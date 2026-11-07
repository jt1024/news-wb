"""自动探测地市政府网站的政务动态列表页。

对每个城市域名：抓首页 → 找「动态/要闻/新闻」栏目链接 → 逐个验证能否解析出
≥5 条候选新闻链接 → 输出可用源配置。结果写入 docs/discovered_sources.json。
"""
import json
import re
import subprocess
import sys
from urllib.parse import urljoin

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"

CITIES = [
    ("广东省人民政府", "广东省", "province", "https://www.gd.gov.cn"),
    ("珠海市人民政府", "珠海市", "city", "https://www.zhuhai.gov.cn"),
    ("汕头市人民政府", "汕头市", "city", "https://www.shantou.gov.cn"),
    ("韶关市人民政府", "韶关市", "city", "https://www.sg.gov.cn"),
    ("湛江市人民政府", "湛江市", "city", "https://www.zhanjiang.gov.cn"),
    ("肇庆市人民政府", "肇庆市", "city", "https://www.zhaoqing.gov.cn"),
    ("江门市人民政府", "江门市", "city", "https://www.jiangmen.gov.cn"),
    ("茂名市人民政府", "茂名市", "city", "https://www.maoming.gov.cn"),
    ("惠州市人民政府", "惠州市", "city", "https://www.huizhou.gov.cn"),
    ("梅州市人民政府", "梅州市", "city", "https://www.meizhou.gov.cn"),
    ("汕尾市人民政府", "汕尾市", "city", "https://www.shanwei.gov.cn"),
    ("河源市人民政府", "河源市", "city", "https://www.heyuan.gov.cn"),
    ("阳江市人民政府", "阳江市", "city", "https://www.yangjiang.gov.cn"),
    ("清远市人民政府", "清远市", "city", "https://www.qy.gov.cn"),
    ("东莞市人民政府", "东莞市", "city", "https://www.dg.gov.cn"),
    ("中山市人民政府", "中山市", "city", "https://www.zs.gov.cn"),
    ("潮州市人民政府", "潮州市", "city", "https://www.chaozhou.gov.cn"),
    ("揭阳市人民政府", "揭阳市", "city", "https://www.jieyang.gov.cn"),
    ("云浮市人民政府", "云浮市", "city", "https://www.yunfu.gov.cn"),
]


def curl(url: str) -> str:
    p = subprocess.run(
        ["curl", "-sS", "-L", "--compressed", "-m", "15", "-A", UA, url],
        capture_output=True,
    )
    data = p.stdout
    for enc in ("utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def find_column_links(home_html: str, base: str) -> list[tuple[str, str]]:
    """从首页提取 (标题, URL) 候选栏目，优先含「动态/要闻」的。"""
    seen, out = set(), []
    for m in re.finditer(r'<a[^>]+href="([^"#]+)"[^>]*>([^<]{2,20})</a>', home_html):
        href, text = m.group(1), m.group(2).strip()
        if href in seen or not text:
            continue
        if re.search(r"政务动态|要闻|新闻动态|工作动态|时政|头条|聚焦", text):
            url = urljoin(base, href)
            if not url.startswith("http"):
                continue
            if re.search(r"(gov\.cn|\.gov)", url) or url.startswith(base):
                seen.add(href)
                out.append((text, url))
    # 排序：精确含「政务动态/要闻」优先
    out.sort(key=lambda x: 0 if re.search(r"政务动态|要闻", x[0]) else 1)
    return out[:6]


def count_items(list_html: str, base: str) -> int:
    urls = set()
    for m in re.finditer(r'href="([^"]+)"[^>]*>([^<]{6,60})<', list_html):
        href = m.group(1)
        text = m.group(2).strip()
        if len(text) < 8:
            continue
        u = urljoin(base, href)
        if re.search(r"(post_|content/|art/|t20\d{6}_\d+|/\d{8}/|\d{6,}_\d+\.|\.s?html$)", u):
            if "gov.cn" in u or u.startswith(base):
                if not u.rstrip("/").endswith(("index.html", "index.htm")):
                    urls.add(u)
    return len(urls)


def discover() -> list[dict]:
    results = []
    for name, city, level, base in CITIES:
        entry = {"name": name, "city": city, "level": level, "base_url": base, "status": "fail", "list_url": "", "column": "", "items": 0}
        try:
            home = curl(base)
            if not home:
                print(f"[{city}] 首页抓取失败", flush=True)
                results.append(entry)
                continue
            columns = find_column_links(home, base)
            ok = False
            for text, url in columns:
                try:
                    html = curl(url)
                except Exception:
                    continue
                n = count_items(html, base)
                print(f"  [{city}] 候选 {text} -> {url} : {n} 条", flush=True)
                if n >= 5:
                    entry.update(status="ok", list_url=url, column=text, items=n)
                    print(f"[{city}] ✓ {text} -> {url} ({n}条)", flush=True)
                    ok = True
                    break
            if not ok:
                print(f"[{city}] ✗ 栏目均不可用", flush=True)
        except Exception as e:
            print(f"[{city}] 异常: {e}", flush=True)
        results.append(entry)
    return results


if __name__ == "__main__":
    import pathlib

    out = discover()
    out_path = pathlib.Path(__file__).resolve().parent.parent.parent / "docs" / "discovered_sources.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    ok = sum(1 for r in out if r["status"] == "ok")
    print(f"\n完成: {ok}/{len(out)} 个源探测成功，结果已写入 {out_path}")
