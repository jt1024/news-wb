"""全源体检：库内存量数据噪音扫描 + 实时重抓详情页验证提取质量。

用法: cd news-app && .venv/bin/python scripts/audit_sources.py
"""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.crawler.base import Fetcher
from app.db import SessionLocal
from app.models import News, Source

# 噪音特征（出现在正文前 400 字内视为可疑）
NOISE_SIGNATURES = [
    "当前位置", "浏览字体", "分享到", "【打印", "【关闭", "关闭页面", "字体大小",
    "阅读人次", "【TOP】", "微信扫一扫", "扫一扫", "网站地图", "无障碍",
    "长者模式", "粤ICP备", "版权所有",
]
HTML_RESIDUE_RE = re.compile(r"<(?:p|br|div|span)[^>]*>", re.I)
JS_RESIDUE_RE = re.compile(r"(function\s*\(|window\.|document\.|var\s+\w+\s*=)")
ENCODING_BAD_RE = re.compile(r"[\ufffd]")


def scan_text(text: str) -> list[str]:
    """返回命中的问题标签列表。"""
    issues = []
    head = text[:400]
    for kw in NOISE_SIGNATURES:
        if kw in head:
            issues.append(f"噪音:{kw}")
    if HTML_RESIDUE_RE.search(text[:600]):
        issues.append("HTML残留")
    if JS_RESIDUE_RE.search(text[:600]):
        issues.append("JS残留")
    if ENCODING_BAD_RE.search(text):
        issues.append("乱码")
    if len(text) < 80:
        issues.append("正文过短")
    # 面包屑特征：连续的 > 导航
    if re.search(r"首页\s*>\s*\S+\s*>", head):
        issues.append("面包屑")
    return issues


def audit_db() -> dict[str, list]:
    """库内存量数据扫描，返回 {源名: [(id, city, issues, 样本), ...]}"""
    db = SessionLocal()
    report: dict[str, list] = {}
    try:
        rows = db.execute(select(News).order_by(News.id.desc())).scalars().all()
        for n in rows:
            issues = scan_text(n.content_text or "")
            if issues:
                report.setdefault(n.title[:0] or "", [])
                src = n.source.name if n.source else "?"
                report.setdefault(src, []).append(
                    (n.id, n.region_city, issues, (n.content_text or "")[:60].replace("\n", "⏎"))
                )
    finally:
        db.close()
    return report


async def audit_live(max_per_source: int = 2) -> list[dict]:
    """实时重抓每个源最新详情页，验证当前代码的提取质量。"""
    db = SessionLocal()
    results = []
    try:
        sources = db.execute(select(Source).where(Source.enabled == True)).scalars().all()  # noqa: E712
        for s in sources:
            # 取该源最新入库的详情 URL 重抓
            urls = [
                row[0]
                for row in db.execute(
                    select(News.url).where(News.source_id == s.id).order_by(News.id.desc()).limit(max_per_source)
                ).all()
            ]
            f = Fetcher(s)
            problems, samples = [], []
            for u in urls[:1]:
                try:
                    d = await f.fetch_detail(u)
                    issues = scan_text(d.content_text or "")
                    if issues or len(d.content_text or "") < 80:
                        problems.append((u, issues, len(d.content_text or "")))
                        samples.append((d.content_text or "")[:70].replace("\n", "⏎"))
                except Exception as e:  # noqa: BLE001
                    problems.append((u, [f"抓取失败:{str(e)[:60]}"], 0))
            results.append({
                "source": s.name,
                "id": s.id,
                "ok": not problems,
                "problems": problems,
                "samples": samples,
            })
    finally:
        db.close()
    return results


if __name__ == "__main__":
    print("=" * 30, "① 库内存量扫描", "=" * 30)
    db_report = audit_db()
    if not db_report:
        print("库内数据全部干净 ✓")
    else:
        for src, items in db_report.items():
            print(f"\n[{src}] {len(items)} 条可疑")
            for nid, city, issues, sample in items[:4]:
                print(f"  #{nid} {city} {issues}")
                print(f"      {sample!r}")

    print("\n" + "=" * 30, "② 实时重抓验证", "=" * 30)
    live = asyncio.run(audit_live())
    bad = [r for r in live if not r["ok"]]
    print(f"实时检查: {len(live) - len(bad)}/{len(live)} 个源提取正常")
    for r in bad:
        print(f"\n✗ {r['source']} (id={r['id']})")
        for u, issues, ln in r["problems"]:
            print(f"  {issues} len={ln}")
            print(f"  {u}")
        for smp in r["samples"][:1]:
            print(f"  样本: {smp!r}")
