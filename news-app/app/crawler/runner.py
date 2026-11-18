"""抓取编排：列表 → 详情 → 三层去重 → 入库。

2026-11-18 起支持水位增量抓取与按日期/地域补抓：
- 增量：每个源记住 last_max_publish，翻页扫描，连续 N 条早于「水位−重叠天数」即停；
  只在整轮成功后推进水位，失败原地不动，下轮重扫同一区间，保证不漏。
- 补抓：指定日期区间 + 地域筛选源，深翻历史列表页；不影响水位。
- 安全：域名级节流（base/politeness）、源级熔断、全局请求预算。
"""
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
from .pagination import is_same_first_url

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
        row.url = url
        row.reason = reason
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
    # 层 2：标题精确指纹（限定同层级同地域，避免不同城市/不同区同名标题误判）
    district = getattr(source, "region_district", "") or ""
    area = getattr(source, "region_area", "") or ""
    if db.execute(
        select(News.id).where(
            News.title_hash == t_hash,
            News.level == source.level,
            News.region_province == source.region_province,
            News.region_city == source.region_city,
            News.region_district == district,
            News.region_area == area,
        ).limit(1)
    ).scalar():
        return True
    # 层 3：同源相似度/SimHash，只比对近 60 天（更早的稿件不会与本轮新稿重复）
    since = datetime.now() - timedelta(days=60)
    rows = db.execute(
        select(News.title, News.simhash_hex).where(
            News.source_id == source.id, News.publish_time >= since
        )
    ).all()
    for old_title, old_sim in rows:
        if title_similarity(title, old_title) >= config.TITLE_SIMILARITY_THRESHOLD:
            return True
        if s_hash and old_sim and hamming_distance_hex(s_hash, old_sim) <= config.SIMHASH_DISTANCE_THRESHOLD:
            return True
    return False


def _threshold_for(source: Source) -> datetime | None:
    """增量抓取的早停阈值：水位回退重叠天数。

    水位为空（首次抓取/新源）返回 None —— 不早停，翻满页数上限，尽量多补历史。
    """
    base = getattr(source, "last_max_publish", None)
    if base is None:
        return None
    return base - timedelta(days=config.WATERMARK_OVERLAP_DAYS)


def _region_matches(source: Source, region: dict) -> bool:
    """补抓的地域筛选：按源自身归属过滤，空值表示不限。"""
    checks = (
        ("province", source.region_province),
        ("city", source.region_city),
        ("district", getattr(source, "region_district", "") or ""),
        ("area", getattr(source, "region_area", "") or ""),
        ("org", getattr(source, "region_org", "") or ""),
        ("level", source.level),
    )
    for key, value in checks:
        wanted = (region.get(key) or "").strip()
        if wanted and value != wanted:
            return False
    return True


async def fetch_source(
    source: Source,
    db: Session,
    max_items: int | None = None,
    page_max: int | None = None,
    backfill: dict | None = None,
) -> FetchLog:
    """抓取单个源：翻页列表 → 详情 → 三层去重 → 入库。返回 FetchLog。

    backfill=None 为日常增量；传入 dict 时为补抓模式，支持 date_from/date_to。
    """
    max_items = max_items or config.PAGE_SIZE
    page_max = page_max or config.PAGE_MAX
    is_backfill = backfill is not None
    date_from = backfill.get("date_from") if is_backfill else None
    date_to = backfill.get("date_to") if is_backfill else None

    fetch_log = FetchLog(source_id=source.id, started_at=datetime.now())
    db.add(fetch_log)
    db.commit()

    # 增量用「水位回退」当早停线；补抓用 date_from 当早停线（列表按时间倒序）
    threshold = date_from if is_backfill else _threshold_for(source)

    found = inserted = duplicated = suppressed_n = detail_failed = empty_skipped = 0
    pages_done = 0
    max_seen_publish: datetime | None = None
    old_streak = 0
    first_page_first_url = ""

    try:
        fetcher = Fetcher(source)
        for page in range(1, page_max + 1):
            items = await fetcher.fetch_list(max_items=max_items, page=page)
            if not items:
                break
            if page == 1:
                first_page_first_url = items[0].url
            elif is_same_first_url(first_page_first_url, items[0].url):
                # 分页参数没生效（站点忽略 page），继续翻只会重复下载
                break
            pages_done = page
            found += len(items)

            for item in items:
                pub = item.publish_time

                # 水位候选：所有「已见过」的条目都算，含被去重/抑制跳过的。
                # 否则列表前排的已抓稿被去重后，水位会停在老稿日期，下轮反复重扫。
                if pub is not None:
                    if max_seen_publish is None or pub > max_seen_publish:
                        max_seen_publish = pub

                # 早停统计：只对有日期的条目计数，无日期不误伤
                if pub is not None and threshold is not None:
                    old_streak = 0 if pub > threshold else old_streak + 1

                # 补抓：列表阶段就能确定日期越界的，直接跳过，不下载详情
                if is_backfill and pub is not None:
                    if date_from and pub < date_from:
                        continue
                    if date_to and pub > date_to:
                        continue

                u_h = url_hash(item.url)
                # 去重前置：URL 层在列表阶段就判，已入库的不再下载详情
                if db.execute(select(News.id).where(News.url_hash == u_h).limit(1)).scalar():
                    duplicated += 1
                    continue
                if is_suppressed(db, u_h):
                    suppressed_n += 1
                    continue

                try:
                    detail = await fetcher.fetch_detail(item.url)
                    text = detail.content_text
                except Exception as e:  # noqa: BLE001
                    detail_failed += 1
                    log.warning("detail skipped %s (%s)", item.url, str(e)[:120])
                    if _is_permanent_failure(e):
                        suppress(db, u_h, item.url, "not_found")
                    continue

                if len((text or "").strip()) < 30:
                    empty_skipped += 1
                    log.warning("empty content skipped %s (%s)", item.url, item.title[:30])
                    suppress(db, u_h, item.url, "empty")
                    continue

                # 列表缺日期时用详情页 meta 兜底；补抓需要二次确认日期区间
                final_pub = pub or getattr(detail, "publish_time", None)
                if is_backfill:
                    if final_pub is None:
                        continue
                    if date_from and final_pub < date_from:
                        continue
                    if date_to and final_pub > date_to:
                        continue
                if final_pub is not None:
                    if max_seen_publish is None or final_pub > max_seen_publish:
                        max_seen_publish = final_pub

                s_hash = simhash64(text) if len(text) > 200 else ""
                t_h = title_hash(item.title)
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
                    status="skipped" if (source.selector_config or {}).get("skip_ai") else "fetched",
                    publish_time=final_pub,
                )
                db.add(news)
                inserted += 1
                db.commit()

            # 整页扫完才判早停，避免同页内先旧后新被误停
            if threshold is not None and old_streak >= config.EARLY_STOP_STREAK:
                break

        fetch_log.status = "ok"
        fetch_log.found = found
        fetch_log.inserted = inserted
        fetch_log.duplicated = duplicated
        notes = [f"翻页{pages_done}"]
        if detail_failed:
            notes.append(f"{detail_failed}/{found} 篇详情抓取失败已跳过")
        if empty_skipped:
            notes.append(f"{empty_skipped} 篇无正文已抑制（{SKIP_TTL_DAYS} 天内不重试）")
        if suppressed_n:
            log.info("source %s: %d known-exempt urls skipped", source.name, suppressed_n)
        if notes:
            fetch_log.error = "；".join(notes)

        # 水位只在「增量 + 整轮成功 + 见到了日期」时推进，且只能前进不能后退。
        # 补抓拿到的是历史稿，绝不能推进水位，否则会永久漏掉区间内的新闻。
        if not is_backfill and max_seen_publish is not None:
            old = getattr(source, "last_max_publish", None)
            if old is None or max_seen_publish > old:
                source.last_max_publish = max_seen_publish
        # 补抓是历史回溯，其列表页失败不能污染面向日常抓取的熔断计数，
        # 否则一次补抓可能让正常源在下轮日常抓取中被误熔断跳过。
        if not is_backfill:
            source.consecutive_fail = 0
    except Exception as e:  # noqa: BLE001
        fetch_log.status = "error"
        fetch_log.error = str(e)[:2000]
        fetch_log.found = found
        fetch_log.inserted = inserted
        fetch_log.duplicated = duplicated
        # 失败不推进水位；连续失败累计仅用于日常抓取熔断（补抓不参与）。
        if not is_backfill:
            source.consecutive_fail = (getattr(source, "consecutive_fail", 0) or 0) + 1
        log.exception("source %s failed", source.name)
    finally:
        fetch_log.finished_at = datetime.now()
        source.last_fetch_at = fetch_log.finished_at
        db.commit()
    return fetch_log


async def run_fetch(
    source_id: int | None = None,
    max_items: int | None = None,
    progress_cb=None,
    page_max: int | None = None,
) -> dict:
    """抓取全部启用源（或指定源）。带熔断与全局请求预算。"""
    db = SessionLocal()
    try:
        q = select(Source).where(Source.enabled == True)  # noqa: E712
        if source_id:
            q = q.where(Source.id == source_id)
        sources = db.execute(q).scalars().all()
        results = []
        skipped_circuit = []
        for i, source in enumerate(sources):
            if progress_cb:
                progress_cb({"phase": "抓取中", "done": i, "total": len(sources),
                             "current": source.name})
            fails = getattr(source, "consecutive_fail", 0) or 0
            if fails >= config.CIRCUIT_FAIL_THRESHOLD:
                log.warning("source %s circuit open (%d fails), skip", source.name, fails)
                skipped_circuit.append(source.name)
                continue
            fl = await fetch_source(source, db, max_items=max_items, page_max=page_max)
            results.append({
                "source": source.name,
                "status": fl.status,
                "found": fl.found,
                "inserted": fl.inserted,
                "duplicated": fl.duplicated,
                "error": fl.error,
            })
        return {"sources": len(results), "results": results,
                "circuit_skipped": skipped_circuit}
    finally:
        db.close()


async def run_backfill(
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    region: dict | None = None,
    source_id: int | None = None,
    max_pages: int | None = None,
    progress_cb=None,
    concurrency: int | None = None,
    source_ids: list[int] | None = None,
) -> dict:
    """按日期区间 + 地域补抓历史新闻。

    用于「当时没抓过、后来要补」的场景。只扫匹配的源，深翻历史列表页，
    命中日期区间的条目入库；不推进任何源的水位。

    并发与安全：
    - 复用抓取轮次锁（round_lock），与 12:00/21:00 定时任务互斥，避免长时间
      补抓中途撞上日常抓取、重复下载同一批源。拿不到锁明确返回 locked=True。
    - 有限并发：每源独立 Session（Session 不可跨并发共享），并发度默认 3，
      通过信号量控制；同域名请求仍由 politeness 占位串行化。
    - 无入库硬中断：分批是调用方职责，达到提示阈值仅告警、本批继续跑完。
    """
    from ..round_guard import round_lock

    region = region or {}
    page_max = max_pages or config.BACKFILL_PAGE_MAX
    conc = max(1, min(concurrency or config.BACKFILL_CONCURRENCY, 8))
    # 若显式给了 source_ids，只处理这些源（分批执行用）
    only_ids = set(source_ids or [])

    with round_lock() as got:
        if not got:
            msg = "已有抓取轮次/补抓在运行，本次补抓跳过（避免并发撞车）"
            log.warning(msg)
            return {"locked": True, "sources": 0, "inserted": 0,
                    "results": [], "message": msg}

        db = SessionLocal()
        inserted_total = 0
        try:
            q = select(Source).where(Source.enabled == True)  # noqa: E712
            if source_id:
                q = q.where(Source.id == source_id)
            if only_ids:
                q = q.where(Source.id.in_(only_ids))
            sources = [s for s in db.execute(q).scalars().all()
                       if _region_matches(s, region)]
            # 会话对象跨并发协程不可共享：这里只取 id，worker 内各建 Session
            src_ids = [s.id for s in sources]
            src_names = {s.id: s.name for s in sources}
            total = len(src_ids)
            done = 0
            sem = asyncio.Semaphore(conc)
            results: list[dict] = []

            async def _one(sid: int) -> dict:
                nonlocal done
                async with sem:
                    sdb = SessionLocal()
                    try:
                        s = sdb.get(Source, sid)
                        if s is None:
                            return {"source": src_names.get(sid, str(sid)),
                                    "status": "error", "inserted": 0, "found": 0,
                                    "error": "源不存在"}
                        fl = await fetch_source(
                            s, sdb,
                            max_items=config.PAGE_SIZE,
                            page_max=page_max,
                            backfill={"date_from": date_from, "date_to": date_to},
                        )
                        return {"source": s.name, "status": fl.status,
                                "inserted": fl.inserted, "found": fl.found,
                                "error": fl.error}
                    except Exception as e:  # noqa: BLE001
                        return {"source": src_names.get(sid, str(sid)),
                                "status": "error", "inserted": 0, "found": 0,
                                "error": str(e)[:500]}
                    finally:
                        sdb.close()
                        done += 1
                        if progress_cb:
                            progress_cb({"phase": "补抓中", "done": done, "total": total,
                                         "current": src_names.get(sid, str(sid))})

            raw = await asyncio.gather(*(_one(i) for i in src_ids))
            results = list(raw)
            inserted_total = sum(r["inserted"] for r in results)
            if inserted_total >= config.BACKFILL_ITEM_MAX:
                log.info("backfill batch inserted=%d (提示阈值 %d)，本批继续跑完",
                         inserted_total, config.BACKFILL_ITEM_MAX)
        finally:
            db.close()
        return {"locked": False, "sources": len(results),
                "inserted": inserted_total, "results": results}
