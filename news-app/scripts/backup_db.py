"""手动执行一次数据库热备：.venv/bin/python scripts/backup_db.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.backup import run_backup  # noqa: E402

if __name__ == "__main__":
    print(json.dumps(run_backup(), ensure_ascii=False, indent=2))
