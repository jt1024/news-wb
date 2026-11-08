"""三层去重：URL 归一化 / 标题指纹与相似度 / 正文 SimHash。"""
import unittest
from datetime import datetime, timedelta
from uuid import uuid4

from app import models  # noqa: F401  确保模型注册到 Base.metadata
from app.crawler.runner import is_duplicate
from app.db import Base, SessionLocal, engine
from app.dedup import (
    hamming_distance_hex,
    normalize_title,
    normalize_url,
    simhash64,
    title_hash,
    title_similarity,
    url_hash,
)
from app.models import News, Source


class PureFunctionTests(unittest.TestCase):
    def test_normalize_url(self):
        self.assertEqual(
            normalize_url("http://WWW.Example.GOV.CN:80/a/b/?utm_source=x&b=2&a=1#frag"),
            "https://example.gov.cn/a/b?a=1&b=2",
        )
        self.assertEqual(normalize_url("https://www.gd.gov.cn/"), "https://gd.gov.cn/")

    def test_url_hash_stable_and_sensitive(self):
        self.assertEqual(url_hash("http://www.gd.gov.cn/a.html?utm_source=x"),
                         url_hash("https://gd.gov.cn/a.html"))
        self.assertNotEqual(url_hash("https://gd.gov.cn/a.html"), url_hash("https://gd.gov.cn/b.html"))
        self.assertEqual(len(url_hash("https://gd.gov.cn/a.html")), 64)

    def test_normalize_title(self):
        self.assertEqual(normalize_title("关于做好２０２６年ＡＢＣ工作 的通知！"),
                         "关于做好2026年abc工作的通知")

    def test_title_hash_and_similarity(self):
        self.assertEqual(title_hash("同一标题！"), title_hash("同一标题"))
        self.assertEqual(title_similarity("同一标题", "同一标题"), 1.0)
        self.assertLess(title_similarity("abcdefgh", "zzzzzzzz"), 0.5)
        self.assertEqual(title_similarity("", "abc"), 0.0)

    def test_simhash(self):
        text = "广东省推进制造业高质量发展若干政策措施，支持企业技术改造与数字化转型。" * 6
        a, b = simhash64(text), simhash64(text)
        self.assertEqual(len(a), 16)
        self.assertEqual(hamming_distance_hex(a, b), 0)
        c = simhash64("天气预报显示本周将有明显降温，市民出行请注意添衣保暖。" * 6)
        self.assertNotEqual(a, c)


class IsDuplicateTests(unittest.TestCase):
    """用临时 SQLite 库验证三层判定的真实 SQL 行为。"""

    def setUp(self):
        Base.metadata.create_all(engine)
        self.db = SessionLocal()
        for model in (News, models.SkippedURL, Source):
            self.db.query(model).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _source(self, city="广州市", district=""):
        s = Source(name="源-" + uuid4().hex, base_url="https://www.example.gov.cn",
                   list_url="https://www.example.gov.cn/ywdt/index.html",
                   region_city=city, region_district=district)
        self.db.add(s)
        self.db.commit()
        return s

    def _news(self, source, title, url, sim="", city=None, days_ago=0, district=None):
        n = News(
            title=title, url=url, url_hash=url_hash(url), title_hash=title_hash(title),
            simhash_hex=sim, source_id=source.id,
            region_city=city or source.region_city,
            region_district=(source.region_district or "") if district is None else district,
            publish_time=datetime.now() - timedelta(days=days_ago),
            content_text="正文占位",
        )
        self.db.add(n)
        self.db.commit()
        return n

    def _dup(self, source, title, url, sim=""):
        return is_duplicate(self.db, source, url_hash(url), title_hash(title), title, sim)

    def test_layer1_same_url(self):
        s = self._source()
        self._news(s, "广州市召开经济工作会议部署四季度重点工作", "https://www.example.gov.cn/a.html")
        self.assertTrue(self._dup(s, "完全不同的另一个标题内容", "http://www.example.gov.cn/a.html?utm_source=x"))

    def test_layer2_title_hash_same_city(self):
        s = self._source()
        title = "广州市召开经济工作会议部署四季度重点工作"
        self._news(s, title, "https://www.example.gov.cn/a.html")
        self.assertTrue(self._dup(s, title, "https://www.example.gov.cn/b.html"))

    def test_layer2_scoped_by_city(self):
        s = self._source()
        title = "广州市召开经济工作会议部署四季度重点工作"
        self._news(s, title, "https://www.example.gov.cn/a.html", city="深圳市")
        other = self._source(city="广州市")
        # 同标题但历史文章属于其他城市、且不是同源，不应误判
        self.assertFalse(self._dup(other, title, "https://www.example.gov.cn/b.html"))

    def test_layer2_scoped_by_district(self):
        """广州 11 区同属广州市，同题通稿不能被跨区误判为重复。"""
        title = "全区传达学习贯彻党的二十届五中全会精神干部大会召开"
        haizhu = self._source(district="海珠区")
        self._news(haizhu, title, "https://www.example.gov.cn/a.html")
        baiyun = self._source(district="白云区")
        self.assertFalse(self._dup(baiyun, title, "https://www.example.gov.cn/b.html"))

    def test_layer2_same_district_still_dedups(self):
        title = "全区传达学习贯彻党的二十届五中全会精神干部大会召开"
        s = self._source(district="从化区")
        self._news(s, title, "https://www.example.gov.cn/a.html")
        self.assertTrue(self._dup(s, title, "https://www.example.gov.cn/b.html"))

    def test_city_level_source_keeps_legacy_matching(self):
        """历史市级文章 region_district 为空，市级源仍能命中标题判重。"""
        title = "广州市召开经济工作会议部署四季度重点工作"
        s = self._source()
        self._news(s, title, "https://www.example.gov.cn/a.html")
        self.assertTrue(self._dup(s, title, "https://www.example.gov.cn/b.html"))

    def test_layer2_title_similarity_same_source(self):
        s = self._source()
        self._news(s, "关于进一步做好2026年全市政务公开工作的通知", "https://www.example.gov.cn/a.html")
        self.assertTrue(self._dup(s, "关于进一步做好2026年全市政务公开工作的通知呀",
                                 "https://www.example.gov.cn/b.html"))

    def test_layer3_simhash(self):
        s = self._source()
        sim = simhash64("广东省推进制造业高质量发展若干政策措施" * 6)
        self._news(s, "甲市出台产业扶持政策", "https://www.example.gov.cn/a.html", sim=sim)
        self.assertTrue(self._dup(s, "乙市发布文旅消费券", "https://www.example.gov.cn/b.html", sim=sim))

    def test_unrelated_article_not_duplicate(self):
        s = self._source()
        self._news(s, "甲市出台产业扶持政策", "https://www.example.gov.cn/a.html")
        self.assertFalse(self._dup(s, "乙市召开防汛抗旱工作电视电话会议",
                                   "https://www.example.gov.cn/b.html"))

    def test_old_article_outside_60_day_window(self):
        s = self._source()
        self._news(s, "关于进一步做好2026年全市政务公开工作的通知",
                   "https://www.example.gov.cn/a.html", days_ago=90)
        self.assertFalse(self._dup(s, "关于进一步做好2026年全市政务公开工作的通知呀",
                                   "https://www.example.gov.cn/b.html"))


if __name__ == "__main__":
    unittest.main()
