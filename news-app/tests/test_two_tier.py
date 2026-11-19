"""两档解读 + 冷启动 60 天下限的单元测试（临时库，不联网）。"""
import asyncio
import importlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402


class TwoTierBase(unittest.TestCase):
    """公共环境：临时库 + reload db/runner/pipeline。"""

    def _env(self):
        return patch("app.config.DATABASE_URL", f"sqlite:///{self.db_path}")

    def setUp(self):
        tmp = tempfile.mkdtemp(prefix="news_two_tier_")
        self.db_path = str(Path(tmp) / "test.db")
        with self._env():  # reload 必须在 DATABASE_URL 补丁内进行
            self._reload()
        # 模型类绑定在 app.models 持有的原始 Base 上（reload app.db 会生成
        # 新 Base，但模型不会重挂），用原始 metadata 在新引擎上建表。
        from app.models import Base
        Base.metadata.create_all(self.dbmod.engine)
        self.sdb = self.dbmod.SessionLocal()

    def tearDown(self):
        self.sdb.close()
        self._reload()  # 还原生产 db/runner/pipeline 模块状态

    def _reload(self):
        import app.db as dbmod
        import app.crawler.runner as runner_mod
        import app.ai.pipeline as pipeline_mod
        importlib.reload(dbmod)
        importlib.reload(runner_mod)
        importlib.reload(pipeline_mod)
        self.dbmod = dbmod
        self.runner = runner_mod
        self.pipeline = pipeline_mod

    def _source(self, **kw):
        from app.models import Source
        s = Source(name="源-" + uuid4().hex, list_url="https://x.gov.cn/index.html", **kw)
        self.sdb.add(s)
        self.sdb.commit()
        return s


class ColdStartFloorTests(TwoTierBase):
    """新源冷启动最多追 COLD_START_MAX_AGE_DAYS 天，更旧的列表稿不入库。"""

    class FakeFetcher:
        def __init__(self, items, detail_text="正文" * 40):
            self.items = items
            self.detail_text = detail_text

        async def fetch_list(self, max_items=None, page=1):
            return self.items if page == 1 else []

        async def fetch_detail(self, url):
            return SimpleNamespace(content_text=self.detail_text,
                                   content_html="", publish_time=None)

    def _items(self):
        now = datetime.now()
        return [
            SimpleNamespace(url="https://x.gov.cn/new.html", title="新稿",
                            publish_time=now - timedelta(days=5)),
            SimpleNamespace(url="https://x.gov.cn/old.html", title="旧稿",
                            publish_time=now - timedelta(days=90)),
        ]

    def test_cold_start_skips_items_older_than_floor(self):
        from app.models import News
        s = self._source()  # 水位为空 → 冷启动
        fake = self.FakeFetcher(self._items())
        with patch.object(self.runner, "Fetcher", lambda source: fake):
            fl = asyncio.run(self.runner.fetch_source(s, self.sdb))
        self.assertEqual(fl.inserted, 1, "只应入库 60 天内的新稿")
        titles = [n.title for n in self.sdb.query(News).all()]
        self.assertIn("新稿", titles)
        self.assertNotIn("旧稿", titles, "90 天前的旧稿应被冷启动下限拦下")

    def test_watermarked_source_not_affected_by_floor(self):
        from app.models import News
        s = self._source()
        s.last_max_publish = datetime.now() - timedelta(days=1)
        self.sdb.commit()
        fake = self.FakeFetcher(self._items())
        with patch.object(self.runner, "Fetcher", lambda source: fake):
            asyncio.run(self.runner.fetch_source(s, self.sdb))
        titles = [n.title for n in self.sdb.query(News).all()]
        self.assertIn("旧稿", titles, "有水位的源不做冷启动截断")


class RoughInterpretTests(TwoTierBase):
    """粗略解读：批量打包、字段最小化、失败保持 fetched 可重试。"""

    def _news(self, title="旧闻", days_ago=100, status="fetched"):
        from app.models import News, Source
        # build_prompt 会访问 news.source.name，必须有源
        src = self.sdb.query(Source).first()
        if src is None:
            src = Source(name="测试源", list_url="https://x.gov.cn/index.html")
            self.sdb.add(src)
            self.sdb.commit()
        n = News(title=title, content_text="内容" * 100, content_html="",
                 url=f"https://x.gov.cn/{uuid4().hex}.html",
                 url_hash=uuid4().hex, title_hash=uuid4().hex,
                 simhash_hex="", source_id=src.id,
                 region_province="广东省", region_city="测试市",
                 level="district", status=status,
                 publish_time=datetime.now() - timedelta(days=days_ago))
        self.sdb.add(n)
        self.sdb.commit()
        return n

    def test_is_rough_routing(self):
        old = SimpleNamespace(publish_time=datetime(2026, 9, 15))
        new = SimpleNamespace(publish_time=datetime(2026, 10, 2))
        undated = SimpleNamespace(publish_time=None)
        self.assertTrue(self.pipeline.is_rough(old))
        self.assertFalse(self.pipeline.is_rough(new))
        self.assertFalse(self.pipeline.is_rough(undated), "无日期不误伤")

    def test_rough_batch_success(self):
        items = [self._news(f"旧闻{i}") for i in range(3)]
        payload = json.dumps({"items": [
            {"id": n.id, "summary": f"摘要{n.id}"} for n in items]})
        with patch.object(self.pipeline, "chat",
                          return_value=payload, create=True):
            ok, failed = self.pipeline.interpret_rough_batch(self.sdb, items)
        self.assertEqual((ok, failed), (3, 0))
        for n in items:
            self.sdb.refresh(n)
            self.assertEqual(n.status, "interpreted")
            self.assertEqual(n.ai_summary, f"摘要{n.id}")
            self.assertEqual(n.ai_key_points, [])
            self.assertEqual(n.ai_analysis, "")
            self.assertEqual(n.review_status, "auto", "粗略档不进人工复核")

    def test_rough_batch_missing_id_stays_fetched(self):
        items = [self._news(f"旧闻{i}") for i in range(2)]
        payload = json.dumps({"items": [{"id": items[0].id, "summary": "只有一篇"}]})
        with patch.object(self.pipeline, "chat",
                          return_value=payload, create=True):
            ok, failed = self.pipeline.interpret_rough_batch(self.sdb, items)
        self.assertEqual((ok, failed), (1, 1))
        self.sdb.refresh(items[1])
        self.assertEqual(items[1].status, "fetched", "漏掉的应留待下轮重试")
        self.assertEqual(items[1].ai_error or "", "", "不写终态失败标记")

    def test_rough_batch_bad_json_keeps_fetched(self):
        items = [self._news("旧闻")]
        with patch.object(self.pipeline, "chat",
                          return_value="这不是JSON", create=True):
            ok, failed = self.pipeline.interpret_rough_batch(self.sdb, items)
        self.assertEqual((ok, failed), (0, 1))
        self.sdb.refresh(items[0])
        self.assertEqual(items[0].status, "fetched")

    def test_rough_batch_quota_error_propagates(self):
        from app.ai.client import AIQuotaError
        items = [self._news("旧闻")]

        def boom(*a, **k):
            raise AIQuotaError("402")

        with patch.object(self.pipeline, "chat", side_effect=boom, create=True):
            with self.assertRaises(AIQuotaError):
                self.pipeline.interpret_rough_batch(self.sdb, items)
        self.sdb.refresh(items[0])
        self.assertEqual(items[0].status, "fetched", "额度中止不得写终态")

    def test_run_interpret_routes_two_tiers(self):
        old = self._news("旧闻", days_ago=100)
        new = self._news("新闻", days_ago=3)

        def fake_chat(messages, **kw):
            system = messages[0]["content"]
            user = messages[1]["content"]
            if "政务新闻编辑" in system:
                # 粗略档：从 prompt 里提取 [id]
                import re
                nid = int(re.search(r"\[(\d+)\]", user).group(1))
                return json.dumps({"items": [{"id": nid, "summary": "粗略摘要"}]})
            # 细致档：按标题判断是哪篇
            nid = old.id if old.title in user else new.id
            return json.dumps({"summary": "细致摘要", "key_points": ["要点"],
                               "analysis": "分析", "confidence": 0.9,
                               "tags": [], "content_type": "news"})

        with patch.object(self.pipeline, "chat", side_effect=fake_chat, create=True):
            res = self.pipeline.run_interpret(20)
        self.assertEqual(res["ok"], 2)
        self.sdb.refresh(old)
        self.sdb.refresh(new)
        self.assertEqual(old.ai_summary, "粗略摘要")
        self.assertEqual(old.ai_key_points, [], "旧闻不应生成要点")
        self.assertEqual(new.ai_summary, "细致摘要")
        self.assertEqual(new.ai_key_points, ["要点"], "新聞保持细致解读")


class TagDedupTests(TwoTierBase):
    """标签判重：同一新闻重复解读不得触发 news_tags 唯一约束崩溃。"""

    def _news(self):
        from app.models import News, Source
        src = Source(name="标签源-" + uuid4().hex, list_url="https://x.gov.cn/index.html")
        self.sdb.add(src)
        self.sdb.commit()
        n = News(title="标签测试", content_text="内容" * 50, content_html="",
                 url=f"https://x.gov.cn/{uuid4().hex}.html",
                 url_hash=uuid4().hex, title_hash=uuid4().hex,
                 simhash_hex="", source_id=src.id, level="district",
                 status="fetched", publish_time=datetime.now())
        self.sdb.add(n)
        self.sdb.commit()
        return n

    def _apply(self, news, tags):
        data = {"summary": "摘要", "key_points": [], "analysis": "",
                "confidence": 0.9, "tags": tags, "content_type": "news"}
        self.pipeline._apply_result(self.sdb, news, data)

    def test_duplicate_tag_names_no_unique_violation(self):
        news = self._news()
        # AI 返回重复标签名（同一标签出现两次），必须去重
        self._apply(news, ["民生", "民生", "交通"])
        self.sdb.commit()
        tag_count = self.sdb.execute(
            __import__("sqlalchemy").text(
                "select count(*) from news_tags where news_id=:n"), {"n": news.id}
        ).scalar()
        self.assertEqual(tag_count, 2, "重复标签名只应写入一条关联")

    def test_reapply_same_tags_idempotent(self):
        news = self._news()
        self._apply(news, ["民生", "交通"])
        self.sdb.commit()
        # 再次解读同一篇（同一会话），标签关联数不应增加
        self._apply(news, ["民生", "交通"])
        self.sdb.commit()
        tag_count = self.sdb.execute(
            __import__("sqlalchemy").text(
                "select count(*) from news_tags where news_id=:n"), {"n": news.id}
        ).scalar()
        self.assertEqual(tag_count, 2, "重复解读不得重复插入关联")


if __name__ == "__main__":
    unittest.main()
