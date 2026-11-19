"""探测四直辖市 86 个区县门户的政务要闻列表页（2026-11-20）。

域名来源：
  * 上海/天津：市政府门户导航页（scripts/extract_municipal_nav.py 提取）；
  * 北京：首都之窗各区政府入口（网络检索，bj*.gov.cn）；
  * 重庆：市民政局各区县官网公示表 + 市政府信息公开指南（真实区县独立域名）。

抓首页 -> 找「要闻/政务动态」栏目 -> 验证列表页 >=5 条新闻链接。
首页做 http/https 双协议探测，记录实际可达协议。结果写入
data/municipal_candidates.json。
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urljoin, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE

# (省, 显示名, region_city, region_district, level, 首页候选)
SITES = []
# ---- 北京 16 区（首都之窗各区政府入口）----
for d, host in [
    ("东城区", "www.bjdch.gov.cn"), ("西城区", "www.bjxch.gov.cn"),
    ("朝阳区", "www.bjchy.gov.cn"), ("海淀区", "www.bjhd.gov.cn"),
    ("丰台区", "www.bjft.gov.cn"), ("石景山区", "www.bjsjs.gov.cn"),
    ("门头沟区", "www.bjmtg.gov.cn"), ("房山区", "www.bjfsh.gov.cn"),
    ("通州区", "www.bjtzh.gov.cn"), ("顺义区", "www.bjshy.gov.cn"),
    ("大兴区", "www.bjdx.gov.cn"), ("昌平区", "www.bjchp.gov.cn"),
    ("平谷区", "www.bjpg.gov.cn"), ("怀柔区", "www.bjhr.gov.cn"),
    ("密云区", "www.bjmy.gov.cn"), ("延庆区", "www.bjyq.gov.cn"),
]:
    SITES.append(("北京市", f"北京市{d}人民政府", "市辖区", d, "district", f"https://{host}/"))
# ---- 上海 16 区（上海市政府门户导航）----
for d, host in [
    ("黄浦区", "www.shhuangpu.gov.cn"), ("徐汇区", "www.xuhui.gov.cn"),
    ("长宁区", "www.shcn.gov.cn"), ("静安区", "www.jingan.gov.cn"),
    ("普陀区", "www.shpt.gov.cn"), ("虹口区", "www.shhk.gov.cn"),
    ("杨浦区", "www.shyp.gov.cn"), ("闵行区", "www.shmh.gov.cn"),
    ("宝山区", "www.shbsq.gov.cn"), ("嘉定区", "www.jiading.gov.cn"),
    ("浦东新区", "www.pudong.gov.cn"), ("金山区", "www.jinshan.gov.cn"),
    ("松江区", "www.songjiang.gov.cn"), ("青浦区", "www.shqp.gov.cn"),
    ("奉贤区", "www.fengxian.gov.cn"), ("崇明区", "www.shcm.gov.cn"),
]:
    SITES.append(("上海市", f"上海市{d}人民政府", "市辖区", d, "district", f"https://{host}/"))
# ---- 天津 16 区（天津政务网网站地图）----
for d, host in [
    ("滨海新区", "www.tjbh.gov.cn"), ("和平区", "www.tjhp.gov.cn"),
    ("河东区", "www.tjhd.gov.cn"), ("河西区", "www.tjhx.gov.cn"),
    ("南开区", "www.tjnk.gov.cn"), ("河北区", "www.tjhb.gov.cn"),
    ("红桥区", "www.tjhq.gov.cn"), ("东丽区", "www.tjdl.gov.cn"),
    ("西青区", "www.tjxq.gov.cn"), ("津南区", "www.tjjn.gov.cn"),
    ("北辰区", "www.tjbc.gov.cn"), ("武清区", "www.tjwq.gov.cn"),
    ("宝坻区", "www.tjbd.gov.cn"), ("宁河区", "www.tjnh.gov.cn"),
    ("静海区", "www.tjjh.gov.cn"), ("蓟州区", "www.tjjz.gov.cn"),
]:
    SITES.append(("天津市", f"天津市{d}人民政府", "市辖区", d, "district", f"https://{host}/"))
# ---- 重庆 38 区县（民政局公示表 + 市政府信息公开指南；江北/渝北待验证）----
_CHONGQING = [
    ("万州区", "www.wz.gov.cn"), ("黔江区", "www.qianjiang.gov.cn"),
    ("涪陵区", "www.fl.gov.cn"), ("渝中区", "www.cqyz.gov.cn"),
    ("大渡口区", "www.ddk.gov.cn"), ("沙坪坝区", "www.cqspb.gov.cn"),
    ("九龙坡区", "cqjlp.gov.cn"), ("南岸区", "www.cqna.gov.cn"),
    ("北碚区", "www.beibei.gov.cn"), ("江北区", "www.cqjb.gov.cn"),
    ("渝北区", "www.cqyb.gov.cn"), ("巴南区", "www.cqbn.gov.cn"),
    ("长寿区", "www.cqcs.gov.cn"), ("江津区", "www.jiangjin.gov.cn"),
    ("合川区", "www.hc.gov.cn"), ("永川区", "www.cqyc.gov.cn"),
    ("南川区", "www.cqnc.gov.cn"), ("綦江区", "www.cqqj.gov.cn"),
    ("大足区", "www.dazu.gov.cn"), ("璧山区", "www.bishan.gov.cn"),
    ("铜梁区", "www.cqstl.gov.cn"), ("潼南区", "www.cqtn.gov.cn"),
    ("荣昌区", "www.rongchang.gov.cn"), ("开州区", "www.cqkz.gov.cn"),
    ("梁平区", "www.cqlp.gov.cn"), ("武隆区", "cqwl.gov.cn"),
    ("城口县", "www.cqck.gov.cn"), ("丰都县", "www.cqfd.gov.cn"),
    ("垫江县", "www.cqsdj.gov.cn"), ("忠县", "www.zhongxian.gov.cn"),
    ("云阳县", "www.yunyang.gov.cn"), ("奉节县", "www.cqfj.gov.cn"),
    ("巫山县", "www.cqws.gov.cn"), ("巫溪县", "www.cqwx.gov.cn"),
    ("石柱土家族自治县", "cqszx.gov.cn"), ("秀山土家族苗族自治县", "www.cqxs.gov.cn"),
    ("酉阳土家族苗族自治县", "youyang.gov.cn"), ("彭水苗族土家族自治县", "www.psx.gov.cn"),
]
for d, host in _CHONGQING:
    city = "县" if d.endswith("县") else "市辖区"
    SITES.append(("重庆市", f"重庆市{d}人民政府", city, d, "district", f"https://{host}/"))

COL_PAT = re.compile(r"要闻动态|政务动态|政务要闻|今日[^\s<]{0,6}|要闻|新闻动态|工作动态|最新动态|本地新闻|新闻|头条|动态")
NEWS_URL = re.compile(r"(t20\d{6}_\d+|/20\d{6}/|/20\d\d-\d\d/|\d{6,}_\d+\.s?html|content_\d+|/content/|/art/\d+|post_\d+|\.s?html?$)")


def curl(url: str, timeout: int = 18) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as resp:
        data = resp.read()
    for enc in ("utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="ignore")


def curl_auto(url: str) -> tuple[str, str]:
    """返回 (实际可用 url, html)；先试给定协议，失败换另一种。"""
    p = urlparse(url)
    alts = [url]
    alt = ("http://" if p.scheme == "https" else "https://") + p.netloc + (p.path or "/")
    alts.append(alt)
    last = None
    for u in alts:
        try:
            return u, curl(u)
        except Exception as e:
            last = e
    raise last


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
    # 优先精确栏目名
    out.sort(key=lambda x: (0 if re.search(r"要闻动态|政务动态|政务要闻|新闻动态|要闻", x[0]) else 1))
    return out[:10]


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


def probe(site: tuple) -> dict:
    prov, name, city, district, level, home0 = site
    e = {"province": prov, "name": name, "city": city, "district": district,
         "level": level, "home": home0, "status": "fail", "home_real": "",
         "list_url": "", "column": "", "items": 0, "note": ""}
    try:
        home, html = curl_auto(home0)
        e["home_real"] = home
        if len(html) < 1500:
            e["note"] = f"首页异常/过短({len(html)})"
            return e
        cols = find_columns(html, home)
        for text, url in cols:
            try:
                ch = curl(url)
            except Exception:
                continue
            n = count_items(ch, url)
            if n >= 5:
                e.update(status="ok", list_url=url, column=text, items=n,
                         note=f"栏目「{text}」解析 {n} 条")
                return e
        e["note"] = f"候选栏目{len(cols)}个均<5条"
    except Exception as ex:
        e["note"] = f"异常 {type(ex).__name__}: {str(ex)[:80]}"
    return e


def main():
    results = []
    with ThreadPoolExecutor(max_workers=10) as pool:
        for e in pool.map(probe, SITES):
            results.append(e)
            flag = "OK " if e["status"] == "ok" else "   "
            print(f"{flag}{e['province']} {e['district']:<8} {e['items']:>3}条 "
                  f"{e['note'][:46]}", flush=True)
    out = ROOT / "data" / "municipal_candidates.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    ok = sum(1 for r in results if r["status"] == "ok")
    print(f"\n结果: {ok}/{len(results)} 可用 -> {out}", flush=True)


if __name__ == "__main__":
    main()
