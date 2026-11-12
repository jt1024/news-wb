"""港澳台地区维度回归：源配置、迁移、判重隔离、API 与统计口径。

只使用临时库，不触碰生产数据（见 tests/__init__.py）。
"""
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from sqlalchemy import create_engine, text

from app import main as main_module
from app import models  # noqa: F401  确保模型注册到 Base.metadata
from app.api import news as news_api
from app.api import trends as trends_api
from app.crawler.runner import is_duplicate
from app.crawler.sources import AREA_LABELS, SEED_SOURCES
from app.db import Base, SessionLocal, engine
from app.dedup import title_hash, url_hash
from app.models import News, Source


class AreaConfigTests(unittest.TestCase):
    def test_labels_are_canonical(self):
        self.assertEqual(AREA_LABELS, ("中国香港", "中国澳门", "中国台湾", "港澳综合"))

    def test_seed_sources_isolated_from_guangdong(self):
        areas = [c for c in SEED_SOURCES if c.get("level") == "area"]
        self.assertEqual(len(areas), 7)
        self.assertEqual({c["region_area"] for c in areas}, set(AREA_LABELS))
        for c in areas:
            self.assertEqual(c["level"], "area")
            # 省市字段必须留空，否则会被趋势/周月报映射成「广东省」
            for key in ("region_province", "region_city", "region_district", "region_org"):
                self.assertEqual(c.get(key, ""), "", c["name"])
            self.assertTrue(c["selector_config"].get("skip_ai"), c["name"])
            self.assertTrue(c["list_url"].startswith("https://"), c["name"])


class AreaMigrationTests(unittest.TestCase):
    def test_migrate_adds_region_area_to_old_tables(self):
        db_file = Path(tempfile.mkdtemp(prefix="news_area_migrate_")) / "old.db"
        eng = create_engine(f"sqlite:///{db_file}")
        with eng.begin() as conn:
            conn.execute(text("CREATE TABLE news (id INTEGER PRIMARY KEY)"))
            conn.execute(text("CREATE TABLE sources (id INTEGER PRIMARY KEY)"))
        main_module._migrate(eng)
        with eng.connect() as conn:
            for table in ("news", "sources"):
                cols = [r[1] for r in conn.execute(text(f"PRAGMA table_info({table})"))]
                self.assertIn("region_area", cols)
        eng.dispose()


class AreaScopedTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.create_all(engine)
        self.db = SessionLocal()
        for model in (News, models.SkippedURL, Source):
            self.db.query(model).delete()
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def _source(self, area, level="area", city=""):
        s = Source(name="源-" + uuid4().hex, base_url="https://example.gov.cn",
                   list_url="https://example.gov.cn/xw/index.html",
                   region_area=area, level=level, region_city=city,
                   region_province="", region_district="", region_org="")
        self.db.add(s)
        self.db.commit()
        return s

    def _news(self, source, title, url, area=None, level=None, city=None):
        n = News(title=title, url=url, url_hash=url_hash(url), title_hash=title_hash(title),
                 source_id=source.id,
                 region_area=source.region_area if area is None else area,
                 level=source.level if level is None else level,
                 region_city=source.region_city if city is None else city,
                 region_province="", publish_time=datetime.now(), content_text="正文占位内容")
        self.db.add(n)
        self.db.commit()
        return n

    def test_duplicate_scoped_by_area(self):
        hk = self._source("中国香港")
        mo = self._source("中国澳门")
        title = "粤港澳大湾区合作交流活动在两地同步举行"
        self._news(hk, title, "https://example.gov.cn/a.html")
        # 同标题但不同地区、不同源：不能误判为重复
        self.assertFalse(is_duplicate(self.db, mo, url_hash("https://example.gov.cn/b.html"),
                                      title_hash(title), title, ""))
        # 同地区同源：仍应判重
        self.assertTrue(is_duplicate(self.db, hk, url_hash("https://example.gov.cn/c.html"),
                                     title_hash(title), title, ""))

    def test_brief_and_api_area_filter(self):
        hk = self._source("中国香港")
        mo = self._source("中国澳门")
        hk_news = self._news(hk, "香港特别行政区举行青年交流活动", "https://example.gov.cn/hk.html")
        self._news(mo, "澳门特别行政区举办经贸论坛", "https://example.gov.cn/mo.html")

        brief = news_api._brief(hk_news)
        self.assertEqual(brief["area"], "中国香港")
        self.assertEqual(brief["level"], "area")
        self.assertEqual(brief["city"], "")

        # 直接调用时把 Query 默认值全部显式传空串，避免 Query 对象进入 SQL
        kw = dict(city="", district="", level="", org="", type_="", tag="", q="",
                  start="", end="", page=1, size=20, db=self.db)
        res = news_api.list_news(area="中国香港", **kw)
        self.assertEqual(res["total"], 1)
        self.assertEqual(res["items"][0]["area"], "中国香港")
        self.assertEqual(news_api.list_news(**kw)["total"], 2)

    def test_meta_areas_follow_fixed_order(self):
        self._source("中国澳门")
        self._source("中国香港")
        self.assertEqual(news_api.meta(self.db)["areas"], ["中国香港", "中国澳门"])

    def test_trends_exclude_area_news(self):
        hk = self._source("中国香港")
        self._news(hk, "香港特别行政区发布最新经贸合作安排", "https://example.gov.cn/hk.html")
        gd = self._source("", level="city", city="广州市")
        self._news(gd, "广州市部署四季度制造业重点工作", "https://example.gov.cn/gz.html")
        data = trends_api.trends(days=30, db=self.db)
        self.assertEqual(data["total"], 1)
        self.assertEqual([c["city"] for c in data["city_totals"]], ["广州市"])
        self.assertNotIn("广东省", [c["city"] for c in data["city_totals"]])
