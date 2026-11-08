"""趋势深化：政策信号生命周期串联 + 同主题地市对比矩阵。

信号链的思想：一条政策通常会经历「征求意见 → 正式印发 → 贯彻落实 → 政策解读」，
这些文章散落在 21 个地市、不同栏目里。按 AI 主题标签把它们串成时间线，
就能看出某个主题是刚启动、正在铺开，还是已进入落地阶段。

全部为只读查询；识别规则集中在 STAGE_RULES，便于后续调整。
"""
from collections import defaultdict

from sqlalchemy import bindparam, text

# 顺序即优先级：「征求意见」和「解读」要先于「发布/印发」判断，
# 否则「《XX办法（征求意见稿）》发布」「政策解读发布会」会被误判成正式印发。
STAGE_RULES = [
    ("draft", "征求意见", ("征求意见", "公开征求", "征求意见稿", "草案", "拟修订", "意见建议")),
    ("interpretation", "政策解读", ("解读", "答记者问", "政策问答", "政策说明")),
    ("issued", "正式印发", ("印发", "出台", "颁布", "发布", "公告", "施行", "决定")),
    # 「推进 / 调研 / 部署 / 落地」在普通政务新闻标题里太常见，会把大量日常动态
    # 误判成政策落地信号，因此只保留指向明确的执行类措辞。
    ("implementation", "贯彻落实", ("贯彻", "落实", "实施细则", "督导", "宣讲",
                                    "部署落实", "贯彻落实")),
]
STAGE_ORDER = [s[0] for s in STAGE_RULES]
STAGE_LABEL = {s[0]: s[1] for s in STAGE_RULES}


def detect_stage(title: str, content_type: str) -> str | None:
    """按标题关键词判断政策阶段；无关键词时按内容类型兜底。"""
    t = title or ""
    for stage, _label, keywords in STAGE_RULES:
        if any(k in t for k in keywords):
            return stage
    if content_type == "interpretation":
        return "interpretation"
    if content_type in ("policy", "notice"):
        return "issued"
    return None


def policy_chains(db, start, limit: int = 6) -> dict:
    """按主题聚合政策信号，返回覆盖 ≥2 个阶段的链条与阶段分布。"""
    rows = db.execute(
        text("""SELECT n.title title,
                       COALESCE(NULLIF(n.region_org,''), NULLIF(n.region_city,''), '广东省') city,
                       n.publish_time pub, n.url url, n.content_type ctype, t.name tag
                FROM news n
                JOIN news_tags nt ON nt.news_id = n.id
                JOIN tags t ON t.id = nt.tag_id
                WHERE n.publish_time >= :start AND t.name != '其他'
                ORDER BY n.publish_time DESC"""),
        {"start": start},
    ).all()

    by_tag: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    stage_totals = {s: 0 for s in STAGE_ORDER}
    for r in rows:
        stage = detect_stage(r.title, r.ctype)
        if not stage:
            continue
        stage_totals[stage] += 1
        by_tag[r.tag][stage].append({
            "title": r.title,
            "city": r.city or "广东省",
            "date": (r.pub or "")[:10],
            "url": r.url,
        })

    chains = []
    for tag, stages in by_tag.items():
        covered = [s for s in STAGE_ORDER if stages.get(s)]
        if len(covered) < 2:  # 单阶段不构成「走向」
            continue
        total = sum(len(v) for v in stages.values())
        all_dates = [it["date"] for items in stages.values() for it in items if it["date"]]
        chains.append({
            "tag": tag,
            "coverage": len(covered),
            "total": total,
            "first_date": min(all_dates) if all_dates else "",
            "last_date": max(all_dates) if all_dates else "",
            "stages": [
                {
                    "stage": s,
                    "label": STAGE_LABEL[s],
                    "count": len(stages.get(s, [])),
                    "items": stages.get(s, [])[:3],
                }
                for s in STAGE_ORDER
            ],
        })
    chains.sort(key=lambda x: (x["coverage"], x["total"]), reverse=True)
    return {
        "chains": chains[:limit],
        "stage_totals": [
            {"stage": s, "label": STAGE_LABEL[s], "n": stage_totals[s]}
            for s in STAGE_ORDER
        ],
        "signal_total": sum(stage_totals.values()),
    }


def city_topic_matrix(db, start, topics: list[str], cities: list[str]) -> dict:
    """Top 主题 × Top 地市的交叉发文量，供热力图对比同一主题下谁在密集发声。"""
    if not topics or not cities:
        return {"topics": [], "cities": [], "cells": [], "max": 0}
    rows = db.execute(
        text("""SELECT t.name tag, n.region_city city, count(*) n
                FROM news n
                JOIN news_tags nt ON nt.news_id = n.id
                JOIN tags t ON t.id = nt.tag_id
                WHERE n.publish_time >= :start AND t.name IN :topics
                  AND n.level != 'national'
                GROUP BY t.name, n.region_city""").bindparams(
            bindparam("topics", expanding=True)
        ),
        {"start": start, "topics": topics},
    ).all()
    city_set = set(cities)
    counts = {(r.tag, (r.city or "广东省")): r.n for r in rows
              if (r.city or "广东省") in city_set}
    cells = [
        {"topic": t, "city": c, "n": counts.get((t, c), 0)}
        for t in topics for c in cities
    ]
    return {
        "topics": topics,
        "cities": cities,
        "cells": cells,
        "max": max((x["n"] for x in cells), default=0),
    }
