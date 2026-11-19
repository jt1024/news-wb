"""探测海南市区县政府门户的政务要闻列表页（一次性工具，2026-11-19）。

思路复用 discover_sources.py：抓首页 → 找「要闻/政务动态」栏目 → 验证列表页
能解析出 ≥5 条候选新闻链接。结果写入 data/hainan_candidates.json。
"""
from __future__ import annotations

import json
import re
import urllib.request
import ssl
from pathlib import Path
from urllib.parse import urljoin

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
ROOT = Path(__file__).resolve().parent.parent

# (名称, 省, 市, 区县, level, 首页)
SITES = [
    ("海口市人民政府", "海口市", "", "city", "https://www.haikou.gov.cn/"),
    ("海口市秀英区人民政府", "海口市", "秀英区", "district", "http://xyqzf.haikou.gov.cn/"),
    ("海口市龙华区人民政府", "海口市", "龙华区", "district", "http://lhqzf.haikou.gov.cn/"),
    ("海口市琼山区人民政府", "海口市", "琼山区", "district", "http://qsqzf.haikou.gov.cn/"),
    ("海口市美兰区人民政府", "海口市", "美兰区", "district", "http://mlqzf.haikou.gov.cn/"),
    ("三亚市人民政府", "三亚市", "", "city", "https://www.sanya.gov.cn/"),
    ("三亚市海棠区人民政府", "三亚市", "海棠区", "district", "https://ht.sanya.gov.cn/"),
    ("三亚市吉阳区人民政府", "三亚市", "吉阳区", "district", "https://jy.sanya.gov.cn/"),
    ("三亚市天涯区人民政府", "三亚市", "天涯区", "district", "https://ty.sanya.gov.cn/"),
    ("三亚市崖州区人民政府", "三亚市", "崖州区", "district", "https://yz.sanya.gov.cn/"),
    ("儋州市人民政府", "儋州市", "", "city", "https://www.danzhou.gov.cn/"),
    ("五指山市人民政府", "省直辖县级行政区划", "五指山市", "district", "https://www.wuzhishan.gov.cn/"),
    ("琼海市人民政府", "省直辖县级行政区划", "琼海市", "district", "https://qionghai.hainan.gov.cn/"),
    ("文昌市人民政府", "省直辖县级行政区划", "文昌市", "district", "https://wenchang.hainan.gov.cn/"),
    ("万宁市人民政府", "省直辖县级行政区划", "万宁市", "district", "https://wanning.hainan.gov.cn/"),
    ("东方市人民政府", "省直辖县级行政区划", "东方市", "district", "https://dongfang.hainan.gov.cn/"),
    ("定安县人民政府", "省直辖县级行政区划", "定安县", "district", "https://dingan.hainan.gov.cn/"),
    ("屯昌县人民政府", "省直辖县级行政区划", "屯昌县", "district", "https://tunchang.hainan.gov.cn/"),
    ("澄迈县人民政府", "省直辖县级行政区划", "澄迈县", "district", "https://chengmai.hainan.gov.cn/"),
    ("临高县人民政府", "省直辖县级行政区划", "临高县", "district", "https://lingao.hainan.gov.cn/"),
    ("白沙黎族自治县人民政府", "省直辖县级行政区划", "白沙黎族自治县", "district", "https://baisha.hainan.gov.cn/"),
    ("昌江黎族自治县人民政府", "省直辖县级行政区划", "昌江黎族自治县", "district", "https://changjiang.hainan.gov.cn/"),
    ("乐东黎族自治县人民政府", "省直辖县级行政区划", "乐东黎族自治县", "district", "https://ledong.hainan.gov.cn/"),
    ("陵水黎族自治县人民政府", "省直辖县级行政区划", "陵水黎族自治县", "district", "https://lingshui.hainan.gov.cn/"),
    ("保亭黎族苗族自治县人民政府", "省直辖县级行政区划", "保亭黎族苗族自治县", "district", "https://baoting.hainan.gov.cn/"),
    ("琼中黎族苗族自治县人民政府", "省直辖县级行政区划", "琼中黎族苗族自治县", "district", "https://qiongzhong.hainan.gov.cn/"),
]

COL_PAT = re.compile(r"要闻动态|政务动态|今日[^\s<]{0,6}|要闻|政务要闻|本地新闻|新闻动态|头条")
# 形似新闻详情链接（含日期/内容 id/静态文章后缀）
NEWS_URL = re.compile(r"(t20\d{6}_\d+|/20\d{6}/|\d{6,}_\d+\.s?html|/content/|/art/\d+|post_\d+|\.s?html$|\.s?htm$)")


_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def curl(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=18, context=_CTX) as resp:
        data = resp.read()
    for enc in ("utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def find_columns(home: str, base: str) -> list[tuple[str, str]]:
    seen, out = set(), []
    for m in re.finditer(r'<a[^>]+href=["\']([^"\'#]+)["\'][^>]*>([^<]{2,24})</a>', home):
        href, text = m.group(1), m.group(2).strip()
        if href in seen or not text or not COL_PAT.search(text):
            continue
        url = urljoin(base, href)
        if not url.startswith("http"):
            continue
        seen.add(href)
        out.append((text, url))
    out.sort(key=lambda x: (0 if re.search(r"要闻动态|政务动态|政务要闻", x[0]) else 1))
    return out[:8]


def count_items(html: str, base: str) -> int:
    urls = set()
    for m in re.finditer(r'href=["\']([^"\']+)["\'][^>]*>([^<]{6,80})<', html):
        href, text = m.group(1), m.group(2).strip()
        if len(text) < 8:
            continue
        u = urljoin(base, href)
        if NEWS_URL.search(u) and not re.search(r"index\.(s?html?|php)$", u):
            urls.add(u)
    return len(urls)


def main():
    results = []
    for name, city, district, level, home_url in SITES:
        entry = {"name": name, "city": city, "district": district, "level": level,
                 "home": home_url, "status": "fail", "list_url": "", "column": "", "items": 0}
        try:
            home = curl(home_url)
            if len(home) < 2000:
                entry["note"] = f"首页异常/过短({len(home)})"
                print(f"[{name}] 首页异常 {len(home)}", flush=True)
                results.append(entry)
                continue
            cols = find_columns(home, home_url)
            print(f"[{name}] 候选栏目 {len(cols)} 个", flush=True)
            for text, url in cols:
                html = curl(url)
                n = count_items(html, url)
                print(f"    {text} -> {url} : {n} 条", flush=True)
                if n >= 5:
                    entry.update(status="ok", list_url=url, column=text, items=n,
                                 note=f"首页栏目「{text}」解析 {n} 条")
                    break
            if entry["status"] != "ok":
                entry["note"] = "候选栏目均不足 5 条"
        except Exception as e:
            entry["note"] = f"异常 {type(e).__name__}: {e}"
        results.append(entry)
    out = ROOT / "data" / "hainan_candidates.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"\n结果: {ok}/{len(results)} 可用 -> {out}", flush=True)


if __name__ == "__main__":
    main()
