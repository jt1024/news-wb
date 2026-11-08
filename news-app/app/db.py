"""SQLAlchemy 引擎与会话。"""
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from . import config

if DATABASE_URL := config.DATABASE_URL:
    # 保险：unittest / pytest 进程若仍指向生产库，强制切到一次性临时库。
    # `python -m unittest discover -s tests` 不会导入 tests/__init__.py，
    # 只靠包内隔离会漏；测试里的 delete() 会直接清空生产 news/sources 表。
    _is_test = (any(k in " ".join(sys.argv[:2]) for k in ("unittest", "pytest"))
                or "PYTEST_CURRENT_TEST" in os.environ)
    if _is_test and "news.db" in DATABASE_URL and "test.db" not in DATABASE_URL:
        _tmp_db = Path(tempfile.mkdtemp(prefix="news_unittest_")) / "test.db"
        DATABASE_URL = f"sqlite:///{_tmp_db}"
    kwargs = {}
    if DATABASE_URL.startswith("sqlite"):
        import pathlib

        db_path = DATABASE_URL.replace("sqlite:///", "")
        pathlib.Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(DATABASE_URL, **kwargs)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
