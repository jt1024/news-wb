"""管理后台 API：手动触发、源管理、复核队列、状态日志、执行报告。"""
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from ..auth import require_auth
from .. import config
from ..crawler.runner import run_fetch, seed_sources
from ..db import get_db, SessionLocal
from ..models import FetchLog, News, Source
from ..scheduler import trigger_fetch, trigger_interpret, trigger_report, _task_state

router = APIRouter(prefix="/api/admin", dependencies=[Depends(require_auth)])

REPORTS_DIR = Path(__file__).resolve().parents[2] / "data" / "reports"


def _read_only_guard():
    """线上发布的是只读快照：抓取、推送、改源、复核都留给本地 Mac mini。"""
    if config.PUBLISH_MODE:
        raise HTTPException(status_code=403, detail="线上为只读快照，请在本地服务执行此操作")


@router.get("/reports")
def admin_reports():
    """历史执行报告列表（最新在前）。"""
    items = []
    if REPORTS_DIR.is_dir():
        for p in sorted(REPORTS_DIR.glob("*.html"), reverse=True):
            st = p.stat()
            items.append({
                "name": p.stem,
                "url": "/reports/" + p.name,
                "size": st.st_size,
                "time": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
            })
    return {"reports": items}


@router.post("/generate-report")
async def admin_generate_report():
    """立即生成最近一轮报告并按配置推送（异步）。"""
    _read_only_guard()
    task_id = trigger_report()
    return {"task_id": task_id, "message": "报告生成与推送已启动"}


@router.post("/trigger-fetch")
async def admin_trigger_fetch(max_items: int = 50):
    """异步触发抓取，立即返回任务 ID。"""
    _read_only_guard()
    task_id = trigger_fetch(max_items)
    return {"task_id": task_id, "message": "抓取已启动"}


@router.post("/trigger-interpret")
async def admin_trigger_interpret(batch_size: int = 20):
    _read_only_guard()
    task_id = trigger_interpret(batch_size)
    return {"task_id": task_id, "message": "解读已启动"}


@router.get("/status")
def admin_status():
    """任务状态 + 最近抓取日志。"""
    db = SessionLocal()
    try:
        logs = db.execute(select(FetchLog).order_by(FetchLog.id.desc()).limit(20)).scalars().all()
        counts = {}
        for status in ("fetched", "interpreted", "skipped", "failed"):
            counts[status] = db.execute(
                select(News.id).where(News.status == status).order_by(None)
            ).scalars().all().__len__()
        pending_review = db.execute(
            select(News.id).where(News.review_status == "pending").order_by(None)
        ).scalars().all().__len__()
        return {
            "tasks": _task_state(),
            "counts": counts,
            "pending_review": pending_review,
            "recent_logs": [
                {
                    "source_id": l.source_id,
                    "started_at": l.started_at.isoformat(),
                    "finished_at": l.finished_at.isoformat() if l.finished_at else None,
                    "status": l.status,
                    "found": l.found,
                    "inserted": l.inserted,
                    "duplicated": l.duplicated,
                    "error": l.error[:200],
                } for l in logs
            ],
        }
    finally:
        db.close()


# ---- 源站点管理 ----

@router.get("/scheduler")
def scheduler_status():
    """定时任务自检：调度器是否运行、挂了哪些 job、下次触发时间。"""
    from ..scheduler import scheduler

    return {
        "running": scheduler.running,
        "state": str(scheduler.state),
        "timezone": str(scheduler.timezone),
        "jobs": [
            {
                "id": j.id,
                "trigger": str(j.trigger),
                "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
                "misfire_grace_time": j.misfire_grace_time,
                "coalesce": j.coalesce,
            }
            for j in scheduler.get_jobs()
        ],
    }


@router.get("/sources")
def list_sources(db=Depends(get_db)):
    sources = db.execute(select(Source)).scalars().all()
    return [{"id": s.id, "name": s.name, "city": s.region_city,
             "district": s.region_district or "", "org": s.region_org or "", "level": s.level,
             "list_url": s.list_url, "fetch_type": s.fetch_type, "enabled": s.enabled,
             "last_fetch_at": s.last_fetch_at.isoformat() if s.last_fetch_at else None}
            for s in sources]


@router.post("/sources")
def create_source(body: dict, db=Depends(get_db)):
    _read_only_guard()
    required = ("name", "list_url")
    for k in required:
        if not body.get(k):
            raise HTTPException(400, f"缺少字段 {k}")
    s = Source(
        name=body["name"],
        region_city=body.get("city", ""),
        region_district=body.get("district", "") or "",
        region_province="全国" if body.get("level") == "national" else "广东省",
        region_org=body.get("org", "") or "",
        level=body.get("level", "city"),
        base_url=body.get("base_url", ""),
        list_url=body["list_url"],
        fetch_type=body.get("fetch_type", "html"),
        selector_config=body.get("selector_config", {}),
        enabled=True,
    )
    db.add(s)
    db.commit()
    return {"id": s.id}


@router.put("/sources/{source_id}")
def update_source(source_id: int, body: dict, db=Depends(get_db)):
    _read_only_guard()
    s = db.get(Source, source_id)
    if not s:
        raise HTTPException(404)
    if "enabled" in body:
        s.enabled = bool(body["enabled"])
    if "name" in body:
        s.name = body["name"]
    if "list_url" in body:
        s.list_url = body["list_url"]
    db.commit()
    return {"ok": True}


@router.delete("/sources/{source_id}")
def delete_source(source_id: int, db=Depends(get_db)):
    _read_only_guard()
    s = db.get(Source, source_id)
    if not s:
        raise HTTPException(404)
    s.enabled = False  # 软删除：停用而非物理删除
    db.commit()
    return {"ok": True}


# ---- 复核队列 ----

@router.get("/review-queue")
def review_queue(db=Depends(get_db)):
    rows = db.execute(
        select(News).where(News.review_status == "pending").order_by(News.id).limit(50)
    ).scalars().all()
    return [{"id": n.id, "title": n.title, "summary": n.ai_summary,
             "analysis": n.ai_analysis, "confidence": n.ai_confidence,
             "city": n.region_city, "district": n.region_district or ""} for n in rows]


@router.post("/review/{news_id}")
def review_news(news_id: int, body: dict, db=Depends(get_db)):
    _read_only_guard()
    n = db.get(News, news_id)
    if not n:
        raise HTTPException(404)
    n.review_status = "reviewed"
    if body.get("summary") is not None:
        n.ai_summary = body["summary"]
    if body.get("analysis") is not None:
        n.ai_analysis = body["analysis"]
    db.commit()
    return {"ok": True}


@router.delete("/review/{news_id}")
def reject_news(news_id: int, db=Depends(get_db)):
    """复核不通过：重置为待解读。"""
    _read_only_guard()
    n = db.get(News, news_id)
    if not n:
        raise HTTPException(404)
    n.review_status = "auto"
    n.status = "fetched"
    n.ai_summary = ""
    n.ai_key_points = []
    n.ai_analysis = ""
    db.commit()
    return {"ok": True}
