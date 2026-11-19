"""用项目 Fetcher 实测海南候选源：列表可解析 + 详情正文非空（2026-11-19）。

输入 data/hainan_candidates.json（discover_hainan.py 产出），对 status=ok 的源
逐条跑 Fetcher.fetch_list / fetch_detail，标记 fetch_ok / detail_ok。
结果写入 data/hainan_validation.json。
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
import sys
sys.path.insert(0, str(ROOT))

from app.crawler.base import Fetcher  # noqa: E402
from app.models import Source  # noqa: E402

CAND = json.loads((ROOT / "data" / "hainan_candidates.json").read_text())

# 探测阶段被误判/漏判的站点，用手动确认的本地栏目覆盖
FIX = {
    "儋州市人民政府": ("儋州市新闻动态", "https://www.danzhou.gov.cn/danzhou/ywdt/"),
    "东方市人民政府": ("今日东方", "https://dongfang.hainan.gov.cn/ywdt/jrdf/"),
    "白沙黎族自治县人民政府": ("今日白沙", "https://baisha.hainan.gov.cn/ywdt/testjrbs/"),
    "五指山市人民政府": ("政务动态", "http://wzs.hainan.gov.cn/wzs/gzdt/list_zwdt.shtml"),
}

LEVEL = {"province": "province", "city": "city", "district": "district"}


def make_source(r: dict, list_url: str, column: str) -> Source:
    return Source(
        name=r["name"], region_province="海南省",
        region_city=r["city"], region_district=r["district"],
        region_org="", region_area="", level=r["level"],
        base_url=r["home"], list_url=list_url, fetch_type="html",
        selector_config={"column": column}, enabled=1,
    )


async def verify(r: dict):
    if r["name"] in FIX:
        column, list_url = FIX[r["name"]]
    else:
        if r["status"] != "ok":
            return {**r, "fetch_ok": False, "detail_ok": False,
                    "reason": "探测未通过"}
        column, list_url = r["column"], r["list_url"]
        # 省府要闻等外站栏目不能作为本源（会重复抓省级新闻）
        if "hainan.gov.cn/hainan/" in list_url:
            return {**r, "fetch_ok": False, "detail_ok": False,
                    "reason": "探测误判为省府要闻"}
    try:
        src = make_source(r, list_url, column)
        f = Fetcher(src)
        items = await f.fetch_list(max_items=20)
        if not items:
            return {**r, "list_url": list_url, "column": column,
                    "fetch_ok": False, "detail_ok": False, "reason": "列表解析 0 条"}
        # 只取首条有链接的详情验证正文（避免逐条节流耗时）
        detail_ok, detail_len, reason = False, 0, ""
        first = items[0]
        u = getattr(first, "url", "") or (first.get("url") if isinstance(first, dict) else "")
        if not u:
            reason = "首条无链接"
        else:
            try:
                d = await f.fetch_detail(u)
                txt = getattr(d, "content_text", "") or (d.get("content_text") if isinstance(d, dict) else "")
                detail_len = len(txt or "")
                detail_ok = detail_len >= 100
                if not detail_ok:
                    reason = f"正文仅 {detail_len} 字"
            except Exception as e:
                reason = f"详情异常 {type(e).__name__}: {str(e)[:60]}"
        return {**r, "list_url": list_url, "column": column, "fetch_ok": True,
                "items": len(items), "detail_ok": detail_ok,
                "detail_len": detail_len, "reason": reason}
    except Exception as e:
        return {**r, "list_url": list_url, "column": column,
                "fetch_ok": False, "detail_ok": False,
                "reason": f"{type(e).__name__}: {str(e)[:80]}"}


async def main():
    out = []
    for r in CAND:
        v = await verify(r)
        out.append(v)
        print(f"{'OK' if v['fetch_ok'] and v['detail_ok'] else '  '} "
              f"{v.get('items', 0):>3}条 {'✓' if v['detail_ok'] else ' '} "
              f"{r['district'] or r['city']:<12} {v['reason'][:50]}", flush=True)
    (ROOT / "data" / "hainan_validation.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    good = [v for v in out if v["fetch_ok"] and v["detail_ok"]]
    print(f"\n通过: {len(good)}/{len(out)} -> data/hainan_validation.json", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
