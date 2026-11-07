"""测试环境隔离：绝不允许单测连到生产库 data/news.db。

unittest discover 会先导入本包，再导入各测试模块，因此在这里统一完成：
1. 先导入 notifier（它会 load_dotenv(override=True) 把 .env 灌进环境变量）；
2. 再强制把 DATABASE_URL 指向临时库，之后所有 app.* 模块都绑定到临时库。
"""
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import notifier  # noqa: E402,F401  先让 .env 覆盖生效

TEST_DB = Path(tempfile.mkdtemp(prefix="news_unittest_")) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB}"
