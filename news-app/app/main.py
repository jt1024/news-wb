"""FastAPI 入口：API 路由 + 静态前端 + 启动初始化。"""
import logging
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .api import admin, news, trends
from .auth import router as auth_router
from .db import Base, SessionLocal, engine
from .crawler.runner import seed_sources

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

app = FastAPI(title="政务新闻聚合平台", version="0.1.0")
app.include_router(auth_router)
app.include_router(news.router)
app.include_router(trends.router)
app.include_router(admin.router)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
REPORTS_DIR = Path(__file__).resolve().parent.parent / "data" / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
# 报告静态目录必须挂在通配路由 /{path:path} 之前，否则会被吞掉
app.mount("/reports", StaticFiles(directory=REPORTS_DIR), name="reports")


@app.on_event("startup")
async def startup():
    """必须是 async：AsyncIOScheduler 要在正在运行的 event loop 里启动。
    写成同步 def 时 FastAPI 会放到线程池执行，start() 会抛
    RuntimeError: no running event loop，导致定时任务静默不挂载。
    """
    Base.metadata.create_all(engine)
    _migrate(engine)
    _check_auth_security()
    db = SessionLocal()
    try:
        added = seed_sources(db)
        if added:
            logging.getLogger("app").info("seeded %d sources", added)
    finally:
        db.close()
    from .scheduler import start_scheduler

    start_scheduler()


def _check_auth_security():
    """启动自检：把容易被忽略的认证风险写进日志（不阻断服务）。"""
    log = logging.getLogger("security")
    if not config.AUTH_SECRET:
        log.warning("AUTH_SECRET 未配置：登录口令正兼任 token 签名密钥，建议生成独立随机串")
    pwd = config.ADMIN_PASSWORD
    if pwd in ("", "changeme") or (pwd.isdigit() and len(pwd) < 8):
        log.warning("ADMIN_PASSWORD 强度偏弱；当前仅监听 127.0.0.1，若上公网必须先更换")


def _migrate(engine):
    """轻量迁移：为旧表补充新增列。"""
    from sqlalchemy import text

    with engine.connect() as conn:
        cols = [r[1] for r in conn.execute(text("PRAGMA table_info(news)"))]
        if "ai_error" not in cols:
            conn.execute(text("ALTER TABLE news ADD COLUMN ai_error TEXT DEFAULT ''"))
            conn.commit()


@app.get("/")
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/admin")
def admin_page():
    return FileResponse(WEB_DIR / "admin.html")


@app.get("/{path:path}")
def web_files(path: str):
    """根路径托管前端静态文件（web/ 目录）。"""
    file = (WEB_DIR / path).resolve()
    if file.is_file() and str(file).startswith(str(WEB_DIR)):
        return FileResponse(file)
    raise HTTPException(status_code=404, detail="Not Found")


@app.exception_handler(401)
def unauthorized(request, exc):
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=401, content={"detail": "未登录"})
    return FileResponse(WEB_DIR / "login.html")
