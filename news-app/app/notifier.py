"""执行报告与告警推送。

服务端无人值守：每轮定时任务生成报告后直接 HTTP POST 到 webhook，
不依赖 AI 会话、不需要常驻登录态。

支持渠道（在 .env 配 NOTIFY_CHANNEL）：
    feishu      飞书自定义群机器人（推荐：免费、即时、手机能收）
    wecom       企业微信群机器人
    serverchan  Server酱 Turbo（微信服务号收消息）
    pushplus    PushPlus（微信服务号收消息）
    custom      任意接收 JSON 的自定义 webhook

配置：
    NOTIFY_WEBHOOK   feishu / wecom / custom 的机器人地址
    NOTIFY_TOKEN     serverchan / pushplus 的 token
    NOTIFY_SECRET    飞书机器人开了「签名校验」时填（可选）

推送失败只记日志，不抛出——绝不能让通知失败拖垮抓取主流程。
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# override=True：定时任务以子进程方式运行，会继承服务进程启动时的旧环境变量
# （例如把 NOTIFY_CHANNEL 从 off 改成 feishu 但没重启服务）。以 .env 文件为准，
# 保证改配置立即生效，且不会出现「报告生成了却静默没推送」。
load_dotenv(BASE_DIR / ".env", override=True)

log = logging.getLogger("notifier")

CHANNELS = {"off", "feishu", "wecom", "serverchan", "pushplus", "custom"}
TIMEOUT = 12


def _post(url: str, payload: dict, *, form: bool = False, headers: dict | None = None):
    if form:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        content_type = "application/x-www-form-urlencoded"
    else:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        content_type = "application/json; charset=utf-8"
    req = urllib.request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": content_type, **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        return resp.status, resp.read().decode("utf-8", errors="ignore")[:600]


def _feishu_sign(secret: str) -> tuple[str, str]:
    """飞书机器人签名：timestamp + "\\n" + secret 作 HMAC-SHA256 key，空消息，base64。"""
    ts = str(int(time.time()))
    hmac_code = hmac.new(f"{ts}\n{secret}".encode("utf-8"), digestmod=hashlib.sha256).digest()
    return ts, base64.b64encode(hmac_code).decode("utf-8")


def build_message(d: dict, html_name: str, public_url: str = "") -> tuple[str, str]:
    """把轮次数据压成一条手机上一屏能看完的摘要。"""
    a = d["agg"]
    pending = int(d.get("pending") or 0)
    ai_err = int(d.get("ai_err") or 0)
    degraded = bool(a["failed"] or pending or ai_err)
    hour = int(d["key"][11:13])
    slot = "早间" if hour < 9 else ("午间" if hour < 16 else "晚间")
    ok = a["failed"] == 0
    title = f"抓取报告 {d['key'][5:10]} {hour:02d}:00 {slot}轮｜新增 {a['inserted']} 篇"
    if degraded:
        title = f"【注意】{title}｜待解读 {pending}"

    lines = [
        f"**状态**：{'全部成功' if ok else str(a['failed']) + ' 个源失败'}",
        f"**总览**：{a['sources']} 源｜扫描 {a['found']}｜新增 **{a['inserted']}**｜判重 {a['duplicated']}｜耗时 {d['secs']:.0f}s",
        "",
    ]
    if degraded:
        lines.append("**需要关注**")
        if pending or ai_err:
            lines.append(
                f"- 待解读 {pending} 篇 / AI 错误 {ai_err} 篇：新闻已入库不会丢失，"
                "多为 AI 额度耗尽；额度恢复后下一轮自动补解读"
            )
        if a["failed"]:
            lines.append(f"- {a['failed']} 个源级失败，下轮自动重试")
        lines.append("")
    lines.append("**本轮新增**")
    if d["news"]:
        for t, city, pub, status, err, src in d["news"][:8]:
            lines.append(f"- [{city or '—'}] {t[:42]}")
        if len(d["news"]) > 8:
            lines.append(f"- …另有 {len(d['news']) - 8} 篇，见完整报告")
    else:
        lines.append("- 无新增（列表内容均已入库，正常）")
    lines.append("")
    notes = [(r[8], r[7]) for r in d["logs"] if r[7]]
    failed = [r[8] for r in d["logs"] if r[3] != "ok"]
    if notes or failed:
        lines.append("**异常与处置**")
        for name, note in notes:
            lines.append(f"- {name}：{note}（下轮自动重试，无需处理）")
        for name in failed:
            lines.append(f"- {name}：源级失败，需关注（下轮会重试）")
    else:
        lines.append("**异常**：无")
    lines += [
        "",
        f"全库 {d['total']} 篇｜已解读 {d['interpreted']}｜待解读 {pending}｜AI 错误 {ai_err}",
    ]
    if public_url:
        lines.append(f"完整报告：[在手机上查看最新一轮]({public_url})（链接固定，每轮自动更新）")
    else:
        lines.append(f"完整报告：`data/reports/{html_name}`")
    return title, "\n".join(lines)


def _dispatch(title: str, markdown: str, *, red: bool = False,
              extra: dict | None = None, link: str | None = None) -> dict:
    """把一条消息发到当前配置的渠道。任何异常都被吞掉并记日志。"""
    channel = os.getenv("NOTIFY_CHANNEL", "off").strip().lower()
    if channel in ("", "off", "none"):
        return {"skipped": True, "reason": "NOTIFY_CHANNEL 未配置（off）"}
    if channel not in CHANNELS:
        log.warning("unknown NOTIFY_CHANNEL=%s, skip", channel)
        return {"skipped": True, "reason": f"未知渠道 {channel}"}

    webhook = os.getenv("NOTIFY_WEBHOOK", "").strip()
    token = os.getenv("NOTIFY_TOKEN", "").strip()
    secret = os.getenv("NOTIFY_SECRET", "").strip()

    if channel in ("feishu", "wecom", "custom") and not webhook:
        return {"skipped": True, "reason": f"{channel} 缺少 NOTIFY_WEBHOOK"}
    if channel in ("serverchan", "pushplus") and not token:
        return {"skipped": True, "reason": f"{channel} 缺少 NOTIFY_TOKEN"}

    try:
        if channel == "feishu":
            elements = [{"tag": "div", "text": {"tag": "lark_md", "content": markdown}}]
            if link:
                elements.append({
                    "tag": "action",
                    "actions": [{
                        "tag": "button", "type": "primary",
                        "text": {"tag": "plain_text", "content": "查看完整报告"},
                        "url": link,
                    }],
                })
            payload = {
                "msg_type": "interactive",
                "card": {
                    "header": {"title": {"tag": "plain_text", "content": title},
                               "template": "red" if red else "green"},
                    "elements": elements,
                },
            }
            if secret:
                ts, sign = _feishu_sign(secret)
                payload["timestamp"], payload["sign"] = ts, sign
            status, body = _post(webhook, payload)
        elif channel == "wecom":
            status, body = _post(webhook, {"msgtype": "markdown", "markdown": {"content": markdown}})
        elif channel == "serverchan":
            status, body = _post(
                f"https://sctapi.ftqq.com/{token}.send",
                {"title": title, "desp": markdown}, form=True,
            )
        elif channel == "pushplus":
            status, body = _post(
                "https://www.pushplus.plus/send",
                {"token": token, "title": title, "content": markdown, "template": "markdown"},
            )
        else:  # custom
            status, body = _post(webhook, {
                "title": title, "text": markdown, "markdown": markdown,
                **(extra or {}),
            })
        result = {"ok": 200 <= status < 300, "channel": channel, "status": status, "body": body}
        log.info("message pushed via %s: %s %s", channel, status, body[:120])
        return result
    except Exception as ex:  # noqa: BLE001
        log.warning("message push failed via %s: %s", channel, str(ex)[:200])
        return {"ok": False, "channel": channel, "error": str(ex)[:200]}


def push_report(d: dict, html_path: str, md_path: str = "") -> dict:
    """生成报告后调用；返回推送结果字典。"""
    from .publisher import public_url

    a = d["agg"]
    red = bool(a["failed"] or d.get("pending") or d.get("ai_err"))
    url = public_url()
    title, markdown = build_message(d, os.path.basename(html_path), url)
    return _dispatch(title, markdown, red=red, link=url or None, extra={
        "report_html": os.path.basename(html_path),
        "report_md": os.path.basename(md_path) if md_path else "",
        "report_url": url,
        "round": d["key"],
    })


def push_alert(title: str, markdown: str, link: str = "") -> dict:
    """即时告警（AI 额度耗尽、系统异常等），不等下一轮报告。"""
    return _dispatch(title, markdown, red=True, link=link or None,
                     extra={"kind": "alert"})


def push_notice(title: str, markdown: str, *, red: bool = False,
                link: str = "") -> dict:
    """一般通知：09:00 存活心跳、周报 / 月报摘要。"""
    return _dispatch(title, markdown, red=red, link=link or None,
                     extra={"kind": "notice"})
