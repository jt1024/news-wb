"""P2 回归测试：政策链识别、地市矩阵、周期报告聚合、固定链接产出、飞书卡片链接。

全部使用独立临时库/临时目录，不触碰生产数据。
"""
import json
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app import period_report, publisher
from app.notifier import build_message
from app.trends_extra import STAGE_ORDER, city_topic_matrix, detect_stage, policy_chains


class StageRuleTests(unittest.TestCase):
    def test_priority(self):
        # 征求意见、解读要先于「发布/印发」命中
        self.assertEqual(detect_stage("《XX办法（征求意见稿）》公开征求意见", "notice"), "draft")
        self.assertEqual(detect_stage("《XX条例》政策解读发布会", "news"), "interpretation")
        self.assertEqual(detect_stage("关于印发 XX 实施方案的通知", "news"), "issued")
        self.assertEqual(detect_stage("贯彻落实党的二十届五中全会精神", "news"), "implementation")

    def test_fallback_by_content_type(self):
        self.assertEqual(detect_stage("一则普通标题", "policy"), "issued")
        self.assertEqual(detect_stage("一则普通标题", "interpretation"), "interpretation")
        self.assertIsNone(detect_stage("一则普通标题", "news"))

    def test_common_news_is_not_implementation(self):
        # 「推进/调研/部署」这类泛词不能算政策落地信号
        for title in ("市领导赴企业调研", "推进高质量发展的日常工作", "会议部署下周安排"):
            self.assertIsNone(detect_stage(title, "news"))


class TrendExtraTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        with self.engine.begin() as c:
            c.execute(text("CREATE TABLE news (id INTEGER PRIMARY KEY, title TEXT, region_city TEXT, "
                           "publish_time TEXT, url TEXT, content_type TEXT)"))
            c.execute(text("CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT)"))
            c.execute(text("CREATE TABLE news_tags (news_id INTEGER, tag_id INTEGER)"))
        self.db = sessionmaker(bind=self.engine)()
        today = date.today()
        rows = [
            # 产业：三阶段完整链条
            ("《产业办法（征求意见稿）》征求意见", "广州市", "notice", "产业", 10),
            ("印发产业扶持办法", "广州市", "policy", "产业", 8),
            ("贯彻落实产业扶持办法", "佛山市", "news", "产业", 5),
            # 文旅：仅一阶段，不应成链
            ("文旅活动通知", "珠海市", "notice", "文旅", 3),
        ]
        tag_ids = {}
        with self.engine.begin() as c:
            for i, (title, city, ctype, tag, ago) in enumerate(rows, 1):
                pub = (today - timedelta(days=ago)).isoformat() + " 09:00:00"
                c.execute(text("INSERT INTO news VALUES (:i,:t,:c,:p,:u,:ct)"),
                          {"i": i, "t": title, "c": city, "p": pub,
                           "u": f"https://example.com/{i}", "ct": ctype})
                if tag not in tag_ids:
                    tag_ids[tag] = len(tag_ids) + 1
                    c.execute(text("INSERT INTO tags VALUES (:i,:n)"),
                              {"i": tag_ids[tag], "n": tag})
                c.execute(text("INSERT INTO news_tags VALUES (:n,:t)"),
                          {"n": i, "t": tag_ids[tag]})
        self.start = (today - timedelta(days=30)).isoformat()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_policy_chains(self):
        r = policy_chains(self.db, self.start)
        self.assertEqual(r["signal_total"], 4)
        self.assertEqual(len(r["chains"]), 1)  # 文旅只有一阶段，被排除
        chain = r["chains"][0]
        self.assertEqual(chain["tag"], "产业")
        self.assertEqual(chain["coverage"], 3)
        self.assertEqual([s["stage"] for s in chain["stages"]], STAGE_ORDER)
        self.assertEqual([s["count"] for s in chain["stages"]], [1, 0, 1, 1])
        self.assertEqual(chain["stages"][2]["items"][0]["city"], "广州市")

    def test_city_topic_matrix(self):
        m = city_topic_matrix(self.db, self.start, ["产业", "文旅"], ["广州市", "佛山市", "珠海市"])
        self.assertEqual(len(m["cells"]), 6)
        get = lambda t, c: next(x["n"] for x in m["cells"] if x["topic"] == t and x["city"] == c)
        self.assertEqual(get("产业", "广州市"), 2)
        self.assertEqual(get("产业", "佛山市"), 1)
        self.assertEqual(get("文旅", "珠海市"), 1)
        self.assertEqual(get("文旅", "广州市"), 0)
        self.assertEqual(m["max"], 2)

    def test_empty_inputs(self):
        self.assertEqual(city_topic_matrix(self.db, self.start, [], [])["cells"], [])


class WindowTests(unittest.TestCase):
    def test_weekly_window(self):
        s, e, label, stem = period_report.window("weekly", date(2026, 11, 7))  # 周六
        self.assertEqual((s.isoformat(), e.isoformat()), ("2026-10-26", "2026-11-02"))
        self.assertEqual(stem, "weekly-2026-W44")

    def test_monthly_window(self):
        s, e, label, stem = period_report.window("monthly", date(2026, 11, 7))
        self.assertEqual((s.isoformat(), e.isoformat()), ("2026-10-01", "2026-11-01"))
        self.assertEqual(stem, "monthly-2026-10")

    def test_january_crosses_year(self):
        s, e, _label, stem = period_report.window("monthly", date(2027, 1, 5))
        self.assertEqual(stem, "monthly-2026-12")


class PeriodReportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="news_period_")
        self.db_path = Path(self.tmp) / "news.db"
        conn = sqlite3.connect(self.db_path)
        conn.executescript("""
            CREATE TABLE news (id INTEGER PRIMARY KEY, title TEXT, region_city TEXT,
                publish_time TEXT, url TEXT, content_type TEXT, status TEXT, ai_error TEXT,
                level TEXT DEFAULT 'city', region_org TEXT DEFAULT '');
            CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE news_tags (news_id INTEGER, tag_id INTEGER);
            CREATE TABLE fetch_logs (id INTEGER PRIMARY KEY, started_at TEXT,
                inserted INTEGER, status TEXT);
            CREATE TABLE sources (id INTEGER PRIMARY KEY, name TEXT, region_city TEXT,
                region_district TEXT, enabled INTEGER, region_org TEXT DEFAULT '');
            INSERT INTO sources VALUES (1,'省级','','',1,''),(2,'广州市','广州市','',1,''),
                (3,'天河区','广州市','天河区',1,''),
                (4,'国家发展改革委','','',1,'国家发展改革委');
            INSERT INTO tags VALUES (1,'产业');
            INSERT INTO news (id,title,region_city,publish_time,url,content_type,status,ai_error)
                VALUES (1,'印发产业政策','广州市','2026-10-15 09:00:00',
                'https://example.com/1','policy','interpreted','');
            INSERT INTO news (id,title,region_city,publish_time,url,content_type,status,ai_error)
                VALUES (2,'贯彻落实会议精神','佛山市','2026-10-16 09:00:00',
                'https://example.com/2','news','interpreted','');
            INSERT INTO news (id,title,region_city,publish_time,url,content_type,status,ai_error,level,region_org)
                VALUES (3,'国家发展改革委发布规划解读','','2026-10-17 09:00:00',
                'https://example.com/3','policy','interpreted','','national','国家发展改革委');
            INSERT INTO news_tags VALUES (1,1),(2,1);
            INSERT INTO fetch_logs VALUES (1,'2026-10-15 12:00:00',2,'ok');
        """)
        conn.commit()
        conn.close()
        self.patcher = patch.object(period_report, "DB", self.db_path)
        self.patcher.start()
        self.out_patcher = patch.object(period_report, "OUT_DIR", Path(self.tmp))
        self.out_patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.out_patcher.stop()

    def test_collect(self):
        d = period_report.collect("monthly", date(2026, 11, 7))
        self.assertEqual(d["total"], 3)
        self.assertEqual(d["city_count"], 2)
        self.assertEqual(d["national_count"], 1)
        self.assertEqual(d["rounds"], 1)
        self.assertEqual(d["topics"][0]["tag"], "产业")
        self.assertEqual(d["pending"], 0)
        self.assertEqual(d["all_total"], 3)
        self.assertEqual(d["scope"], "4 源 / 1 地市 / 1 区 / 1 部委")
        self.assertEqual(d["picks"][0]["city"], "国家发展改革委")

    def test_generate_degrades_without_ai(self):
        with patch.object(period_report, "ai_summary", return_value=""):
            d = period_report.generate("monthly", date(2026, 11, 7))
        self.assertTrue(Path(d["html_path"]).exists())
        self.assertTrue(Path(d["md_path"]).exists())
        html = Path(d["html_path"]).read_text(encoding="utf-8")
        self.assertIn("广东政务新闻月报", html)
        self.assertIn("纯统计版", html)
        self.assertIn("数据完整", html)
        md = Path(d["md_path"]).read_text(encoding="utf-8")
        self.assertIn("AI 综述暂不可用", md)

    def test_summary_markdown_contains_url(self):
        d = period_report.collect("monthly", date(2026, 11, 7))
        d["summary"] = "测试综述"
        text = period_report.summary_markdown(d)
        self.assertIn("测试综述", text)
        self.assertIn("完整报告", text)


class PublisherTests(unittest.TestCase):
    def test_publish_local_and_meta(self):
        tmp = Path(tempfile.mkdtemp(prefix="news_pub_"))
        src = tmp / "round.html"
        src.write_text("<html>report</html>", encoding="utf-8")
        with patch.object(publisher, "OUT_DIR", tmp), \
             patch.object(publisher, "LATEST_HTML", tmp / "latest.html"), \
             patch.object(publisher, "LATEST_META", tmp / "latest.meta.json"):
            meta = publisher.publish_local(str(src), "round.md", "2026-11-07 21")
            self.assertEqual(meta["round"], "2026-11-07 21")
            self.assertEqual((tmp / "latest.html").read_text(encoding="utf-8"), "<html>report</html>")
            self.assertEqual(json.loads((tmp / "latest.meta.json").read_text(encoding="utf-8"))["round"],
                             "2026-11-07 21")
            self.assertEqual(publisher.latest_meta()["round"], "2026-11-07 21")


class NotifierLinkTests(unittest.TestCase):
    def _d(self):
        return {
            "key": "2026-11-07 21", "secs": 79,
            "agg": {"sources": 27, "found": 618, "inserted": 9,
                    "duplicated": 607, "failed": 0},
            "news": [("测试标题", "广州市", "2026-11-07", "interpreted", "", "测试源")],
            "logs": [], "total": 728, "interpreted": 728,
            "pending": 0, "ai_err": 0,
        }

    def test_message_with_link(self):
        title, md = build_message(self._d(), "x.html", "https://24hw.cn/abc")
        self.assertIn("在手机上查看最新一轮", md)
        self.assertIn("https://24hw.cn/abc", md)
        self.assertNotIn("data/reports/x.html", md)
        self.assertNotIn("【注意】", title)

    def test_message_without_link(self):
        _title, md = build_message(self._d(), "x.html")
        self.assertIn("data/reports/x.html", md)

    def test_degraded_title(self):
        d = self._d()
        d["pending"] = 5
        title, md = build_message(d, "x.html")
        self.assertIn("【注意】", title)
        self.assertIn("待解读 5", md)


class PermanentAIFailureTests(unittest.TestCase):
    """模型侧确定性拒答必须转终态，否则每轮定时任务都会空转重试。"""

    def test_422_is_permanent(self):
        from app.ai.pipeline import is_permanent_ai_failure

        self.assertTrue(is_permanent_ai_failure(
            "Client error '422 Unprocessable Entity' for url 'https://api.minimax.chat/'"))
        self.assertTrue(is_permanent_ai_failure("HTTP 403 Forbidden"))

    def test_quota_ratelimit_and_network_are_retryable(self):
        from app.ai.pipeline import is_permanent_ai_failure

        for err in ("AI 402：额度不足", "rate limited",
                    "Client error '429 Too Many Requests'", "HTTP 402",
                    "ConnectTimeout", "Server error '500 Internal Server Error'"):
            self.assertFalse(is_permanent_ai_failure(err), err)


if __name__ == "__main__":
    unittest.main()
