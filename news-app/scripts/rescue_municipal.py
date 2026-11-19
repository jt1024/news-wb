"""抢救性验证：Fetcher 因 SSL 升级/证书问题失败的站点，用 curl 直连首页验证。

对 validate_municipal.py 中失败的站点，用 curl 抓首页（跟随实际协议），
提取首页里的新闻详情链接，验证首条详情页正文非空。通过的站点以首页为
list_url 纳入，同时收集需加入 Fetcher.HTTP_ONLY_HOSTS 的 http-only 域名。
结果写回 data/municipal_validation.json（合并覆盖）。
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.crawler.base import Fetcher  # noqa: E402
from app.models import Source  # noqa: E402
import scripts.discover_municipal as disco  # noqa: E402

UA = disco.UA
CTX = disco.CTX
VAL = ROOT / "data" / "municipal_validation.json"


def curl(url: str, timeout: int = 15) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
        return resp.read()


def curl_auto(url: str):
    return disco.curl_auto(url)


def detail_text(url: str) -> str:
    try:
        data = curl(url)
        for enc in ("utf-8", "gb18030"):
            try:
                h = data.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            h = data.decode("utf-8", errors="ignore")
        # 粗提取正文：去 script/style/标签，取中文密度最高的片段
        h = re.sub(r"<script.*?</script>|<style.*?</style>", " ", h, flags=re.S | re.I)
        txt = re.sub(r"<[^>]+>", " ", h)
        txt = re.sub(r"\s+", " ", txt)
        # 取所有较长中文段落拼接
        segs = re.findall(r"[\u4e00-\u9fff，。、；：（）\u201c\u201d]{40,}", txt)
        return " ".join(segs)[:3000]
    except Exception:
        return ""


def rescue(r: dict) -> dict:
    home = r.get("home_real") or r["home"]
    out = dict(r)
    try:
        real, html = curl_auto(home)
        n = disco.count_items(html, real)
        if n < 5:
            out["reason"] = f"curl首页仅{n}条"
            return out
        # 找首条新闻链接
        news_urls = []
        for m in re.finditer(r'href=["\']([^"\']+)["\'][^>]*>([^<]{6,80})<', html):
            u = urljoin(real, m.group(1))
            if disco.NEWS_URL.search(u) and not re.search(r"index\.(s?html?|php)$", u):
                news_urls.append(u)
        if not news_urls:
            out["reason"] = "首页无详情链接"
            return out
        # 验证前3条详情正文
        best = ""
        for u in news_urls[:3]:
            t = detail_text(u)
            if len(t) > len(best):
                best = t
            if len(best) >= 150:
                break
        if len(best) < 100:
            out["reason"] = f"详情正文仅{len(best)}字"
            return out
        out.update(detail_ok=True, items=n, detail_len=len(best),
                   final_list_url=real, final_column="首页(curl)",
                   reason="")
    except Exception as e:
        out["reason"] = f"{type(e).__name__}: {str(e)[:40]}"
    return out


def main():
    data = json.loads(VAL.read_text())
    fails = [r for r in data if not r["detail_ok"]]
    print(f"抢救 {len(fails)} 个失败站点...", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        rescued = list(ex.map(rescue, fails))
    # 合并回 data
    by_name = {(r["province"], r["district"]): r for r in rescued}
    for r in data:
        if (r["province"], r["district"]) in by_name:
            r.update(by_name[(r["province"], r["district"])])
    for r in rescued:
        mark = "OK " if r["detail_ok"] else "   "
        print(f"{mark}{r['province']} {r['district']:<10} {r.get('items',0):>3}条 "
              f"{r['reason'][:40]}", flush=True)
    ok = sum(1 for r in data if r["detail_ok"])
    print(f"\n最终通过: {ok}/{len(data)}", flush=True)
    VAL.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
