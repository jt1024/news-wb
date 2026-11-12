"""构建 WorkBuddy「发布为应用」专用目录。

平台会按目录原样压缩上传，因此这里单独生成一个**只读快照**，与主项目隔离：

  * 不带 .env 里的飞书 Webhook / AI Key / 本地口令；
  * 不带 .venv / tests / scripts / 日志 / 备份（体积与密钥风险）；
  * 带上 web/ 前端、app/ 后端、锁版本的 requirements.txt 和一份 SQLite 快照；
  * 自带 serve.py 读取 $PORT 并绑定 0.0.0.0（平台要求）；
  * PUBLISH_MODE=1：不挂定时任务、不抓取、不推送，后台写操作返回 403。

用法：.venv/bin/python scripts/build_publish.py
"""
from __future__ import annotations

import secrets
import shutil
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # news-app
OUT = ROOT.parent / "publish-app"                     # /Users/jt/Desktop/CC/news/publish-app
SKIP_DIRS = {"__pycache__", ".pytest_cache", "runtime"}


def _copy_python_tree(src: Path, dst: Path) -> None:
    for path in src.rglob("*.py"):
        if SKIP_DIRS & set(path.relative_to(src).parts):
            continue
        rel = path.relative_to(src)
        target = dst / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    # 包目录必须有 __init__.py
    for d in (dst, dst / "api", dst / "crawler"):
        init = d / "__init__.py"
        if not init.exists():
            init.write_text("", encoding="utf-8")


def _snapshot_db(src: Path, dst: Path) -> None:
    """用 SQLite backup() 拿一致性快照，WAL 模式下不能直接 copy 文件。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    if not src.exists():
        return
    with sqlite3.connect(f"file:{src}?mode=ro", uri=True) as s, sqlite3.connect(dst) as d:
        s.backup(d)


def _load_publish_env() -> dict[str, str]:
    """在清空目录**之前**读出线上配置，用于保留登录口令与 token 签名密钥。"""
    env_file = OUT / ".env"
    result: dict[str, str] = {}
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                result[key.strip()] = value.strip()
    return result


def _credentials_for_publish(prev: dict[str, str]) -> tuple[str, str]:
    """复用已有口令/密钥；缺失或过弱时才重新生成。

    每日自动同步会反复重建本目录，若每次都换新口令，用户会被锁在线上应用外，
    且旧 token 因签名密钥变化全部失效。
    """
    pwd = prev.get("ADMIN_PASSWORD", "")
    if len(pwd) < 16:
        pwd = secrets.token_urlsafe(24)
        reused = False
    else:
        reused = True
    secret = prev.get("AUTH_SECRET") or secrets.token_urlsafe(40)
    print(f"线上凭证: {'沿用已有口令' if reused else '生成新口令'}; "
          f"签名密钥: {'沿用' if prev.get('AUTH_SECRET') else '新生成'}")
    return pwd, secret


def main() -> None:
    prev = _load_publish_env()
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    (OUT / "data" / "reports").mkdir(parents=True, exist_ok=True)

    _copy_python_tree(ROOT / "app", OUT / "app")
    shutil.copytree(ROOT / "web", OUT / "web",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "requirements.txt", OUT / "requirements.txt")

    _snapshot_db(ROOT / "data" / "news.db", OUT / "data" / "news.db")
    reports = sorted((ROOT / "data" / "reports").glob("*.html"),
                     key=lambda p: p.stat().st_mtime, reverse=True)[:3]
    for p in reports:
        shutil.copy2(p, OUT / "data" / "reports" / p.name)
    if reports:
        shutil.copy2(reports[0], OUT / "data" / "reports" / "latest.html")

    (OUT / "serve.py").write_text('''"""平台入口：监听 $PORT 并绑定 0.0.0.0（发布沙箱的硬性要求）。"""
import os

import uvicorn

from app.main import app

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8300")), workers=1)
''', encoding="utf-8")

    pwd, secret = _credentials_for_publish(prev)
    (OUT / ".env").write_text(f'''# 线上只读快照专用配置：不含任何 AI Key / 飞书 Webhook / 本地口令
ADMIN_PASSWORD={pwd}
AUTH_SECRET={secret}
AUTH_TOKEN_EXPIRE_HOURS=72
LOGIN_MAX_FAILURES=5
LOGIN_LOCK_SECONDS=300
PUBLISH_MODE=1
NOTIFY_CHANNEL=off
TZ=Asia/Shanghai
''', encoding="utf-8")
    (OUT / ".env").chmod(0o600)

    (OUT / "README.md").write_text('''# 政务新闻聚合平台 · 线上只读快照

由 `news-app/scripts/build_publish.py` 生成，供 WorkBuddy「发布为应用」使用。

- 数据与配置来自本地 Mac mini 的一次性快照；抓取、AI 解读、报告推送仍只在本机跑。
- `PUBLISH_MODE=1`：不挂定时任务、后台写操作返回 403。
- 登录口令见同目录 `.env`（该文件不会提交到 Git）。
- 启动：`python serve.py`，监听 `$PORT`、绑定 `0.0.0.0`。
''', encoding="utf-8")

    size = sum(p.stat().st_size for p in OUT.rglob("*") if p.is_file())
    print(f"发布目录: {OUT}")
    print(f"文件数: {sum(1 for p in OUT.rglob('*') if p.is_file())}, 体积: {size / 1024 / 1024:.1f} MB")
    print(f"口令长度: {len(pwd)}（明文见 {OUT / '.env'}，请勿提交到 Git）")
    print("敏感文件自检:", [p.name for p in OUT.rglob("*")
                       if p.is_file() and (p.name.startswith(".env") or p.suffix == ".db")])


if __name__ == "__main__":
    main()
