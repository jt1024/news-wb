"""增量抓取 / 翻页 / 水位 / 补抓 / 安全抓取的单元测试（全本地，不联网）。"""
import asyncio
import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from app import config
from app import models  # noqa: F401
from app.crawler import politeness
from app.crawler.pagination import is_same_first_url, page_url
from app.crawler.runner import _region_matches, _threshold_for
from app.db import Base, SessionLocal, engine
from app.models import Source


class PaginationTests(unittest.TestCase):
    def test_page_one_returns_original(self):
        url = "https://www.gz.gov.cn/xw/gzyw/index.html"
        self.assertEqual(page_url(url, 1), url)

    def test_index_html(self):
        self.assertEqual(
            page_url("https://www.gz.gov.cn/xw/gzyw/index.html", 2),
            "https://www.gz.gov.cn/xw/gzyw/index_2.html",
        )

    def test_index_shtml(self):
        self.assertEqual(
            page_url("https://www.nhc.gov.cn/xwdt/index.shtml", 3),
            "https://www.nhc.gov.cn/xwdt/index_3.shtml",
        )

    def test_trailing_slash(self):
        self.assertEqual(
            page_url("https://www.zhanjiang.gov.cn/yaowen/", 2),
            "https://www.zhanjiang.gov.cn/yaowen/index_2.html",
        )

    def test_explicit_pattern_wins(self):
        url = "https://www.sz.gov.cn/list.shtml"
        cfg = {"page_pattern": "https://www.sz.gov.cn/list_{page}.shtml"}
        self.assertEqual(page_url(url, 4, cfg), "https://www.sz.gov.cn/list_4.shtml")

    def test_query_param_fallback(self):
        self.assertEqual(
            page_url("https://x.gov.cn/list?type=1", 2),
            "https://x.gov.cn/list?type=1&page=2",
        )

    def test_unknown_shape_returns_none(self):
        """推导不出来就返回 None，让调用方停止翻页，绝不瞎猜打 404。"""
        self.assertIsNone(page_url("https://x.gov.cn/list.html", 2))
        self.assertIsNone(page_url("https://x.gov.cn/list", 2))

    def test_same_first_url(self):
        self.assertTrue(is_same_first_url("https://x/a.html", "https://x/a.html"))
        self.assertFalse(is_same_first_url("https://x/a.html", "https://x/b.html"))
        self.assertFalse(is_same_first_url("", ""))


class WatermarkTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.create_all(engine)
        self.db = SessionLocal()
        self.db.query(Source).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _source(self, **kw):
        s = Source(name="源-" + uuid4().hex, list_url="https://x.gov.cn/index.html", **kw)
        self.db.add(s)
        self.db.commit()
        return s

    def test_no_watermark_means_no_early_stop(self):
        s = self._source()
        self.assertIsNone(_threshold_for(s))

    def test_threshold_is_watermark_minus_overlap(self):
        wm = datetime(2026, 11, 18, 12, 0)
        s = self._source(last_max_publish=wm)
        self.assertEqual(_threshold_for(s),
                         wm - timedelta(days=config.WATERMARK_OVERLAP_DAYS))

    def test_region_match_city(self):
        s = self._source(region_province="广东省", region_city="广州市")
        self.assertTrue(_region_matches(s, {"city": "广州市"}))
        self.assertFalse(_region_matches(s, {"city": "深圳市"}))
        self.assertTrue(_region_matches(s, {"province": "广东省", "city": "广州市"}))
        self.assertFalse(_region_matches(s, {"province": "山东省", "city": "广州市"}))

    def test_region_match_area_and_level(self):
        s = self._source(region_province="", region_city="", region_area="中国香港",
                         level="area")
        self.assertTrue(_region_matches(s, {"area": "中国香港", "level": "area"}))
        self.assertFalse(_region_matches(s, {"area": "中国香港", "level": "province"}))


class PolitenessTests(unittest.TestCase):
    def setUp(self):
        politeness.reset()

    def tearDown(self):
        politeness.reset()

    def test_rate_limit_sets_penalty(self):
        url = "https://www.gz.gov.cn/a.html"
        self.assertFalse(politeness.is_penalized(url))
        politeness.note_rate_limited(url)
        self.assertTrue(politeness.is_penalized(url))
        self.assertEqual(politeness.stats()["penalized_hosts"], 1)

    def test_hosts_are_independent(self):
        politeness.note_rate_limited("https://a.gov.cn/x")
        self.assertFalse(politeness.is_penalized("https://b.gov.cn/x"))

    def test_success_clears_lowest_penalty(self):
        url = "https://www.gz.gov.cn/a.html"
        politeness.note_rate_limited(url)
        politeness.note_success(url)
        self.assertFalse(politeness.is_penalized(url))

    def test_wait_turn_records_host(self):
        asyncio.run(politeness.wait_turn("https://www.gz.gov.cn/a.html"))
        self.assertGreaterEqual(politeness.stats()["tracked_hosts"], 1)


if __name__ == "__main__":
    unittest.main()
