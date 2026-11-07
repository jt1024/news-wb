"""政策走向分析 API：主题热度、地市活跃度、类型分布、上升话题。

全部为只读聚合查询，基于 news / tags / news_tags 三张表；
时间维度一律用 publish_time（发布日期），数据为空时返回空结构而非报错。
"""
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from ..auth import require_auth
from ..db import get_db

router = APIRouter(dependencies=[Depends(require_auth)])

TYPE_LABEL = {
    "news": "新闻动态",
    "notice": "通知公告",
    "policy": "政策文件",
    "interpretation": "政策解读",
    "procurement": "招采公示",
}


@router.get("/api/trends")
def trends(days: int = Query(30, ge=7, le=365), db: Session = Depends(get_db)):
    now = datetime.now()
    start = now - timedelta(days=days)
    d7 = now - timedelta(days=7)
    d14 = now - timedelta(days=14)

    # ---- 1. 每日发布量 ----
    daily = [
        {"date": r.d, "n": r.n}
        for r in db.execute(
            text("""SELECT date(publish_time) d, count(*) n
                    FROM news WHERE publish_time >= :start
                    GROUP BY d ORDER BY d"""),
            {"start": start},
        )
    ]

    # ---- 2. 地市活跃度 ----
    city_totals = [
        {"city": (r.c or "广东省"), "n": r.n}
        for r in db.execute(
            text("""SELECT region_city c, count(*) n
                    FROM news WHERE publish_time >= :start
                    GROUP BY region_city ORDER BY n DESC"""),
            {"start": start},
        )
    ]

    # ---- 3. 内容类型分布 ----
    # 注意：列别名不要用单字母 t（与 Row 内部属性冲突），用 ctype
    type_totals = [
        {"type": r.ctype, "label": TYPE_LABEL.get(r.ctype, r.ctype), "n": r.n}
        for r in db.execute(
            text("""SELECT content_type ctype, count(*) n
                    FROM news WHERE publish_time >= :start
                    GROUP BY content_type ORDER BY n DESC"""),
            {"start": start},
        )
    ]

    # ---- 4. 主题热度（窗口内总量 Top 8 + 每日序列） ----
    top_rows = db.execute(
        text("""SELECT t.name name, count(*) n
                FROM news_tags nt
                JOIN tags t ON t.id = nt.tag_id
                JOIN news ON news.id = nt.news_id
                WHERE news.publish_time >= :start
                GROUP BY t.name ORDER BY n DESC LIMIT 8"""),
        {"start": start},
    ).all()
    topics = [{"tag": r.name, "total": r.n, "series": []} for r in top_rows]
    if topics:
        names = [t["tag"] for t in topics]
        series_rows = db.execute(
            text("""SELECT t.name name, date(news.publish_time) d, count(*) n
                    FROM news_tags nt
                    JOIN tags t ON t.id = nt.tag_id
                    JOIN news ON news.id = nt.news_id
                    WHERE news.publish_time >= :start AND t.name IN :names
                    GROUP BY t.name, d ORDER BY d""").bindparams(
                bindparam("names", expanding=True)
            ),
            {"start": start, "names": names},
        ).all()
        # 按标签聚成 {tag: {date: n}}，再对齐到 daily 的日期轴（缺失日补 0）
        by_tag_date = {}
        for r in series_rows:
            by_tag_date.setdefault(r.name, {})[r.d] = r.n
        for t in topics:
            t["series"] = [
                {"date": row["date"], "n": by_tag_date.get(t["tag"], {}).get(row["date"], 0)}
                for row in daily
            ]

    # ---- 5. 上升话题：近 7 天 vs 前 7 天 ----
    # SQLite 的 ORDER BY/HAVING 不能引用 SELECT 别名，表达式需原样重写；
    # delta（增量）在 Python 侧计算与排序
    rising_rows = db.execute(
        text("""SELECT t.name name,
                       sum(CASE WHEN news.publish_time >= :d7 THEN 1 ELSE 0 END) recent,
                       sum(CASE WHEN news.publish_time >= :d14 AND news.publish_time < :d7 THEN 1 ELSE 0 END) previous
                FROM news_tags nt
                JOIN tags t ON t.id = nt.tag_id
                JOIN news ON news.id = nt.news_id
                WHERE news.publish_time >= :d14
                GROUP BY t.name
                HAVING (sum(CASE WHEN news.publish_time >= :d7 THEN 1 ELSE 0 END)
                        + sum(CASE WHEN news.publish_time >= :d14 AND news.publish_time < :d7 THEN 1 ELSE 0 END)) >= 2
                ORDER BY recent DESC LIMIT 30"""),
        {"d7": d7, "d14": d14},
    ).all()
    rising = sorted(
        (
            {
                "tag": r.name,
                "recent": r.recent,
                "previous": r.previous,
                "delta": r.recent - r.previous,
                "growth": round((r.recent - r.previous) / max(r.previous, 1), 2),
            }
            for r in rising_rows
        ),
        key=lambda x: (x["delta"], x["recent"]),
        reverse=True,
    )[:10]

    total = db.execute(
        text("SELECT count(*) FROM news WHERE publish_time >= :start"), {"start": start}
    ).scalar()

    return {
        "days": days,
        "total": total,
        "daily": daily,
        "city_totals": city_totals,
        "type_totals": type_totals,
        "topics": topics,
        "rising": rising,
        "generated_at": now.isoformat(timespec="seconds"),
    }
