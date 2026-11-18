"""补抓工具改造测试：加锁、有限并发、域名限速占位、分批、软上限。

只用临时库/纯函数，不联网、不碰生产库。
"""
import asyncio
import os
import sqlite3
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
import sys  # noqa: E402
sys.path.insert(0, str(ROOT))

from app.crawler import politeness  # noqa: E402
from app.crawler import runner  # noqa: E402


class PolitenessConcurrencyTests(unittest.TestCase):
    def setUp(self):
        politeness.reset()

    def tearDown(self):
        politeness.reset()

    def test_concurrent_same_host_staggers_not_bursts(self):
        """关键：并发请求同域名必须被占位串行化，不能一起醒来扎堆。"""
        host_urls = [f"https://same.gov.cn/p{i}.html" for i in range(4)]
        wake = []

        async def one(url):
            await politeness.wait_turn(url)
            wake.append(time.monotonic())

        async def job():
            await asyncio.gather(*(one(u) for u in host_urls))

        with patch.object(politeness.config, "DOMAIN_MIN_INTERVAL", 0.2), \
             patch.object(politeness.config, "DOMAIN_JITTER", 0.0):
            asyncio.run(job())

        self.assertEqual(len(wake), 4)
        # 相邻两次唤醒至少间隔约 0.2s（允许调度误差）
        gaps = [wake[i + 1] - wake[i] for i in range(3)]
        self.assertTrue(all(g >= 0.15 for g in gaps), f"请求扎堆了: gaps={gaps}")

    def test_different_hosts_not_serialized(self):
        """不同域名不应互相等待（并发加速的前提）。"""
        urls = [f"https://h{i}.gov.cn/x" for i in range(3)]
        wake = []

        async def one(url):
            await politeness.wait_turn(url)
            wake.append(time.monotonic())

        async def job():
            await asyncio.gather(*(one(u) for u in urls))

        with patch.object(politeness.config, "DOMAIN_MIN_INTERVAL", 0.5), \
             patch.object(politeness.config, "DOMAIN_JITTER", 0.0):
            t0 = time.monotonic()
            asyncio.run(job())
            elapsed = time.monotonic() - t0
        # 若被错误串行，耗时 >= 1.0s；并发应远小于
        self.assertLess(elapsed, 0.4, f"不同域名被串行了: {elapsed:.2f}s")


class BackfillLockTests(unittest.TestCase):
    def test_locked_returns_explicit_flag(self):
        """拿不到抓取轮次锁时，必须明确返回 locked=True，不能静默成功。"""
        from app.round_guard import round_lock

        async def job():
            with round_lock() as got:
                self.assertTrue(got)
                # 同一进程内再抢一次锁（不同 fd）应失败
                return await runner.run_backfill(
                    date_from=datetime(2026, 11, 1),
                    region={"city": "广州市"},
                )

        res = asyncio.run(job())
        self.assertTrue(res.get("locked"), f"应返回 locked，实际 {res}")
        self.assertIn("message", res)
        self.assertEqual(res["inserted"], 0)


class BackfillBatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="bf_test_")
        self.db = str(Path(self.tmp) / "t.db")
        conn = sqlite3.connect(self.db)
        conn.executescript("""
            CREATE TABLE sources (
                id INTEGER PRIMARY KEY, name TEXT, enabled INTEGER DEFAULT 1,
                list_url TEXT, base_url TEXT, fetch_type TEXT DEFAULT 'html',
                selector_config TEXT, level TEXT DEFAULT '', region_province TEXT DEFAULT '',
                region_city TEXT DEFAULT '', region_district TEXT DEFAULT '',
                region_area TEXT DEFAULT '', region_org TEXT DEFAULT '',
                last_fetch_at TEXT, last_max_publish TEXT, consecutive_fail INTEGER DEFAULT 0,
                created_at TEXT
            );
            CREATE TABLE news (
                id INTEGER PRIMARY KEY, title TEXT, content_text TEXT, content_html TEXT,
                url TEXT, url_hash TEXT, title_hash TEXT, simhash_hex TEXT, source_id INTEGER,
                region_province TEXT, region_city TEXT, region_district TEXT, region_area TEXT,
                region_org TEXT, level TEXT, status TEXT, publish_time TEXT, fetch_time TEXT,
                ai_error TEXT DEFAULT '', review_status TEXT DEFAULT ''
            );
            CREATE TABLE fetch_logs (
                id INTEGER PRIMARY KEY, source_id INTEGER, started_at TEXT, finished_at TEXT,
                status TEXT, found INTEGER, inserted INTEGER, duplicated INTEGER, error TEXT
            );
            CREATE TABLE skipped_urls (
                url_hash TEXT PRIMARY KEY, url TEXT, reason TEXT, expires_at TEXT, hit_count INTEGER
            );
        """)
        for i, (name, city) in enumerate([("广州A", "广州市"), ("广州B", "广州市"),
                                          ("深圳C", "深圳市")], 1):
            conn.execute(
                "INSERT INTO sources (id,name,list_url,region_city,region_province,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (i, name, f"https://s{i}.gov.cn/", city, "广东省", "2026-10-01"),
            )
        conn.commit()
        conn.close()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _env(self):
        # db.py 读的是 config.DATABASE_URL（import 时已固定），必须 patch 它并 reload
        return patch("app.config.DATABASE_URL", f"sqlite:///{self.db}")

    def test_source_ids_batch_filters(self):
        """分批：只处理指定的源 ID。"""
        import importlib
        import app.db as dbmod

        with self._env():
            importlib.reload(dbmod)
            importlib.reload(runner)
            seen = []

            async def fake_fetch(source, db, **kw):
                seen.append(source.name)

                class FL:
                    status = "ok"
                    inserted = 0
                    found = 10

                fl = FL()
                fl.error = None
                return fl

            with patch.object(runner, "fetch_source", side_effect=fake_fetch):
                res = asyncio.run(runner.run_backfill(
                    date_from=datetime(2026, 11, 1),
                    source_ids=[1, 3],
                    concurrency=2,
                ))
            self.assertEqual(res["sources"], 2)
            self.assertEqual(set(seen), {"广州A", "深圳C"})

    def test_backfill_failure_does_not_touch_circuit_counter(self):
        """补抓失败不能污染日常抓取的熔断计数（历史回溯失败与日常无关）。

        直接调真实 fetch_source：patch Fetcher 让列表页抛异常，分别验证
        补抓模式 consecutive_fail 不变、日常模式会 +1。
        """
        import importlib
        import app.db as dbmod

        with self._env():
            importlib.reload(dbmod)
            importlib.reload(runner)

            class BoomFetcher:
                def __init__(self, *a, **k):
                    pass

                async def fetch_list(self, *a, **k):
                    raise RuntimeError("simulated list failure")

            async def run(mode):
                sdb = dbmod.SessionLocal()
                try:
                    s = sdb.get(runner.Source, 1)
                    s.consecutive_fail = 1
                    sdb.commit()
                    kw = {"backfill": {"date_from": datetime(2026, 11, 1),
                                       "date_to": datetime(2026, 11, 3)}} if mode == "backfill" else {}
                    await runner.fetch_source(s, sdb, **kw)
                    sdb.refresh(s)
                    return s.consecutive_fail
                finally:
                    sdb.close()

            with patch.object(runner, "Fetcher", BoomFetcher):
                after_bf = asyncio.run(run("backfill"))
                after_daily = asyncio.run(run("daily"))
            self.assertEqual(after_bf, 1, "补抓失败不应改变 consecutive_fail")
            self.assertEqual(after_daily, 2, "日常抓取失败应 +1")

    def test_over_cap_does_not_break_batch(self):
        """达到提示阈值不应中断本批（每批跑完）。"""
        import importlib
        import app.db as dbmod

        with self._env():
            importlib.reload(dbmod)
            importlib.reload(runner)
            seen = []

            async def fake_fetch(source, db, **kw):
                seen.append(source.name)

                class FL:
                    status = "ok"
                    inserted = 3000  # 单源就超过 2000 提示阈值
                    found = 3000
                    error = None

                return FL()

            with patch.object(runner, "fetch_source", side_effect=fake_fetch), \
                 patch.object(runner.config, "BACKFILL_ITEM_MAX", 2000):
                res = asyncio.run(runner.run_backfill(
                    date_from=datetime(2026, 11, 1),
                    region={"city": "广州市"},
                    concurrency=2,
                ))
            # 两个广州源都应被处理，不因首个超限而中断
            self.assertEqual(res["sources"], 2)
            self.assertEqual(res["inserted"], 6000)


if __name__ == "__main__":
    unittest.main()
