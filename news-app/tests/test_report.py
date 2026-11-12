"""报告与推送：轮次聚合、cron 解析、飞书签名、消息降级与分发。"""
import base64
import hashlib
import hmac
import os
import sqlite3
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import execution_report as report  # noqa: E402

from app import config, notifier  # noqa: E402


def _fixture_db():
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT, region_city TEXT,
            region_org TEXT DEFAULT '', region_province TEXT DEFAULT '广东省',
            region_area TEXT DEFAULT '');
        CREATE TABLE fetch_logs (
            id INTEGER PRIMARY KEY, source_id INTEGER, started_at TEXT, finished_at TEXT,
            status TEXT, found INTEGER, inserted INTEGER, duplicated INTEGER, error TEXT);
        CREATE TABLE news (
            id INTEGER PRIMARY KEY, title TEXT, region_city TEXT, publish_time TEXT,
            status TEXT, ai_error TEXT, source_id INTEGER, fetch_time TEXT,
            region_org TEXT DEFAULT '', region_province TEXT DEFAULT '广东省',
            region_area TEXT DEFAULT '');
        INSERT INTO sources (id,name,region_city) VALUES
          (1, '测试源甲', '甲市'), (2, '测试源乙', '乙市');
        INSERT INTO fetch_logs VALUES
          (1, 1, '2026-11-07 12:00:10.000000', '2026-11-07 12:00:50.000000',
           'ok', 10, 2, 8, ''),
          (2, 2, '2026-11-07 12:00:15.000000', '2026-11-07 12:00:45.000000',
           'ok', 8, 1, 7, '1 篇空正文已跳过'),
          (3, 1, '2026-11-07 21:00:00.000000', '2026-11-07 21:00:40.000000',
           'ok', 5, 1, 4, '');
        INSERT INTO news (id,title,region_city,publish_time,status,ai_error,source_id,fetch_time)
          VALUES
          (1, '甲市召开经济工作会议', '甲市', '2026-11-07 09:00:00',
           'interpreted', '', 1, '2026-11-07 12:00:30.000000'),
          (2, '乙市发布产业扶持政策', '乙市', '2026-11-07 10:00:00',
           'interpreted', '', 2, '2026-11-07 12:00:35.000000');
        INSERT INTO news (id,title,region_city,publish_time,status,ai_error,source_id,fetch_time,region_org)
          VALUES (3, '国家发展改革委发布规划解读', '', '2026-11-07 18:00:00',
           'interpreted', '', 1, '2026-11-07 21:00:20.000000', '国家发展改革委');
        """
    )
    return conn


class RoundAggregationTests(unittest.TestCase):
    def setUp(self):
        self.conn = _fixture_db()

    def tearDown(self):
        self.conn.close()

    def test_rounds_group_by_date_hour_latest_first(self):
        rs = report.rounds(self.conn)
        self.assertEqual([r[0] for r in rs], ["2026-11-07 21", "2026-11-07 12"])

    def test_load_round_aggregates(self):
        d = report.load_round(self.conn, *report.rounds(self.conn)[0])
        a = d["agg"]
        self.assertEqual((a["sources"], a["ok"], a["failed"]), (1, 1, 0))
        self.assertEqual((a["found"], a["inserted"], a["duplicated"]), (5, 1, 4))
        self.assertEqual(d["secs"], 40)
        self.assertEqual(len(d["news"]), 1)
        # 国家级新闻 city 为空，报告里应显示机构名而不是「—」或「广东省」
        self.assertEqual(d["news"][0][1], "国家发展改革委")

    def test_news_window_uses_sql_datetime_format(self):
        """回归：ISO 的 T 分隔符曾导致本轮新增永远查不到。"""
        d = report.load_round(self.conn, *report.rounds(self.conn)[1])
        self.assertEqual(len(d["news"]), 2)
        self.assertEqual(d["agg"]["inserted"], 3)
        self.assertEqual(d["agg"]["noted"], 1)
        self.assertEqual(d["total"], 3)
        self.assertEqual(d["pending"], 0)

    def test_slot_label(self):
        self.assertEqual(report.slot_label(6), "早间轮")
        self.assertEqual(report.slot_label(12), "午间轮")
        self.assertEqual(report.slot_label(21), "晚间轮")
        self.assertEqual(report.slot_label(1), "手动/补跑")


class CronTests(unittest.TestCase):
    def test_dedup_and_sort(self):
        with patch.dict(os.environ, {"CRON_HOURS": "21,6,12,12", "CRON_HOUR": "7"}):
            self.assertEqual(config._parse_cron_hours(), [6, 12, 21])

    def test_invalid_value_falls_back(self):
        with patch.dict(os.environ, {"CRON_HOURS": "bad,12", "CRON_HOUR": "8"}):
            self.assertEqual(config._parse_cron_hours(), [8])

    def test_empty_falls_back_to_legacy_hour(self):
        with patch.dict(os.environ, {"CRON_HOURS": "", "CRON_HOUR": "9"}):
            self.assertEqual(config._parse_cron_hours(), [9])


def _sample_round(pending=0, ai_err=0, failed=0):
    return {
        "key": "2026-11-07 21",
        "agg": {"sources": 27, "ok": 27 - failed, "failed": failed,
                "found": 618, "inserted": 9, "duplicated": 607, "noted": 1},
        "secs": 79,
        "news": [("佛山市召开干部大会传达学习五中全会精神", "佛山市", "2026-11-07 09:00:00",
                  "interpreted", "", "佛山源")],
        "logs": [(1, "", "", "ok", 30, 1, 29, "1 篇空正文已跳过", "河源源", "河源市")],
        "total": 728, "pending": pending, "ai_err": ai_err, "interpreted": 728 - pending,
    }


class NotifierTests(unittest.TestCase):
    def test_feishu_signature_matches_official_algorithm(self):
        secret = "unit-test-secret"
        ts, sign = notifier._feishu_sign(secret)
        expected = base64.b64encode(
            hmac.new(f"{ts}\n{secret}".encode("utf-8"), digestmod=hashlib.sha256).digest()
        ).decode("utf-8")
        self.assertEqual(sign, expected)
        self.assertTrue(ts.isdigit())
        self.assertLess(abs(int(ts) - time.time()), 5)
        self.assertNotEqual(notifier._feishu_sign("another-secret")[1], sign)

    def test_message_normal_and_degraded(self):
        title, md = notifier.build_message(_sample_round(), "report.html")
        self.assertIn("新增 9 篇", title)
        self.assertNotIn("【注意】", title)
        self.assertIn("全库 728 篇", md)
        self.assertIn("异常与处置", md)

        title2, md2 = notifier.build_message(_sample_round(pending=5, ai_err=2), "report.html")
        self.assertIn("【注意】", title2)
        self.assertIn("待解读 5", title2)
        self.assertIn("需要关注", md2)
        self.assertIn("待解读部分下轮自动补", md2)
        self.assertIn("模型明确拒答的已跳过", md2)

    def test_dispatch_off_skips(self):
        with patch.dict(os.environ, {"NOTIFY_CHANNEL": "off"}):
            self.assertTrue(notifier._dispatch("t", "m")["skipped"])

    def test_dispatch_feishu_with_signature_and_red_header(self):
        env = {"NOTIFY_CHANNEL": "feishu", "NOTIFY_WEBHOOK": "http://127.0.0.1:9/hook",
               "NOTIFY_SECRET": "sec"}
        with patch.dict(os.environ, env), \
             patch.object(notifier, "_post", return_value=(200, '{"StatusCode":0}')) as post:
            result = notifier._dispatch("告警", "内容", red=True)
        self.assertTrue(result["ok"])
        payload = post.call_args[0][1]
        self.assertEqual(payload["card"]["header"]["template"], "red")
        self.assertIn("timestamp", payload)
        self.assertIn("sign", payload)

    def test_push_failure_never_raises(self):
        env = {"NOTIFY_CHANNEL": "feishu", "NOTIFY_WEBHOOK": "http://127.0.0.1:9/hook",
               "NOTIFY_SECRET": ""}
        with patch.dict(os.environ, env), \
             patch.object(notifier, "_post", side_effect=OSError("network down")), \
             self.assertLogs("notifier", level="WARNING"):
            result = notifier._dispatch("t", "m")
        self.assertFalse(result["ok"])


if __name__ == "__main__":
    unittest.main()
