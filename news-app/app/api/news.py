"""新闻浏览 API：列表/详情/字典。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from ..auth import require_auth
from ..db import get_db
from ..models import News, Source, Tag

router = APIRouter(dependencies=[Depends(require_auth)])


def _brief(n: News) -> dict:
    return {
        "id": n.id,
        "title": n.title,
        "summary": n.ai_summary or (n.content_text[:120] if n.content_text else ""),
        "city": n.region_city,
        "district": n.region_district or "",
        "source": n.source.name if n.source else "",
        "content_type": n.content_type,
        "tags": [t.name for t in n.tags],
        "publish_time": n.publish_time.isoformat() if n.publish_time else None,
        "url": n.url,
        "status": n.status,
        "confidence": n.ai_confidence,
    }


@router.get("/api/news")
def list_news(
    city: str = "",
    district: str = "",
    type_: str = Query("", alias="type"),
    tag: str = "",
    q: str = "",
    start: str = "",
    end: str = "",
    page: int = 1,
    size: int = 20,
    db: Session = Depends(get_db),
):
    stmt = select(News).options(joinedload(News.source), joinedload(News.tags))
    if city:
        stmt = stmt.where(News.region_city == city)
    if district:
        stmt = stmt.where(News.region_district == district)
    if type_:
        stmt = stmt.where(News.content_type == type_)
    if tag:
        stmt = stmt.where(News.tags.any(Tag.name == tag))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(News.title.like(like), News.content_text.like(like), News.ai_summary.like(like)))
    if start:
        stmt = stmt.where(News.publish_time >= datetime.fromisoformat(start))
    if end:
        stmt = stmt.where(News.publish_time <= datetime.fromisoformat(end + "T23:59:59") if len(end) == 10 else datetime.fromisoformat(end))
    stmt = stmt.order_by(News.publish_time.desc().nullslast(), News.id.desc())

    total_n = len(db.execute(stmt.with_only_columns(News.id).order_by(None)).scalars().all())
    rows = db.execute(stmt.offset((page - 1) * size).limit(size)).scalars().unique().all()
    return {"total": total_n, "page": page, "size": size, "items": [_brief(n) for n in rows]}


@router.get("/api/news/{news_id}")
def news_detail(news_id: int, db: Session = Depends(get_db)):
    n = db.get(News, news_id)
    if not n:
        raise HTTPException(404, "not found")
    d = _brief(n)
    d.update({
        "content_text": n.content_text,
        "ai_key_points": n.ai_key_points,
        "ai_analysis": n.ai_analysis,
        "ai_model": n.ai_model,
        "review_status": n.review_status,
        "version": n.version,
        "fetch_time": n.fetch_time.isoformat(),
    })
    return d


@router.post("/api/news/{news_id}/interpret")
async def interpret_single(news_id: int, db: Session = Depends(get_db)):
    """手动触发单篇 AI 解读（前台详情页按钮）。"""
    import asyncio

    from .. import config
    from ..ai.pipeline import interpret_one

    if not config.ai_enabled():
        raise HTTPException(400, "AI 未配置：请在 .env 设置 AI_PROVIDER 与 AI_API_KEY")
    n = db.get(News, news_id)
    if not n:
        raise HTTPException(404, "not found")
    ok = await asyncio.to_thread(interpret_one, db, n)
    db.commit()
    return {"ok": ok, "error": n.ai_error if not ok else ""}


@router.get("/api/meta")
def meta(db: Session = Depends(get_db)):
    cities = [r[0] for r in db.execute(select(News.region_city).distinct()).all() if r[0]]
    # 从源配置取而非新闻表：新接入的区还没抓到文章时，筛选下拉也要有选项
    districts = [r[0] for r in db.execute(select(Source.region_district).distinct()).all() if r[0]]
    tags = [t.name for t in db.execute(select(Tag)).scalars()]
    sources = [{"id": s.id, "name": s.name, "city": s.region_city,
                "district": s.region_district or "", "level": s.level, "enabled": s.enabled}
               for s in db.execute(select(Source)).scalars()]
    return {"cities": sorted(cities), "districts": sorted(districts),
            "tags": tags, "sources": sources,
            "types": [
                {"key": "news", "label": "新闻动态"},
                {"key": "notice", "label": "通知公告"},
                {"key": "policy", "label": "政策文件"},
                {"key": "interpretation", "label": "政策解读"},
                {"key": "procurement", "label": "招采公示"},
            ]}
