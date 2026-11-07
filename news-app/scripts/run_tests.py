"""一键运行单测：自动固定工作目录与隔离数据库，避免误连生产库。

用法：.venv/bin/python scripts/run_tests.py
"""
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import tests  # noqa: E402,F401  触发 tests/__init__.py 的环境隔离

suite = unittest.defaultTestLoader.discover(
    start_dir=str(ROOT / "tests"), top_level_dir=str(ROOT), pattern="test_*.py"
)
result = unittest.TextTestRunner(verbosity=2).run(suite)
sys.exit(0 if result.wasSuccessful() else 1)
