"""周期报告（周报 / 月报）数据与渲染。

统计全部基于 SQLite 只读查询；AI 综述是可选增强——额度耗尽或接口异常时
自动降级为纯统计版，报告与推送照常产出，绝不因为 AI 失败而丢一份报告。
"""
from __future__ import annotations

import html
import json
import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DB = BASE_DIR / "data" / "news.db"
OUT_DIR = BASE_DIR / "data" / "reports"

log = logging.getLogger("period_report")

TYPE_LABEL = {
    "news": "新闻动态", "notice": "通知公告", "policy": "政策文件",
    "interpretation": "政策解读", "procurement": "招采公示",
}


def window(period: str, today: date | None = None) -> tuple[date, date, str, str]:
    """返回 (起始日, 结束日(不含), 中文标题, 文件名前缀)。默认统计上一个完整周期。"""
    today = today or date.today()
    if period == "weekly":
        end = today - timedelta(days=today.weekday())  # 本周一
        start = end - timedelta(days=7)
        iso = start.isocalendar()
        return start, end, f"{start:%Y-%m-%d} — {end - timedelta(days=1):%Y-%m-%d}（第 {iso.week} 周）", \
            f"weekly-{iso.year}-W{iso.week:02d}"
    end = today.replace(day=1)
    start = (end - timedelta(days=1)).replace(day=1)
    return start, end, f"{start:%Y 年 %m 月}", f"monthly-{start:%Y-%m}"


def collect(period: str, today: date | None = None) -> dict:
    start, end, label, stem = window(period, today)
    s, e = start.isoformat(), end.isoformat()
    prev_s = (start - (end - start)).isoformat()
    conn = sqlite3.connect(str(DB))
    try:
        def one(sql, args=()):
            return conn.execute(sql, args).fetchone()[0]

        # 周/月报口径为广东省 + 国家部委；港澳台地区（level='area'）与
        # 广东以外省级单位（level='province' 且 region_province 不是广东省）单独成体系，
        # 不进入本报告的篇数、类型、代表文章与待解读统计，避免口径混用。
        # 外省省级新闻 region_city 为空，混进来会被显示成「广东省」。
        total = one("SELECT COUNT(*) FROM news WHERE date(publish_time)>=? AND date(publish_time)<? "
                    "AND level!='area' AND (level!='province' OR region_province IN ('广东省',''))", (s, e))
        prev_total = one("SELECT COUNT(*) FROM news WHERE date(publish_time)>=? AND date(publish_time)<? "
                         "AND level!='area' AND (level!='province' OR region_province IN ('广东省',''))", (prev_s, s))
        interpreted = one("SELECT COUNT(*) FROM news WHERE date(publish_time)>=? AND date(publish_time)<? "
                          "AND status='interpreted' AND level!='area' AND (level!='province' OR region_province IN ('广东省',''))", (s, e))
        city_count = one("SELECT COUNT(DISTINCT region_city) FROM news WHERE date(publish_time)>=? "
                         "AND date(publish_time)<? AND region_city!=''", (s, e))
        # 国家级新闻 region_city 为空，不能混进「广东省」或地市榜
        national_count = one("SELECT COUNT(*) FROM news WHERE date(publish_time)>=? "
                             "AND date(publish_time)<? AND level='national'", (s, e))
        cities = [{"city": r[0] or "广东省", "n": r[1]} for r in conn.execute(
            "SELECT region_city, COUNT(*) n FROM news WHERE date(publish_time)>=? AND date(publish_time)<? "
            "AND region_city!='' GROUP BY region_city ORDER BY n DESC LIMIT 10", (s, e))]
        topics = [{"tag": r[0], "n": r[1]} for r in conn.execute(
            "SELECT t.name, COUNT(*) n FROM news_tags nt JOIN tags t ON t.id=nt.tag_id "
            "JOIN news n ON n.id=nt.news_id WHERE date(n.publish_time)>=? AND date(n.publish_time)<? "
            "AND n.level!='area' AND (n.level!='province' OR n.region_province IN ('广东省','')) "
            "GROUP BY t.name ORDER BY n DESC LIMIT 8", (s, e))]
        types = [{"label": TYPE_LABEL.get(r[0], r[0]), "n": r[1]} for r in conn.execute(
            "SELECT content_type, COUNT(*) n FROM news WHERE date(publish_time)>=? AND date(publish_time)<? "
            "AND level!='area' AND (level!='province' OR region_province IN ('广东省','')) GROUP BY content_type ORDER BY n DESC", (s, e))]
        # 政策类优先的代表文章；不足 8 条用最新新闻补齐
        picks = list(conn.execute(
            "SELECT title, COALESCE(NULLIF(region_org,''), NULLIF(region_city,''), '广东省'), "
            "substr(publish_time,1,10), url, content_type FROM news "
            "WHERE date(publish_time)>=? AND date(publish_time)<? AND level!='area' AND (level!='province' OR region_province IN ('广东省','')) "
            "AND content_type IN ('policy','notice','interpretation') "
            "ORDER BY publish_time DESC LIMIT 8", (s, e)))
        if len(picks) < 8:
            picks += list(conn.execute(
                "SELECT title, COALESCE(NULLIF(region_org,''), NULLIF(region_city,''), '广东省'), "
                "substr(publish_time,1,10), url, content_type FROM news "
                "WHERE date(publish_time)>=? AND date(publish_time)<? AND level!='area' AND (level!='province' OR region_province IN ('广东省','')) "
                "AND content_type NOT IN ('policy','notice','interpretation') "
                "ORDER BY publish_time DESC LIMIT ?", (s, e, 8 - len(picks))))
        # 与本周期相比的上升主题
        rising = []
        for t in topics:
            tag, n = t["tag"], t["n"]
            prev_n = one(
                "SELECT COUNT(*) FROM news_tags nt JOIN tags t ON t.id=nt.tag_id "
                "JOIN news n ON n.id=nt.news_id WHERE t.name=? AND date(n.publish_time)>=? AND date(n.publish_time)<? "
                "AND n.level!='area' AND (n.level!='province' OR n.region_province IN ('广东省',''))",
                (tag, prev_s, s))
            rising.append({"tag": tag, "n": n, "delta": n - prev_n})
        rising.sort(key=lambda x: x["delta"], reverse=True)
        rounds, inserted, failed = conn.execute(
            "SELECT COUNT(DISTINCT substr(started_at,1,13)), COALESCE(SUM(inserted),0), "
            "COALESCE(SUM(CASE WHEN status!='ok' THEN 1 ELSE 0 END),0) FROM fetch_logs "
            "WHERE date(started_at)>=? AND date(started_at)<?", (s, e)).fetchone()
        # 港澳台地区稿件 status='skipped'（不做 AI 解读），不能算作待解读积压
        pending = one("SELECT COUNT(*) FROM news WHERE status!='interpreted' AND level!='area' AND (level!='province' OR region_province IN ('广东省',''))")
        ai_err = one("SELECT COUNT(*) FROM news WHERE ai_error IS NOT NULL AND ai_error!=''")
        all_total = one("SELECT COUNT(*) FROM news")
        # 报告副标题的源规模从库里现查，避免每次扩源都要回来改硬编码数字
        source_count = one("SELECT COUNT(*) FROM sources WHERE enabled=1")
        source_cities = one("SELECT COUNT(DISTINCT region_city) FROM sources "
                            "WHERE enabled=1 AND region_city!=''")
        source_districts = one("SELECT COUNT(DISTINCT region_district) FROM sources "
                               "WHERE enabled=1 AND region_district!=''")
        source_orgs = one("SELECT COUNT(DISTINCT region_org) FROM sources "
                          "WHERE enabled=1 AND region_org!=''")
        source_areas = one("SELECT COUNT(DISTINCT region_area) FROM sources "
                           "WHERE enabled=1 AND region_area!=''")
        source_provinces = one("SELECT COUNT(DISTINCT region_province) FROM sources "
                               "WHERE enabled=1 AND region_province NOT IN ('','广东省','全国')")
    finally:
        conn.close()

    scope = f"{source_count} 源 / {source_cities} 地市"
    if source_districts:
        scope += f" / {source_districts} 区"
    if source_orgs:
        scope += f" / {source_orgs} 部委"
    if source_areas:
        scope += f" / {source_areas} 港澳台地区"
    if source_provinces:
        scope += f" / {source_provinces} 外省省级单位"

    days = (end - start).days
    return {
        "period": period,
        "label": label,
        "stem": stem,
        "scope": scope,
        "start": s, "end": (end - timedelta(days=1)).isoformat(),
        "total": total, "prev_total": prev_total,
        "delta": total - prev_total,
        "daily_avg": round(total / max(days, 1), 1),
        "interpreted": interpreted,
        "city_count": city_count,
        "national_count": national_count,
        "cities": cities, "topics": topics, "types": types,
        "picks": [{"title": r[0], "city": r[1] or "广东省", "date": r[2],
                   "url": r[3], "type": TYPE_LABEL.get(r[4], r[4])} for r in picks],
        "rising": rising[:6],
        "rounds": rounds, "inserted": inserted, "failed": failed,
        "pending": pending, "ai_err": ai_err, "all_total": all_total,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


def ai_summary(d: dict) -> str:
    """生成 200 字左右政策走向综述；任何失败都降级为空串。"""
    try:
        from . import config
        from .ai.client import chat

        if not config.ai_enabled():
            return ""
        facts = [
            f"周期：{d['label']}，发布 {d['total']} 篇（上期 {d['prev_total']} 篇，{'增' if d['delta'] >= 0 else '减'} {abs(d['delta'])} 篇），日均 {d['daily_avg']} 篇",
            "热门主题：" + "、".join(f"{t['tag']}({t['n']})" for t in d["topics"][:6]),
            "活跃地市：" + "、".join(f"{c['city']}({c['n']})" for c in d["cities"][:6]),
            f"国家部委新闻：{d.get('national_count', 0)} 篇（{d.get('scope', '')}）",
            "上升主题：" + "、".join(f"{r['tag']}(+{r['delta']})" for r in d["rising"][:4] if r["delta"] > 0),
            "代表文章：" + "；".join(p["title"][:36] for p in d["picks"][:8]),
        ]
        raw = chat([
            {"role": "system", "content": "你是广东省政务舆情分析师。只依据给定数据写周期政策走向综述，"
                                          "不得编造事实、数据或文件名称；语言克制、具体，不写套话。"},
            {"role": "user", "content": "请写 200 字左右的中文综述，分 2-3 点，指出本周期政策关注重点、"
                                        "地域分布特征和值得留意的上升信号。\n\n" + "\n".join(facts)},
        ], temperature=0.3, max_tokens=4000)
        return raw.strip()
    except Exception as ex:  # noqa: BLE001  402/429/超时一律降级
        log.warning("AI 周期综述不可用，降级为纯统计版: %s", str(ex)[:160])
        return ""


def build_markdown(d: dict, summary: str) -> str:
    lines = [
        f"# 广东政务新闻{'周报' if d['period'] == 'weekly' else '月报'} · {d['label']}",
        "",
        f"**发布量**：{d['total']} 篇（上期 {d['prev_total']}，{'↑' if d['delta'] >= 0 else '↓'}{abs(d['delta'])}）｜日均 {d['daily_avg']} 篇",
        f"**覆盖**：{d['city_count']} 个活跃地市｜国家部委 {d.get('national_count', 0)} 篇｜"
        f"{d.get('scope', '')}｜AI 解读 {d['interpreted']}/{d['total']} 篇",
        f"**抓取**：{d['rounds']} 轮{'（该周期早于平台上线）' if not d['rounds'] else ''}｜新增 {d['inserted']} 篇｜源级失败 {d['failed']} 次",
        "",
    ]
    if summary:
        lines += ["## 政策走向综述", "", summary, ""]
    else:
        lines += ["> AI 综述暂不可用，本期为纯统计版（不影响报告完整性）。", ""]
    lines += [
        "## 热门主题", "",
        "、".join(f"{t['tag']} {t['n']}" for t in d["topics"]) or "（本期无标签数据）", "",
        "## 上升信号", "",
        "、".join(f"{r['tag']} {r['delta']:+d}" for r in d["rising"]) or "（数据不足）", "",
        "## 活跃地市 Top 10", "",
        "、".join(f"{c['city']} {c['n']}" for c in d["cities"]) or "（无）", "",
        "## 代表文章", "",
    ]
    lines += [f"- [{p['city']}] {p['title']}（{p['date']} · {p['type']}）" for p in d["picks"]] or ["（无）"]
    lines += [
        "",
        "## 全库健康", "",
        f"库存 {d['all_total']} 篇｜待解读 {d['pending']}｜AI 错误 {d['ai_err']}",
        "",
        f"生成于 {d['generated_at'][:19].replace('T', ' ')}",
    ]
    return "\n".join(lines)


def build_html(d: dict, summary: str) -> str:
    e = lambda x: html.escape(str(x if x is not None else ""))  # noqa: E731
    name = "周报" if d["period"] == "weekly" else "月报"
    kpis = [
        (d["total"], "周期内发布", f"上期 {d['prev_total']}｜{d['delta']:+d}"),
        (d["daily_avg"], "日均篇数", f"覆盖 {d['city_count']} 个地市"),
        (d["interpreted"], "AI 已解读", f"{d['rounds']} 轮抓取"),
        (d["failed"], "源级失败次数", "下轮自动重试"),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><b>{e(v)}</b><span>{e(l)}</span><small>{e(sub)}</small></div>'
        for v, l, sub in kpis)
    bars = ""
    mx = max((t["n"] for t in d["topics"]), default=1)
    for t in d["topics"]:
        bars += (f'<div class="bar"><span class="bl">{e(t["tag"])}</span>'
                 f'<i style="width:{t["n"] / mx * 100:.1f}%"></i><b>{t["n"]}</b></div>')
    city_html = "".join(
        f'<span class="chip">{e(c["city"])} <b>{c["n"]}</b></span>' for c in d["cities"])
    rise_html = "".join(
        f'<span class="chip {"up" if r["delta"] > 0 else ""}">{e(r["tag"])} '
        f'<b>{r["delta"]:+d}</b></span>' for r in d["rising"])
    picks_html = "".join(
        f'<li><span class="meta">{e(p["date"])} · {e(p["city"])} · {e(p["type"])}</span>'
        f'<a href="{e(p["url"])}" target="_blank" rel="noopener">{e(p["title"])}</a></li>'
        for p in d["picks"])
    summary_html = (f'<div class="card"><h2>政策走向综述</h2><p>{e(summary).replace(chr(10), "<br>")}</p></div>'
                    if summary else
                    '<div class="card"><p class="muted">AI 综述暂不可用，本期为纯统计版，数据完整。</p></div>')
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>广东政务新闻{name} · {e(d['label'])}</title>
<style>
:root{{--brand:#C0181F;--text:#1F2329;--text2:#51565D;--text3:#8F959E;--border:#E5E6EB;--bg:#F7F8FA}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--text);
font:14px/1.7 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif}}
.wrap{{max-width:860px;margin:0 auto;padding:24px 16px 60px}}
header{{border-bottom:3px solid var(--brand);padding-bottom:14px;margin-bottom:20px}}
h1{{font-size:21px;margin:0 0 6px;font-weight:600}} .sub{{color:var(--text3);font-size:12.5px}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:18px}}
.kpi{{background:#fff;border:1px solid var(--border);border-radius:10px;padding:14px}}
.kpi b{{display:block;font-size:24px;line-height:1.3}} .kpi span{{font-size:12px;color:var(--text2)}}
.kpi small{{display:block;font-size:11px;color:var(--text3);margin-top:4px}}
.card{{background:#fff;border:1px solid var(--border);border-radius:10px;padding:18px 20px;margin-bottom:14px}}
.card h2{{font-size:15px;margin:0 0 12px;font-weight:600;padding-left:10px;border-left:3px solid var(--brand)}}
.card p{{margin:0;color:var(--text2)}} .muted{{color:var(--text3)}}
.bar{{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:12.5px}}
.bl{{width:76px;flex:none;color:var(--text2)}} .bar i{{display:block;height:10px;background:var(--brand);
border-radius:5px;min-width:3px;opacity:.85}} .bar b{{font-variant-numeric:tabular-nums;font-size:12px}}
.chip{{display:inline-block;background:#F5F6F8;border:1px solid var(--border);border-radius:14px;
padding:4px 11px;margin:0 7px 7px 0;font-size:12.5px;color:var(--text2)}}
.chip.up{{background:#FDEEEF;border-color:#F3C9CB;color:var(--brand)}} .chip b{{font-variant-numeric:tabular-nums}}
ul{{list-style:none;padding:0;margin:0}} li{{padding:9px 0;border-bottom:1px solid #F0F1F4}}
li:last-child{{border-bottom:0}} li a{{color:var(--text);text-decoration:none;display:block}}
li a:hover{{color:var(--brand)}} .meta{{font-size:11.5px;color:var(--text3);display:block}}
footer{{color:var(--text3);font-size:11.5px;text-align:center;margin-top:22px}}
@media(max-width:600px){{.kpis{{grid-template-columns:repeat(2,1fr)}}.wrap{{padding:16px 12px 40px}}}}
</style></head><body><div class="wrap">
<header><h1>广东政务新闻{name}</h1><div class="sub">{e(d['label'])} · {e(d.get('scope', ''))} · 生成于 {e(d['generated_at'][:16].replace('T',' '))}</div></header>
<div class="kpis">{kpi_html}</div>
{summary_html}
<div class="card"><h2>热门主题</h2>{bars or '<p class="muted">本期无标签数据</p>'}</div>
<div class="card"><h2>上升信号（对比上一周期）</h2>{rise_html or '<p class="muted">数据不足</p>'}</div>
<div class="card"><h2>活跃地市 Top 10</h2>{city_html or '<p class="muted">无</p>'}</div>
<div class="card"><h2>代表文章</h2><ul>{picks_html or '<li class="muted">无</li>'}</ul></div>
<div class="card"><h2>全库健康</h2><p>库存 {d['all_total']} 篇｜待解读 {d['pending']}｜AI 错误 {d['ai_err']}｜本期源级失败 {d['failed']} 次（下轮自动重试）</p></div>
<footer>广东政务新闻聚合平台 · 自动生成</footer></div></body></html>"""


def summary_markdown(d: dict) -> str:
    """飞书卡片里的周期报告摘要（一屏能看完）。"""
    lines = [
        f"**周期**：{d['label']}",
        f"**发布量**：{d['total']} 篇（上期 {d['prev_total']}，{d['delta']:+d}）｜日均 {d['daily_avg']} 篇",
        f"**覆盖**：{d['city_count']} 个地市｜AI 解读 {d['interpreted']}/{d['total']} 篇｜抓取 {d['rounds']} 轮",
        "",
    ]
    if d.get("summary"):
        s = d["summary"].strip().replace("\n", " ")
        lines += ["**政策走向综述**", s[:420] + ("…" if len(s) > 420 else ""), ""]
    else:
        lines += ["> AI 综述暂不可用，本期为纯统计版。", ""]
    lines += [
        "**热门主题**：" + ("、".join(f"{t['tag']} {t['n']}" for t in d["topics"][:6]) or "无"),
        "**上升信号**：" + ("、".join(f"{r['tag']} {r['delta']:+d}" for r in d["rising"][:4]) or "数据不足"),
        "**活跃地市**：" + ("、".join(f"{c['city']} {c['n']}" for c in d["cities"][:5]) or "无"),
        "",
        f"全库 {d['all_total']} 篇｜待解读 {d['pending']}｜AI 错误 {d['ai_err']}｜本期源级失败 {d['failed']} 次",
        f"完整报告：`data/reports/{d['stem']}.html`",
    ]
    return "\n".join(lines)


def generate(period: str, today: date | None = None) -> dict:
    """生成 HTML + Markdown，返回数据字典与文件路径。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    d = collect(period, today)
    summary = ai_summary(d)
    hp = OUT_DIR / (d["stem"] + ".html")
    mp = OUT_DIR / (d["stem"] + ".md")
    hp.write_text(build_html(d, summary), encoding="utf-8")
    mp.write_text(build_markdown(d, summary), encoding="utf-8")
    d["summary"] = summary
    d["html_path"], d["md_path"] = str(hp), str(mp)
    return d
