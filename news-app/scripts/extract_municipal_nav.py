"""从四直辖市门户的'区政府网站'导航页提取各区县官网域名（2026-11-20）。

对北京/上海/天津/重庆市政府门户的网站导航页，正则抓 <a href=...>文字</a>，
用 app/data/regions.json 的区县政府名称（简称）匹配链接文字，输出 名称->域名。
结果写入 data/municipal_nav.json，供 discover_municipal.py 使用。
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

PAGES = {
    "北京市": [
        "https://www.beijing.gov.cn/",
        "https://www.beijing.gov.cn/so/s?qt=%E5%90%84%E5%8C%BA%E6%94%BF%E5%BA%9C",
    ],
    "上海市": [
        "https://www.shanghai.gov.cn/",
    ],
    "天津市": [
        "https://www.tj.gov.cn/glllm_55512/glsy/wzdt/",
        "https://www.tj.gov.cn/",
    ],
    "重庆市": [
        "https://www.cq.gov.cn/zwgk/zfxxgkzl/zfxxgkzn/",
        "https://www.cq.gov.cn/",
    ],
}


def curl(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=25, context=CTX) as resp:
        data = resp.read()
    for enc in ("utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def load_names() -> dict[str, list[str]]:
    d = json.loads((ROOT / "app" / "data" / "regions.json").read_text())
    out = {}
    for p in d["provinces"]:
        if p["name"] not in PAGES:
            continue
        names = []
        for c in p.get("cities", []):
            for x in c.get("districts", []):
                n = x["name"]
                names.append(n)
                # 简称：去掉"自治县/土家族..."等民族后缀
                short = re.sub(r"(土家族|苗族|黎族|回族|满族|朝鲜族|自治县)", "", n)
                names.append(short)
        out[p["name"]] = sorted(set(names), key=len, reverse=True)
    return out


def extract(prov: str, html: str, names: list[str]) -> dict[str, str]:
    found = {}
    for m in re.finditer(r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, re.S):
        href, text = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not href or href.startswith(("#", "javascript", "mailto")):
            continue
        for n in names:
            if n and n in text and len(text) <= len(n) + 10:
                u = urljoin(PAGES[prov][0], href)
                host = urlparse(u).netloc
                if host and ("gov.cn" in host or ".gov." in host):
                    found.setdefault(n, f"{urlparse(u).scheme}://{host}/")
                break
    return found


def main():
    names_by_prov = load_names()
    result = {}
    for prov, pages in PAGES.items():
        merged = {}
        for p in pages:
            try:
                html = curl(p)
                got = extract(prov, html, names_by_prov[prov])
                print(f"[{prov}] {p} -> {len(got)} 个匹配", flush=True)
                for n, u in got.items():
                    merged.setdefault(n, u)
            except Exception as e:
                print(f"[{prov}] {p} 异常 {type(e).__name__}: {e}", flush=True)
        result[prov] = merged
        print(f"  === {prov} 汇总 {len(merged)} 个 ===", flush=True)
        for n, u in sorted(merged.items()):
            print(f"    {n:<12} {u}", flush=True)
    out = ROOT / "data" / "municipal_nav.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n结果 -> {out}", flush=True)


if __name__ == "__main__":
    main()
