"""SQLite 在线热备。

每轮定时任务结束后生成当天快照（同一天覆盖为最新），原子替换避免半截文件；
按 BACKUP_KEEP_DAYS 保留历史；可选配置 BACKUP_MIRROR_DIR 再镜像一份到外部目录。

必须用 sqlite3.Connection.backup() 而不是复制文件：WAL 模式下直接 copy
会漏掉未 checkpoint 的数据，backup() 由 SQLite 自己保证一致性快照。
"""
import logging
import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from . import config

log = logging.getLogger("backup")

BASE_DIR = Path(__file__).resolve().parent.parent
BACKUP_DIR = BASE_DIR / "data" / "backups"


def _db_path() -> Path:
    url = config.DATABASE_URL
    if not url.startswith("sqlite"):
        raise RuntimeError("仅支持 SQLite 热备；换 PostgreSQL 后请改用 pg_dump")
    raw = url.replace("sqlite:///", "")
    p = Path(raw)
    return p if p.is_absolute() else BASE_DIR / p


def _open_ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _mirror(path: Path) -> str:
    """可选：把已校验的快照再复制一份到外部目录（iCloud / 移动硬盘等）。

    目录不存在或未配置时静默跳过——绝不让异地备份失败影响主流程。
    """
    raw = os.getenv("BACKUP_MIRROR_DIR", "").strip()
    if not raw:
        return ""
    dest_dir = Path(raw).expanduser()
    if not dest_dir.is_dir():
        log.warning("backup mirror dir not found, skipped: %s", dest_dir)
        return ""
    dst = dest_dir / path.name
    tmp = dest_dir / ("." + path.name + ".tmp")
    shutil.copy2(path, tmp)
    os.replace(tmp, dst)
    return str(dst)


def run_backup() -> dict:
    """执行一次热备，返回可供日志/接口展示的结果字典。"""
    src = _db_path()
    if not src.exists():
        raise FileNotFoundError(f"源数据库不存在：{src}")

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    final = BACKUP_DIR / f"news-{day}.db"
    tmp = BACKUP_DIR / f".news-{day}.db.tmp"
    if tmp.exists():
        tmp.unlink()

    source = _open_ro(src)
    target = sqlite3.connect(tmp)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()

    # 校验快照确实可读且含数据，校验通过才原子替换正式文件
    check = _open_ro(tmp)
    try:
        rows = check.execute("SELECT COUNT(*) FROM news").fetchone()[0]
        tables = check.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]
    finally:
        check.close()
    if rows == 0 or tables == 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"备份校验失败：rows={rows}, tables={tables}")
    os.replace(tmp, final)

    # 清理过期快照
    keep_days = max(1, int(os.getenv("BACKUP_KEEP_DAYS", "14")))
    cutoff = datetime.now() - timedelta(days=keep_days)
    removed = []
    for f in BACKUP_DIR.glob("news-*.db"):
        try:
            stamp = datetime.strptime(f.stem.replace("news-", ""), "%Y%m%d")
        except ValueError:
            continue
        if stamp < cutoff:
            f.unlink()
            removed.append(f.name)

    return {
        "file": str(final),
        "bytes": final.stat().st_size,
        "rows": rows,
        "tables": tables,
        "removed": removed,
        "mirror": _mirror(final),
    }
