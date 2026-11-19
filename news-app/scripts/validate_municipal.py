"""用项目 Fetcher 实测四直辖市候选源：列表可解析 + 详情正文非空（2026-11-20）。

输入 data/municipal_candidates.json。校验策略：
  * 探测 OK 且 list_url 属于本站（剔除外站误判如 ncac.gov.cn）-> 用探测栏目；
  * 否则尝试首页直接 fetch_list（多数政务门户首页即含政务新闻）；
  * 首页 0 条 -> 从首页提取候选栏目（允许嵌套标签、限本站域名）逐个 Fetcher 验证。
首条详情正文非空即判定 usable。结果写入 data/municipal_validation.json。
"""
from __future__ import annotations

import asyncio
import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.crawler.base import Fetcher  # noqa: E402
from app.models import Source  # noqa: E402

CAND = json.loads((ROOT / "data" / "municipal_candidates.json").read_text())

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
COL_PAT = re.compile(r"要闻|动态|新闻|政务|今日|资讯|要闻动态|工作动态|领导活动")

SEM = asyncio.Semaphore(8)


def curl(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=15, context=CTX) as resp:
        data = resp.read()
    for enc in ("utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def core_host(url: str) -> str:
    h = urlparse(url).netloc.lower()
    parts = [p for p in h.split(".") if p not in ("www", "")]
    return ".".join(parts[-3:]) if len(parts) >= 3 else h


def same_site(list_url: str, home: str) -> bool:
    lc, hc = core_host(list_url), core_host(home)
    return lc == hc or lc.endswith("." + hc) or hc.endswith("." + lc)


def extract_columns(home_html: str, base: str) -> list[str]:
    """从首页提取候选栏目 URL（允许 <a> 内含 span 等嵌套标签，限本站域名）。"""
    urls, seen = [], set()
    core = core_host(base)
    for m in re.finditer(r"<a[^>]+href=[\"']([^\"'\#]+)[\"'][^>]*>(.*?)</a>", home_html, re.S):
        href = m.group(1)
        text = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not text or not COL_PAT.search(text) or len(text) > 24:
            continue
        u = urljoin(base, href)
        if not u.startswith("http") or core not in core_host(u):
            continue
        if re.search(r"\.(pdf|doc|docx|xls|xlsx|zip)$", u):
            continue
        if u not in seen:
            seen.add(u)
            urls.append(u)
    # 优先含"要闻/动态"的路径
    urls.sort(key=lambda u: (0 if re.search(r"yw|zw|xw|news|dt|yaowen|dongtai|gzdt", u, re.I) else 1))
    return urls[:12]


def make_source(r: dict, list_url: str) -> Source:
    return Source(
        name=r["name"], region_province=r["province"],
        region_city=r["city"], region_district=r["district"],
        region_org="", region_area="", level=r["level"],
        base_url=r.get("home_real") or r["home"], list_url=list_url,
        fetch_type="html", selector_config={}, enabled=1,
    )


async def try_list(f: Fetcher):
    try:
        return await f.fetch_list(max_items=20)
    except Exception:
        return []


async def verify(r: dict) -> dict:
    out = {**r, "final_list_url": "", "final_column": "", "items": 0,
           "detail_ok": False, "detail_len": 0, "reason": ""}
    candidates = []
    # 1) 探测 OK 且同源的栏目
    if r["status"] == "ok" and r.get("list_url") and same_site(r["list_url"], r.get("home_real") or r["home"]):
        candidates.append((r["list_url"], r.get("column", "")))
    # 2) 首页
    home = r.get("home_real") or r["home"]
    candidates.append((home, "首页"))
    # 3) 首页提取的栏目（Fetcher 试）
    try:
        hh = curl(home)
        for u in extract_columns(hh, home):
            candidates.append((u, "栏目"))
    except Exception:
        pass

    async with SEM:
        for list_url, column in candidates[:14]:
            src = make_source(r, list_url)
            f = Fetcher(src)
            items = await try_list(f)
            if len(items) < 5:
                continue
            # 详情首条验证正文
            u = getattr(items[0], "url", "")
            detail_ok, detail_len = False, 0
            if u:
                try:
                    d = await f.fetch_detail(u)
                    detail_len = len(getattr(d, "content_text", "") or "")
                    detail_ok = detail_len >= 100
                except Exception:
                    pass
            if detail_ok:
                out.update(final_list_url=list_url, final_column=column,
                           items=len(items), detail_ok=True, detail_len=detail_len)
                return out
            out["reason"] = f"列表{len(items)}条但正文仅{detail_len}字"
    if not out["reason"]:
        out["reason"] = "候选列表均<5条或详情无正文"
    return out


async def main():
    out = []
    for r in CAND:
        v = await verify(r)
        out.append(v)
        mark = "OK " if v["detail_ok"] else "   "
        print(f"{mark}{v['province']} {v['district']:<9} {v['items']:>3}条 "
              f"{v['final_column']:<6} {v['reason'][:38]}", flush=True)
    (ROOT / "data" / "municipal_validation.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    good = [v for v in out if v["detail_ok"]]
    print(f"\n通过: {len(good)}/{len(out)} -> data/municipal_validation.json", flush=True)
    for prov in ["北京市", "上海市", "天津市", "重庆市"]:
        n = sum(1 for v in good if v["province"] == prov)
        tot = sum(1 for v in out if v["province"] == prov)
        print(f"  {prov}: {n}/{tot}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
