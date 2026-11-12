"""抓取编排：列表 → 详情 → 三层去重 → 入库。"""
import asyncio
import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import config
from ..db import SessionLocal
from ..dedup import hamming_distance_hex, simhash64, title_hash, title_similarity, url_hash
from ..models import FetchLog, News, SkippedURL, Source
from .base import Fetcher

log = logging.getLogger("crawler")

# 无正文/失效链接的抑制时长。到期自动解除，避免站点后来补正文却永远抓不到。
SKIP_TTL_DAYS = 30


def is_suppressed(db: Session, u_h: str) -> bool:
    """命中抑制表且未过期则跳过；过期记录顺手清理。"""
    row = db.get(SkippedURL, u_h)
    if row is None:
        return False
    if row.expires_at and row.expires_at < datetime.now():
        db.delete(row)
        db.commit()
        return False
    row.hit_count = (row.hit_count or 0) + 1
    db.commit()
    return True


def suppress(db: Session, u_h: str, url: str, reason: str):
    """登记一条已知豁免（重复命中时续期）。"""
    expires = datetime.now() + timedelta(days=SKIP_TTL_DAYS)
    row = db.get(SkippedURL, u_h)
    if row is None:
        db.add(SkippedURL(url_hash=u_h, url=url, reason=reason, expires_at=expires))
    else:
        row.url, row.reason = url, reason
        row.expires_at = expires
        row.hit_count = (row.hit_count or 0) + 1
    db.commit()


def _is_permanent_failure(exc: Exception) -> bool:
    """只有明确「页面不存在」才抑制；网络抖动/超时不抑制，下轮照常重试。"""
    msg = str(exc)
    return "HTTP 404" in msg or "HTTP 410" in msg


def seed_sources(db: Session):
    """把 sources.py 的种子源写入数据库（按 name 幂等）。"""
    from .sources import SEED_SOURCES

    existing = {s.name for s in db.execute(select(Source)).scalars()}
    added = 0
    for cfg in SEED_SOURCES:
        if cfg["name"] in existing:
            continue
        db.add(Source(**cfg))
        added += 1
    if added:
        db.commit()
    return added


def is_duplicate(db: Session, source: Source, url_h: str, t_hash: str, title: str, s_hash: str) -> bool:
    # 层 1：URL 精确匹配
    if db.execute(select(News.id).where(News.url_hash == url_h).limit(1)).scalar():
        return True
    # 层 2：标题精确指纹（限定同层级同地域，避免不同城市/不同区同名标题误判）/ 同源相似度（近 60 天）
    # 广州 11 个区同属「广州市」，必须再按区收窄，否则跨区同名通稿会被当成重复丢掉。
    # 国家级源的 city/district 都为空，加 level 条件是为了：
    #   1) 与同样 city 为空的广东省级源区分开；
    #   2) 各国家部委共享同一命名空间——「李强主持召开国务院常务会议」这类
    #      中央通稿会被十几个部委站同时转载，只保留最先抓到的那条即可。
    district = getattr(source, "region_district", "") or ""
    # 港澳台地区源的 city/district 都为空，必须再按 region_area 收窄，
    # 否则三个地区会共享同一命名空间，跨地区同名通稿会被误判成重复。
    area = getattr(source, "region_area", "") or ""
    if db.execute(
        select(News.id).where(
            News.title_hash == t_hash,
            News.level == source.level,
            News.region_city == source.region_city,
            News.region_district == district,
            News.region_area == area,
        ).limit(1)
    ).scalar():
        return True
    since = datetime.now() - timedelta(days=60)
    rows = db.execute(
        select(News.title, News.simhash_hex).where(
            News.source_id == source.id, News.publish_time >= since
        )
    ).all()
    for old_title, old_sim in rows:
        if title_similarity(title, old_title) >= config.TITLE_SIMILARITY_THRESHOLD:
            return True
        # 层 3：正文 SimHash（有历史指纹才比对）
        if s_hash and old_sim and hamming_distance_hex(s_hash, old_sim) <= config.SIMHASH_DISTANCE_THRESHOLD:
            return True
    return False


async def fetch_source(source: Source, db: Session, max_items: int = 50) -> FetchLog:
    """抓取单个源：返回 FetchLog。"""
    fetch_log = FetchLog(source_id=source.id, started_at=datetime.now())
    db.add(fetch_log)
    db.commit()
    try:
        fetcher = Fetcher(source)
        items = await fetcher.fetch_list(max_items=max_items)
        fetch_log.found = len(items)
        inserted = duplicated = suppressed = detail_failed = empty_skipped = 0
        for item in items:
            # URL 层判重提前：已入库的文章不再打开详情页。
            # 列表页大部分文章是历史已抓的（如 21:00 轮 576 篇中 447 篇重复），
            # 提前跳过可省掉大半详情页下载，显著缩短每轮耗时。
            u_h = url_hash(item.url)
            if db.execute(select(News.id).where(News.url_hash == u_h).limit(1)).scalar():
                duplicated += 1
                continue
            # 已知无正文/失效链接：静默跳过，避免每轮重复下载又重复报一条异常
            if is_suppressed(db, u_h):
                suppressed += 1
                continue
            # 单篇详情页失败不能拖垮整个源：跳过该篇并继续处理其余条目
            try:
                detail = await fetcher.fetch_detail(item.url)
                text = detail.content_text
            except Exception as e:  # noqa: BLE001
                detail_failed += 1
                log.warning("detail skipped %s (%s)", item.url, str(e)[:120])
                if _is_permanent_failure(e):
                    suppress(db, u_h, item.url, "not_found")
                continue
            # 兜底：正文为空/极短的（栏目页、图片页、JS 渲染页）不入库，
            # 否则会生成「正文缺失」的无意义 AI 解读并污染复核队列
            if len((text or "").strip()) < 30:
                empty_skipped += 1
                log.warning("empty content skipped %s (%s)", item.url, item.title[:30])
                suppress(db, u_h, item.url, "empty")
                continue
            s_hash = simhash64(text) if len(text) > 200 else ""
            t_h = title_hash(item.title)
            # 剩余两层：标题指纹（同地域）/ 标题相似度 + 正文 SimHash（同源 60 天）
            if is_duplicate(db, source, u_h, t_h, item.title, s_hash):
                duplicated += 1
                continue
            news = News(
                title=item.title,
                content_text=text,
                content_html=detail.content_html,
                url=item.url,
                url_hash=u_h,
                title_hash=t_h,
                simhash_hex=s_hash,
                source_id=source.id,
                region_province=source.region_province,
                region_city=source.region_city,
                region_district=getattr(source, "region_district", "") or "",
                region_org=getattr(source, "region_org", "") or "",
                region_area=getattr(source, "region_area", "") or "",
                level=source.level,
                # 港澳台地区稿件默认不做 AI 解读：避免模型对敏感表述拒答后堆积
                # failed 终态，也避免混入广东省主题统计；原文与列表照常可用。
                status="skipped" if (source.selector_config or {}).get("skip_ai") else "fetched",
                # 部委列表页常不显示日期：URL 日期已在解析层兜底，这里再用详情页 meta 补一次
                publish_time=item.publish_time or getattr(detail, "publish_time", None),
            )
            db.add(news)
            inserted += 1
            db.commit()
        fetch_log.status = "ok"
        fetch_log.inserted = inserted
        fetch_log.duplicated = duplicated
        notes = []
        if detail_failed:
            notes.append(f"{detail_failed}/{len(items)} 篇详情抓取失败已跳过")
        if empty_skipped:
            notes.append(f"{empty_skipped} 篇无正文已抑制（{SKIP_TTL_DAYS} 天内不重试）")
        if suppressed:
            # 已知豁免是正常状态，不写进 error 备注污染报告，只在运行日志留痕
            log.info("source %s: %d known-exempt urls skipped", source.name, suppressed)
        if notes:
            # 记在 error 字段供后台查看，但状态仍为 ok（源本身可用）
            fetch_log.error = "；".join(notes)
    except Exception as e:  # noqa: BLE001
        fetch_log.status = "error"
        fetch_log.error = str(e)[:2000]
        log.exception("source %s failed: %s", source.name, e)
    fetch_log.finished_at = datetime.now()
    source.last_fetch_at = fetch_log.finished_at
    db.commit()
    return fetch_log


async def run_fetch(source_id: int | None = None, max_items: int = 50, progress_cb=None) -> dict:
    """抓取全部启用源（或指定源）。"""
    db = SessionLocal()
    try:
        q = select(Source).where(Source.enabled == True)  # noqa: E712
        if source_id:
            q = q.where(Source.id == source_id)
        sources = db.execute(q).scalars().all()
        results = []
        for i, source in enumerate(sources):
            if progress_cb:
                progress_cb({"phase": "抓取中", "done": i, "total": len(sources),
                             "current": source.name})
            # 逐源串行，源内详情限速，礼貌抓取
            fl = await fetch_source(source, db, max_items=max_items)
            results.append({
                "source": source.name,
                "status": fl.status,
                "found": fl.found,
                "inserted": fl.inserted,
                "duplicated": fl.duplicated,
                "error": fl.error,
            })
        return {"sources": len(results), "results": results}
    finally:
        db.close()
