"""每轮抓取执行报告生成器。

用法：
    .venv/bin/python scripts/execution_report.py                 # 最近一轮
    .venv/bin/python scripts/execution_report.py --run "2026-11-07 06:00"
    .venv/bin/python scripts/execution_report.py --all          # 补生成全部历史轮次

产出（默认写到 data/reports/）：
    2026-11-07_0600.html    独立可分发的完整报告（内嵌样式，不依赖服务）
    2026-11-07_0600.md      纯文本摘要，便于贴到微信/文档

设计原则：一屏看完结论 —— 总览 KPI → 本轮新增 → 异常与处置 → 源级明细 → 趋势。
异常必须带「是否需要处理」，避免用户看到红字误以为系统坏了。
"""
import argparse
import html
import json
import os
import sqlite3
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

DB = os.path.join(ROOT, "data", "news.db")
OUT_DIR = os.path.join(ROOT, "data", "reports")

BRAND = "#C0181F"
OK = "#1D9E75"
WARN = "#BA7517"
DANGER = "#A32D2D"


def e(s) -> str:
    return html.escape(str(s if s is not None else ""))


def slot_label(hour: int) -> str:
    if 5 <= hour < 9:
        return "早间轮"
    if 9 <= hour < 16:
        return "午间轮"
    if 16 <= hour < 23:
        return "晚间轮"
    return "手动/补跑"


def rounds(conn):
    """按「日期+小时」把 fetch_logs 分轮，返回 [(key, 起始, 结束)]，最新在前。"""
    rows = conn.execute(
        "SELECT DISTINCT substr(started_at,1,13) AS k FROM fetch_logs ORDER BY k DESC"
    ).fetchall()
    out = []
    for (k,) in rows:
        lo, hi = k + ":00", k + ":59"
        out.append((k, lo, hi))
    return out


def load_round(conn, key, lo, hi):
    logs = conn.execute(
        """SELECT f.id, f.started_at, f.finished_at, f.status, f.found, f.inserted,
                  f.duplicated, f.error, s.name, s.region_city
           FROM fetch_logs f LEFT JOIN sources s ON s.id = f.source_id
           WHERE f.started_at >= ? AND f.started_at <= ? ORDER BY f.id""",
        (lo, hi),
    ).fetchall()
    if not logs:
        return None
    ids = [r[0] for r in logs]
    started = min(r[1] for r in logs)
    finished = max(r[2] for r in logs if r[2]) or started
    try:
        secs = (datetime.fromisoformat(finished) - datetime.fromisoformat(started)).total_seconds()
    except ValueError:
        secs = 0
    # 本轮新增文章：fetch_time 落在轮次窗口内（留 2 分钟余量给收尾写入）
    lo_dt = datetime.fromisoformat(started)
    hi_dt = datetime.fromisoformat(finished)
    from datetime import timedelta

    news = conn.execute(
        """SELECT n.title, n.region_city, n.publish_time, n.status, n.ai_error, s.name
           FROM news n LEFT JOIN sources s ON s.id = n.source_id
           WHERE n.fetch_time >= ? AND n.fetch_time <= ?
           ORDER BY n.publish_time DESC, n.id""",
        (lo_dt.strftime("%Y-%m-%d %H:%M:%S.%f"),
         (hi_dt + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M:%S.%f")),
    ).fetchall()
    total = conn.execute("SELECT COUNT(*) FROM news").fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM news WHERE status!='interpreted'").fetchone()[0]
    ai_err = conn.execute(
        "SELECT COUNT(*) FROM news WHERE ai_error IS NOT NULL AND ai_error!=''"
    ).fetchone()[0]
    interpreted = conn.execute(
        "SELECT COUNT(*) FROM news WHERE status='interpreted'"
    ).fetchone()[0]
    agg = {
        "sources": len(logs),
        "ok": sum(1 for r in logs if r[3] == "ok"),
        "failed": sum(1 for r in logs if r[3] != "ok"),
        "found": sum(r[4] or 0 for r in logs),
        "inserted": sum(r[5] or 0 for r in logs),
        "duplicated": sum(r[6] or 0 for r in logs),
        "noted": sum(1 for r in logs if r[7]),
    }
    return {
        "key": key, "logs": logs, "ids": ids, "started": started, "finished": finished,
        "secs": secs, "news": news, "agg": agg, "total": total, "pending": pending,
        "ai_err": ai_err, "interpreted": interpreted,
    }


def cron_text():
    try:
        from app import config

        return "、".join(f"{h:02d}:{config.CRON_MINUTE:02d}" for h in config.CRON_HOURS)
    except Exception:
        return "12:00、21:00"


def next_run_text():
    try:
        from app import config

        hours = config.CRON_HOURS
        now = datetime.now()
        for h in hours:
            if now.hour < h or (now.hour == h and now.minute < config.CRON_MINUTE):
                return f"今日 {h:02d}:{config.CRON_MINUTE:02d}"
        return f"次日 {hours[0]:02d}:{config.CRON_MINUTE:02d}"
    except Exception:
        return "12:00 / 21:00"


def build_markdown(d, prev_inserted, trend):
    a = d["agg"]
    hour = int(d["key"][11:13])
    title = f"{d['key'][:10]} {hour:02d}:00 · {slot_label(hour)}"
    lines = [
        f"# 政务新闻聚合平台 · 抓取执行报告",
        "",
        f"**轮次**：{title}　**状态**：{'全部成功' if a['failed'] == 0 else '存在失败源'}  ",
        f"**执行时间**：{d['started'][11:19]} → {d['finished'][11:19]}（{d['secs']:.0f} 秒）",
        "",
        "## 一、总览",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 执行源 | {a['sources']}（成功 {a['ok']} / 失败 {a['failed']}） |",
        f"| 扫描条目 | {a['found']} |",
        f"| 新增入库 | {a['inserted']} |",
        f"| 判重跳过 | {a['duplicated']} |",
        f"| AI 解读 | 本轮新增 {len(d['news'])} 篇，全库待解读 {d['pending']} |",
    ]
    if prev_inserted is not None:
        prev_key, p_num = prev_inserted
        diff = a["inserted"] - p_num
        lines.append(f"| 对比上一轮（{prev_key[5:10]} {prev_key[11:13]}点） | {p_num} → {a['inserted']}（{'+' if diff >= 0 else ''}{diff}） |")
    lines += ["", "## 二、本轮新增", ""]
    if d["news"]:
        for t, city, pub, status, err, src in d["news"]:
            pub_s = str(pub)[:10] if pub else "日期未知"
            lines.append(f"- **[{city or '—'}]** {t}　`{pub_s}`　{e(src)}　`{e(status)}`")
    else:
        lines.append("- 本轮无新增（各源列表内容均已入库，属正常）")
    lines += ["", "## 三、异常与处置", ""]
    notes = [(r[8], r[7]) for r in d["logs"] if r[7]]
    if notes:
        for name, note in notes:
            lines.append(f"- **{e(name)}**：{e(note)} → 单篇级别，下轮自动重试补回，无需处理")
    else:
        lines.append("- 无异常")
    failed = [r for r in d["logs"] if r[3] != "ok"]
    for r in failed:
        lines.append(f"- **{e(r[8])} 源级失败**：{e(r[7] or '未知错误')} → 需关注")
    lines += ["", "## 四、源级明细", "", "| 源 | 地市 | 扫描 | 新增 | 重复 | 状态 | 备注 |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for r in d["logs"]:
        lines.append(f"| {e(r[8])} | {e(r[9])} | {r[4] or 0} | {r[5] or 0} | {r[6] or 0} | {e(r[3])} | {e(r[7] or '')} |")
    lines += ["", "## 五、库状态与下次执行", "",
              f"- 全库 {d['total']} 篇｜已解读 {d['interpreted']}｜待解读 {d['pending']}｜AI 错误 {d['ai_err']}",
              f"- 下次执行：{next_run_text()}", ""]
    return "\n".join(lines)


CSS = """
*{box-sizing:border-box}body{margin:0;background:#F7F7F5;color:#2C2C2A;
font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;
font-size:13px;line-height:1.6}
.wrap{max-width:960px;margin:0 auto;padding:28px 24px 48px}
.hd{border-top:4px solid #C0181F;background:#fff;border-radius:0 0 12px 12px;
padding:20px 24px;border:1px solid #E8E6E0;border-top:4px solid #C0181F}
.hd h1{font-size:20px;font-weight:500;margin:0 0 6px}
.hd .sub{color:#5F5E5A;font-size:13px}
.pill{display:inline-block;padding:2px 10px;border-radius:999px;font-size:12px;margin-left:8px}
.pill.ok{background:#E1F5EE;color:#0F6E56}.pill.bad{background:#FCEBEB;color:#A32D2D}
.sec{background:#fff;border:1px solid #E8E6E0;border-radius:12px;padding:18px 22px;margin-top:16px}
.sec h2{font-size:14px;font-weight:500;margin:0 0 14px;padding-left:9px;border-left:3px solid #C0181F}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
.kpi{background:#FAFAF8;border:1px solid #EDEBE5;border-radius:8px;padding:12px 14px}
.kpi .l{color:#5F5E5A;font-size:12px}.kpi .v{font-size:22px;font-weight:500;margin-top:2px}
.kpi .v small{font-size:12px;color:#888780;font-weight:400}
table{width:100%;border-collapse:collapse;font-size:12px}
th{text-align:left;color:#5F5E5A;font-weight:400;background:#FAFAF8;padding:8px 10px;
border-bottom:1px solid #E8E6E0;white-space:nowrap}
td{padding:8px 10px;border-bottom:1px solid #F0EEE8;vertical-align:top}
tr:last-child td{border-bottom:none}
.tag{display:inline-block;padding:1px 7px;border-radius:4px;font-size:11px}
.tag.ok{background:#E1F5EE;color:#0F6E56}.tag.warn{background:#FAEEDA;color:#854F0B}
.tag.bad{background:#FCEBEB;color:#A32D2D}
.note{background:#FFFBF2;border:1px solid #F0DFC0;border-radius:8px;padding:12px 14px;margin-bottom:8px}
.note b{font-weight:500}.note .why{color:#5F5E5A;font-size:12px;margin-top:3px}
.clean{color:#0F6E56;font-size:13px}
.trend{display:flex;align-items:flex-end;gap:10px;height:76px;margin-top:6px}
.tbar{flex:1;display:flex;flex-direction:column;align-items:center;gap:4px}
.tbar .b{width:100%;background:#F2C9CB;border-radius:3px 3px 0 0;min-height:3px}
.tbar.cur .b{background:#C0181F}
.tbar .c{font-size:11px;color:#5F5E5A;white-space:nowrap}
.ft{color:#888780;font-size:12px;margin-top:18px;text-align:center}
@media(max-width:680px){.kpis{grid-template-columns:repeat(2,1fr)}.wrap{padding:14px}}
"""


def build_html(d, prev_inserted, trend):
    a = d["agg"]
    hour = int(d["key"][11:13])
    title = f"{d['key'][:10]} {hour:02d}:00 · {slot_label(hour)}"
    badge = (f'<span class="pill ok">全部成功</span>' if a["failed"] == 0
             else f'<span class="pill bad">{a["failed"]} 个源失败</span>')
    if a["noted"]:
        badge += f'<span class="pill warn" style="background:#FAEEDA;color:#854F0B">{a["noted"]} 个源有提示</span>'

    kpis = [
        ("执行源", f'{a["sources"]}', f'成功 {a["ok"]} / 失败 {a["failed"]}'),
        ("扫描条目", f'{a["found"]}', "列表页条目"),
        ("新增入库", f'{a["inserted"]}', "通过三层去重"),
        ("判重跳过", f'{a["duplicated"]}', "已在库"),
        ("本轮耗时", f'{d["secs"]:.0f}<small> 秒</small>', f'{d["started"][11:19]} → {d["finished"][11:19]}'),
        ("AI 解读", f'{sum(1 for n in d["news"] if n[3] == "interpreted")}/{len(d["news"])}', "本轮新增已解读"),
        ("全库总量", f'{d["total"]}', "篇"),
        ("待解读", f'{d["pending"]}', f'AI 错误 {d["ai_err"]}'),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="l">{e(l)}</div><div class="v">{v}</div>'
        f'<div class="l">{e(sub)}</div></div>' for l, v, sub in kpis
    )

    if d["news"]:
        rows = "".join(
            f"<tr><td>{e(city or '—')}</td><td>{e(t)}</td><td>{e(str(pub)[:10] if pub else '—')}</td>"
            f"<td>{e(src or '—')}</td><td><span class=\"tag {'ok' if st == 'interpreted' else 'warn'}\">{e(st)}</span></td></tr>"
            for t, city, pub, st, err, src in d["news"]
        )
        news_html = (f'<table><thead><tr><th>地市</th><th>标题</th><th>发布日期</th>'
                     f'<th>来源栏目</th><th>解读</th></tr></thead><tbody>{rows}</tbody></table>')
    else:
        news_html = '<div class="clean">本轮无新增：各源列表内容均已入库，属于正常情况。</div>'

    cmp_html = ""
    if prev_inserted is not None:
        prev_key, p_num = prev_inserted
        diff = a["inserted"] - p_num
        cmp_html = (f'<div style="font-size:12px;color:#5F5E5A;margin-top:10px">对比上一轮'
                    f'（{e(prev_key[5:10])} {e(prev_key[11:13])}点）新增：'
                    f'{p_num} → <b style="font-weight:500">{a["inserted"]}</b>'
                    f'（{"+" if diff >= 0 else ""}{diff}）</div>')

    notes = [(r[8], r[7]) for r in d["logs"] if r[7]]
    if notes or a["failed"]:
        parts = []
        for name, note in notes:
            parts.append(f'<div class="note"><b>{e(name)}</b>：{e(note)}'
                         f'<div class="why">影响：单篇级别，不影响该源状态；下轮自动重试补回，无需人工处理。</div></div>')
        for r in d["logs"]:
            if r[3] != "ok":
                parts.append(f'<div class="note" style="background:#FDF3F3;border-color:#F0CACA">'
                             f'<b>{e(r[8])} 源级失败</b>：{e(r[7] or "未知错误")}'
                             f'<div class="why">影响：该源本轮无数据，需关注；下轮会重试。</div></div>')
        warn_html = "".join(parts)
    else:
        warn_html = f'<div class="clean">本轮无异常，{a["sources"]} 个源全部正常返回。</div>'

    log_rows = "".join(
        f'<tr><td>{e(r[8])}</td><td>{e(r[9])}</td><td>{r[4] or 0}</td><td>{r[5] or 0}</td>'
        f'<td>{r[6] or 0}</td><td><span class="tag {"ok" if r[3] == "ok" else "bad"}">{e(r[3])}</span></td>'
        f'<td style="color:{"#854F0B" if r[7] else "#888780"}">{e(r[7] or "—")}</td></tr>'
        for r in d["logs"]
    )

    mx = max((n for _, n in trend), default=1) or 1
    bars = ""
    for label, n in trend:
        cur = label == d["key"]
        h = max(3, int(n / mx * 52))
        bars += (f'<div class="tbar {"cur" if cur else ""}"><div class="c">{n}</div>'
                 f'<div class="b" style="height:{h}px"></div>'
                 f'<div class="c">{e(label[5:10])} {e(label[11:13])}点</div></div>')

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>抓取执行报告 {e(title)}</title><style>{CSS}</style></head><body><div class="wrap">
<div class="hd"><h1>政务新闻聚合平台 · 抓取执行报告 {badge}</h1>
<div class="sub">轮次 {e(title)}　·　执行 {e(d['started'][11:19])} → {e(d['finished'][11:19])}（{d['secs']:.0f} 秒）　·　生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}</div></div>

<div class="sec"><h2>一、总览</h2><div class="kpis">{kpi_html}</div>{cmp_html}</div>
<div class="sec"><h2>二、本轮新增内容</h2>{news_html}</div>
<div class="sec"><h2>三、异常与处置</h2>{warn_html}</div>
<div class="sec"><h2>四、源级明细（{a['sources']} 个源）</h2>
<table><thead><tr><th>源</th><th>地市</th><th>扫描</th><th>新增</th><th>重复</th><th>状态</th><th>备注</th></tr></thead>
<tbody>{log_rows}</tbody></table></div>
<div class="sec"><h2>五、近几轮新增趋势</h2><div class="trend">{bars}</div>
<div style="font-size:12px;color:#888780;margin-top:10px">深色为当前轮次；建库初期的批量补齐会造成峰值，稳态后看相对变化即可。</div></div>
<div class="sec"><h2>六、库状态与下次执行</h2>
<div>全库 <b style="font-weight:500">{d['total']}</b> 篇　·　已解读 <b style="font-weight:500">{d['interpreted']}</b>　·　待解读 <b style="font-weight:500">{d['pending']}</b>　·　AI 错误 <b style="font-weight:500">{d['ai_err']}</b></div>
<div style="margin-top:6px;color:#5F5E5A">下次执行：<b style="font-weight:500">{e(next_run_text())}</b>（每日 {e(cron_text())}）</div></div>
<div class="ft">本报告由平台自动生成 · 数据来自本地 SQLite · 异常项均标注影响与处置建议</div>
</div></body></html>"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help='轮次，如 "2026-11-07 06:00"；默认最近一轮')
    ap.add_argument("--all", action="store_true", help="补生成全部历史轮次")
    ap.add_argument("--notify", action="store_true", help="生成后按 .env 的 NOTIFY_CHANNEL 推送")
    args = ap.parse_args()
    conn = sqlite3.connect(DB)
    all_rs = rounds(conn)
    if args.run:
        key = args.run[:13].replace(" ", "-")
        targets = [r for r in all_rs if r[0] == key] or all_rs[:1]
    elif args.all:
        targets = all_rs
    else:
        targets = all_rs[:1]
    os.makedirs(OUT_DIR, exist_ok=True)
    index = {r[0]: i for i, r in enumerate(all_rs)}
    for key, lo, hi in targets:
        i = index[key]
        d = load_round(conn, key, lo, hi)
        if not d:
            continue
        prev = None
        if i + 1 < len(all_rs):
            pd = load_round(conn, *all_rs[i + 1])
            prev = (all_rs[i + 1][0], pd["agg"]["inserted"]) if pd else None
        trend = []
        for k2, lo2, hi2 in reversed(all_rs[max(0, i - 5):i + 1]):
            row = conn.execute(
                "SELECT SUM(inserted) FROM fetch_logs WHERE started_at >= ? AND started_at <= ?",
                (lo2, hi2),
            ).fetchone()
            trend.append((k2, row[0] or 0))
        stem = key[:10] + "_" + key[11:13] + "00"
        hp = os.path.join(OUT_DIR, stem + ".html")
        mp = os.path.join(OUT_DIR, stem + ".md")
        with open(hp, "w", encoding="utf-8") as f:
            f.write(build_html(d, prev, trend))
        with open(mp, "w", encoding="utf-8") as f:
            f.write(build_markdown(d, prev, trend))
        print(f"已生成 {stem}: 新增 {d['agg']['inserted']} / 扫描 {d['agg']['found']} / 源 {d['agg']['sources']}")
        print(f"  {hp}")
        print(f"  {mp}")
        if args.notify:
            from app.notifier import push_report

            res = push_report(d, hp, mp)
            print("  推送:", json.dumps(res, ensure_ascii=False))
    conn.close()


if __name__ == "__main__":
    main()
