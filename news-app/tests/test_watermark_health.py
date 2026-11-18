"""水位健康判定 + 报告/推送集成的单测（全本地，不联网）。"""
import os
import sqlite3
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app import notifier  # noqa: E402
from app.watermark_health import (  # noqa: E402
    analyze_watermarks, unavailable_result, summary_line, track_paged_sources,
    LEVEL_OK, LEVEL_WARN, LEVEL_DANGER,
)
import execution_report as report  # noqa: E402


NOW = datetime(2026, 11, 18, 12, 0, 0)


def src(name, *, wm_days=None, fails=0, created_days=30):
    return {
        "name": name,
        "last_max_publish": (NOW - timedelta(days=wm_days)) if wm_days is not None else None,
        "consecutive_fail": fails,
        "created_at": NOW - timedelta(days=created_days),
    }


class WatermarkHealthTests(unittest.TestCase):
    def test_all_healthy(self):
        rows = [src("甲源", wm_days=1), src("乙源", wm_days=3)]
        r = analyze_watermarks(rows, NOW, stall_days=3)
        self.assertEqual(r["abnormal"], 0)
        self.assertEqual(r["healthy"], 2)
        self.assertEqual(r["worst"], LEVEL_OK)

    def test_stalled_warn_and_danger_by_age(self):
        rows = [src("停滞源", wm_days=5)]       # >3 且 <=6 → warn
        r = analyze_watermarks(rows, NOW, stall_days=3)
        self.assertEqual(r["issues"][0]["kind"], "stalled")
        self.assertEqual(r["issues"][0]["level"], LEVEL_WARN)
        self.assertEqual(r["issues"][0]["age_days"], 5)

        rows = [src("重度停滞", wm_days=9)]     # >6 → danger
        r = analyze_watermarks(rows, NOW, stall_days=3)
        self.assertEqual(r["issues"][0]["level"], LEVEL_DANGER)

    def test_circuit_is_danger_and_wins_over_other(self):
        rows = [src("熔断源", wm_days=20, fails=3)]
        r = analyze_watermarks(rows, NOW, stall_days=3, circuit_threshold=3)
        self.assertEqual(len(r["issues"]), 1)
        self.assertEqual(r["issues"][0]["kind"], "circuit")
        self.assertEqual(r["issues"][0]["level"], LEVEL_DANGER)
        self.assertEqual(r["worst"], LEVEL_DANGER)

    def test_never_watermark_new_source_is_ok(self):
        # 覆盖率已达标（10 个源中 9 个有水位），新源启用仅 1 天、水位为空 → 正常建立期
        rows = [src(f"正常源{i}", wm_days=1) for i in range(9)] + [src("新源", wm_days=None, created_days=1)]
        r = analyze_watermarks(rows, NOW, grace_days=2)
        self.assertFalse(r["cold_start"])
        self.assertEqual(r["abnormal"], 0)
        self.assertEqual(r["healthy"], 10)

    def test_never_watermark_old_source_is_warn(self):
        # 覆盖率已达标，个别老源仍无水位 → 异常
        rows = [src(f"正常源{i}", wm_days=1) for i in range(9)] + [src("老源无水位", wm_days=None, created_days=30)]
        r = analyze_watermarks(rows, NOW, grace_days=2)
        self.assertEqual(r["issues"][0]["kind"], "never")
        self.assertEqual(r["issues"][0]["level"], LEVEL_WARN)

    def test_cold_start_downgrades_never_to_pending(self):
        # 冷启动：大部分源无水位（覆盖率 < 50%）→ 不报异常，降级为待覆盖
        rows = [src(f"无水位源{i}", wm_days=None, created_days=30) for i in range(9)] + [src("唯一有水位", wm_days=1)]
        r = analyze_watermarks(rows, NOW, stall_days=3)
        self.assertTrue(r["cold_start"])
        self.assertEqual(r["abnormal"], 0)
        self.assertEqual(len(r["pending"]), 9)
        self.assertEqual(r["worst"], LEVEL_OK)
        self.assertAlmostEqual(r["coverage"], 0.1, places=2)

    def test_cold_start_still_catches_stalled_and_circuit(self):
        # 冷启动期也不能漏掉真正的停滞/熔断
        rows = [src(f"无水位源{i}", wm_days=None, created_days=30) for i in range(9)]
        rows += [src("停滞源", wm_days=8), src("熔断源", wm_days=1, fails=3)]
        r = analyze_watermarks(rows, NOW, stall_days=3)
        self.assertTrue(r["cold_start"])
        self.assertEqual(r["abnormal"], 2)
        kinds = {i["kind"] for i in r["issues"]}
        self.assertEqual(kinds, {"stalled", "circuit"})
        self.assertEqual(r["worst"], LEVEL_DANGER)

    def test_issues_sorted_danger_first(self):
        rows = [src("停滞源", wm_days=4), src("熔断源", fails=3), src("无水位源", created_days=30)]
        r = analyze_watermarks(rows, NOW, stall_days=3)
        levels = [i["level"] for i in r["issues"]]
        self.assertEqual(levels, sorted(levels, key=lambda x: {LEVEL_DANGER: 0, LEVEL_WARN: 1}[x]))

    def test_summary_line(self):
        self.assertIn("3/3 源正常", summary_line({"available": True, "healthy": 3, "total": 3, "abnormal": 0, "issues": []}))
        s = summary_line({"available": True, "healthy": 1, "total": 4, "abnormal": 3,
                          "issues": [{"kind": "stalled"}, {"kind": "stalled"}, {"kind": "circuit"}]})
        self.assertIn("水位异常 3 源", s)
        self.assertIn("停滞 2", s)
        self.assertIn("熔断 1", s)
        self.assertEqual(summary_line(unavailable_result()), "")
        cold = summary_line({"available": True, "healthy": 1, "total": 190, "abnormal": 0,
                             "cold_start": True, "coverage": 0.005, "pending": [{}] * 189, "issues": []})
        self.assertIn("上线初期", cold)
        self.assertIn("189 源待覆盖", cold)
        self.assertNotIn("异常", cold)

    def test_parse_dt_variants(self):
        from app.watermark_health import parse_dt
        self.assertEqual(parse_dt(None), None)
        self.assertEqual(parse_dt("2026-11-18 12:00:00"), datetime(2026, 11, 18, 12, 0, 0))
        self.assertEqual(parse_dt("2026-11-18T12:00:00"), datetime(2026, 11, 18, 12, 0, 0))
        self.assertEqual(parse_dt(datetime(2026, 11, 18)), datetime(2026, 11, 18))
        self.assertIsNone(parse_dt("garbage"))


class PagedSourceTrackingTests(unittest.TestCase):
    """已配翻页模板源的单独跟踪：只可见/可跟踪，待建立不算异常。"""

    def _row(self, name, *, paged=True, wm_days=None, created_days=1, fails=0, paged_days=None):
        r = src(name, wm_days=wm_days, created_days=created_days, fails=fails)
        r["has_page_pattern"] = paged
        # 宽限期基准是分页配置日期；未显式指定时与 created_days 一致
        pd = created_days if paged_days is None else paged_days
        r["paged_at"] = (NOW - timedelta(days=pd)) if pd is not None else None
        return r

    def test_only_paged_rows_tracked(self):
        rows = [self._row("配了分页", paged=True, wm_days=1),
                self._row("没配分页", paged=False, wm_days=1)]
        out = track_paged_sources(rows, NOW)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "配了分页")

    def test_new_paged_no_watermark_is_pending_not_alarm(self):
        # 刚配好 1 天、水位空 → 待建立，级别 ok，不制造异常
        out = track_paged_sources([self._row("新配源", wm_days=None, created_days=1)], NOW)
        self.assertEqual(out[0]["status"], "pending")
        self.assertEqual(out[0]["level"], LEVEL_OK)

    def test_paged_no_watermark_past_grace_is_warn(self):
        # 分页配了 10 天仍无水位 → 分页疑似失效，warn
        out = track_paged_sources([self._row("老配源", wm_days=None, created_days=30,
                                             paged_days=10)], NOW)
        self.assertEqual(out[0]["status"], "stale")
        self.assertEqual(out[0]["level"], LEVEL_WARN)

    def test_source_created_long_ago_but_paged_today_is_pending(self):
        # 回归：源 13 天前入库、今天才配分页、水位空 → 应判"待建立"而非误报失效
        out = track_paged_sources([self._row("今天才配", wm_days=None,
                                             created_days=13, paged_days=0)], NOW)
        self.assertEqual(out[0]["status"], "pending")
        self.assertEqual(out[0]["level"], LEVEL_OK)

    def test_paged_with_fresh_watermark_is_established(self):
        out = track_paged_sources([self._row("正常源", wm_days=1)], NOW)
        self.assertEqual(out[0]["status"], "established")
        self.assertEqual(out[0]["level"], LEVEL_OK)

    def test_paged_stalled_watermark_is_flagged(self):
        out = track_paged_sources([self._row("停滞源", wm_days=8)], NOW)
        self.assertEqual(out[0]["status"], "stalled")
        self.assertEqual(out[0]["level"], LEVEL_DANGER)

    def test_paged_circuit_is_danger(self):
        out = track_paged_sources([self._row("熔断源", fails=3)], NOW, circuit_threshold=3)
        self.assertEqual(out[0]["status"], "circuit")
        self.assertEqual(out[0]["level"], LEVEL_DANGER)

    def test_paged_does_not_inflate_abnormal(self):
        # 7 个刚配的源水位空、冷启动：paged 有值，但 abnormal 仍为 0
        rows = [self._row(f"新配源{i}", wm_days=None, created_days=1) for i in range(7)]
        r = analyze_watermarks(rows, NOW)
        self.assertEqual(r["abnormal"], 0)
        self.assertEqual(len(r["paged"]), 7)

    def test_summary_line_mentions_paged_count(self):
        r = analyze_watermarks([self._row(f"新配源{i}", wm_days=None, created_days=1)
                                for i in range(7)], NOW)
        self.assertIn("已配翻页 7 源", summary_line(r))


class ReportWatermarkTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.executescript("""
            CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT, region_city TEXT,
                region_org TEXT DEFAULT '', region_province TEXT DEFAULT '广东省',
                region_area TEXT DEFAULT '', last_max_publish TEXT,
                consecutive_fail INTEGER DEFAULT 0, created_at TEXT,
                enabled INTEGER DEFAULT 1);
            CREATE TABLE fetch_logs (id INTEGER PRIMARY KEY, source_id INTEGER, started_at TEXT,
                finished_at TEXT, status TEXT, found INTEGER, inserted INTEGER,
                duplicated INTEGER, error TEXT);
            CREATE TABLE news (id INTEGER PRIMARY KEY, title TEXT, region_city TEXT,
                publish_time TEXT, status TEXT, ai_error TEXT, source_id INTEGER,
                fetch_time TEXT, region_org TEXT DEFAULT '',
                region_province TEXT DEFAULT '广东省', region_area TEXT DEFAULT '');
            INSERT INTO sources (id,name,region_city,last_max_publish,created_at) VALUES
              (1,'正常源','甲市','2026-11-17 10:00:00','2026-09-01 00:00:00'),
              (2,'停滞源','乙市','2026-11-05 10:00:00','2026-09-01 00:00:00');
            INSERT INTO fetch_logs VALUES
              (1,1,'2026-11-18 12:00:10','2026-11-18 12:00:50','ok',10,2,8,'');
        """)

    def tearDown(self):
        self.conn.close()

    def test_load_watermark_detects_columns(self):
        wm = report.load_watermark(self.conn)
        self.assertTrue(wm["available"])
        self.assertEqual(wm["total"], 2)
        self.assertGreaterEqual(wm["abnormal"], 1)  # 停滞源

    def test_load_watermark_missing_columns_is_graceful(self):
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT)")
        wm = report.load_watermark(conn)
        self.assertFalse(wm["available"])
        conn.close()

    def test_markdown_has_watermark_section(self):
        d = report.load_round(self.conn, *report.rounds(self.conn)[0])
        md = report.build_markdown(d, None, [])
        self.assertIn("## 四、水位健康", md)
        self.assertIn("停滞源", md)
        self.assertIn("处置", md)

    def test_html_has_watermark_section(self):
        d = report.load_round(self.conn, *report.rounds(self.conn)[0])
        html = report.build_html(d, None, [])
        self.assertIn("四、水位健康", html)
        self.assertIn("停滞源", html)
        self.assertIn("处置建议", html)

    def test_cold_start_section_shows_pending_not_alarm(self):
        # 构造冷启动库：10 源仅 1 个有水位
        conn = sqlite3.connect(":memory:")
        conn.executescript("""
            CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT, last_max_publish TEXT,
                consecutive_fail INTEGER DEFAULT 0, created_at TEXT, enabled INTEGER DEFAULT 1);
        """)
        for i in range(9):
            conn.execute("INSERT INTO sources (id,name,created_at) VALUES (?,?,?)",
                         (i, f"待覆盖源{i}", "2026-09-01 00:00:00"))
        conn.execute("INSERT INTO sources (id,name,last_max_publish,created_at) VALUES (?,?,?,?)",
                     (9, "有水位源", "2026-11-17 00:00:00", "2026-09-01 00:00:00"))
        wm = report.load_watermark(conn)
        self.assertTrue(wm["cold_start"])
        self.assertEqual(wm["abnormal"], 0)
        conn.close()
        # 直接渲染一个带冷启动 watermark 的最小轮次数据
        d = report.load_round(self.conn, *report.rounds(self.conn)[0])
        d["watermark"] = wm
        md = report.build_markdown(d, None, [])
        self.assertIn("水位功能上线初期", md)
        self.assertIn("9 源待后续轮次覆盖", md)


class NotifierWatermarkTests(unittest.TestCase):
    def _d(self, wm):
        d = {
            "key": "2026-11-18 12",
            "agg": {"sources": 20, "ok": 20, "failed": 0, "found": 500,
                    "inserted": 10, "duplicated": 490, "noted": 0},
            "secs": 60, "news": [], "logs": [], "total": 700,
            "pending": 0, "ai_err": 0, "interpreted": 700,
            "watermark": wm,
        }
        return d

    def test_title_flags_watermark_when_no_pending(self):
        wm = {"available": True, "healthy": 18, "total": 20, "abnormal": 2,
              "worst": LEVEL_WARN, "stall_days": 3,
              "issues": [{"kind": "stalled"}, {"kind": "circuit"}]}
        title, md = notifier.build_message(self._d(wm), "r.html")
        self.assertIn("【注意】", title)
        self.assertIn("水位异常 2 源", title)
        self.assertIn("水位停滞", md)
        self.assertIn("需要关注", md)

    def test_clean_watermark_no_false_alarm(self):
        wm = {"available": True, "healthy": 20, "total": 20, "abnormal": 0,
              "worst": LEVEL_OK, "stall_days": 3, "issues": []}
        title, md = notifier.build_message(self._d(wm), "r.html")
        self.assertNotIn("【注意】", title)
        self.assertNotIn("需核实", md)

    def test_danger_watermark_makes_card_red(self):
        wm = {"available": True, "healthy": 10, "total": 20, "abnormal": 10,
              "worst": LEVEL_DANGER, "stall_days": 3,
              "issues": [{"kind": "stalled"} for _ in range(7)]
                        + [{"kind": "circuit"} for _ in range(3)]}
        env = {"NOTIFY_CHANNEL": "feishu", "NOTIFY_WEBHOOK": "http://127.0.0.1:9/hook",
               "NOTIFY_SECRET": ""}
        with patch.dict(os.environ, env), \
             patch.object(notifier, "_post", return_value=(200, '{"StatusCode":0}')) as post, \
             patch("app.publisher.public_url", return_value=""):
            res = notifier.push_report(self._d(wm), "r.html", "r.md")
        self.assertTrue(res["ok"])
        payload = post.call_args[0][1]
        self.assertEqual(payload["card"]["header"]["template"], "red")
        # 标题带水位异常摘要，正文「需要关注」列出分类计数
        self.assertIn("水位异常 10 源", payload["card"]["header"]["title"]["content"])
        self.assertIn("水位停滞 7 源", payload["card"]["elements"][0]["text"]["content"])


if __name__ == "__main__":
    unittest.main()
