"""测试环境隔离：绝不允许单测连到生产库 data/news.db。

推荐从 news-app 目录运行 `python -m unittest discover`（不带 -s tests），
此时本包会先于各测试模块导入：
1. 先导入 notifier（它会 load_dotenv(override=True) 把 .env 灌进环境变量）；
2. 再强制把 DATABASE_URL 指向临时库，之后所有 app.* 模块都绑定到临时库。

注意：带 `-s tests` 运行时 unittest 把 tests 当普通目录，本包不会被导入，
隔离会失效；app/db.py 里还有一层按进程命令行识别 unittest/pytest 的兜底。
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
