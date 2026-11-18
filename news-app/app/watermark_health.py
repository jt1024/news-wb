"""水位健康度判定（纯逻辑，无 I/O，便于单测）。

执行报告每轮把 sources 的水位字段读出来交给本模块，归类成：
    healthy   正常
    circuit   连续失败已熔断
    stalled   有水位但停滞（疑似站点改版、长期无新稿）
    never     从未建立水位
    pending   待覆盖（冷启动期，见下）

三条关键设计原则：
1. 水位是「本源已见过的最新发布日期」，不是抓取时间。政务站周末/节假日
   常停更，age 天然偏大，所以停滞默认阈值 3 天、翻倍 6 天才转红，文案一律
   写「请核实」而非「故障」——低频源停更正常，不能误报。
2. 冷启动保护：水位功能刚上线时，绝大多数源还没被新代码抓过一轮，水位为空
   属正常。若整体水位覆盖率低于 COLD_START_RATIO（默认 50%），把 never 降级
   为 pending（待覆盖），不计入异常、不触发告警；等覆盖率上来后，个别源仍无
   水位才判为异常。否则上线第一天就会报「189 源异常」，淹没真正的信号。
3. 整列缺失（库未迁移）时返回 available=False，报告跳过该章节，绝不崩溃。
"""
from __future__ import annotations

from datetime import datetime

LEVEL_OK = "ok"
LEVEL_WARN = "warn"
LEVEL_DANGER = "danger"

# 有水位源占比低于此值 → 视为水位功能上线初期（冷启动）
COLD_START_RATIO = 0.5


def parse_dt(value) -> datetime | None:
    """兼容 datetime / ISO 字符串 / 空格分隔 / 空值。"""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).strip().replace("Z", ""))
    except (ValueError, TypeError):
        return None


def analyze_watermarks(rows: list[dict], now: datetime, *,
                       stall_days: int = 3,
                       grace_days: int = 2,
                       circuit_threshold: int = 3,
                       cold_start_ratio: float = COLD_START_RATIO) -> dict:
    """归类各源水位健康度。

    rows 每项需含：name, last_max_publish, consecutive_fail, created_at；
    可选 enabled / region_city / region_province 用于展示。调用方负责只传启用源。
    返回：
        available  —— 是否有水位数据（列缺失时为 False）
        total / healthy / abnormal —— 计数（abnormal = 需核实源数 = len(issues)）
        issues     —— 需核实源（stalled/circuit，冷启动期过后还可能含 never），
                      按严重程度 danger > warn 排序，每项含
                      level/kind/name/age_days/detail/action
    pending    —— 冷启动期待覆盖源（不计入 abnormal）
    paged      —— 已配置 page_pattern 的源跟踪（见 track_paged_sources）
    cold_start —— 是否处于水位覆盖冷启动期
    coverage   —— 水位覆盖率 0~1
    worst      —— 最高严重级别，供推送决定是否标红
    """
    total = len(rows)
    with_wm = sum(1 for r in rows if parse_dt(r.get("last_max_publish")) is not None)
    coverage = (with_wm / total) if total else 1.0
    cold_start = total > 0 and coverage < cold_start_ratio

    issues: list[dict] = []
    pending: list[dict] = []
    healthy = 0

    for r in rows:
        name = r.get("name") or f"源#{r.get('id', '?')}"
        wm = parse_dt(r.get("last_max_publish"))
        fails = int(r.get("consecutive_fail") or 0)
        created = parse_dt(r.get("created_at"))

        # 1) 连续失败熔断：最明确的异常，优先判定（与冷启动无关）
        if fails >= circuit_threshold:
            issues.append({
                "level": LEVEL_DANGER, "kind": "circuit", "name": name,
                "age_days": None, "fails": fails,
                "detail": f"连续失败 {fails} 轮，已触发熔断跳过",
                "action": "检查站点是否改版/反爬升级；恢复后水位会自动续上，无需删数据",
            })
            continue

        # 2) 从未建立水位
        if wm is None:
            if cold_start:
                # 功能上线初期：整体覆盖率低，无水位属正常，降级为待覆盖
                pending.append({
                    "name": name,
                    "detail": "尚未被增量抓取覆盖（水位功能上线初期，随后续轮次自动建立）",
                })
            else:
                age_created = (now - created).days if created else 10 ** 6
                if age_created <= grace_days:
                    healthy += 1  # 覆盖率已达标后的真正新源，建立期正常
                else:
                    issues.append({
                        "level": LEVEL_WARN, "kind": "never", "name": name,
                        "age_days": None, "fails": fails,
                        "detail": "多数源已有水位，此源仍为空（列表/详情都解析不到发布日期）",
                        "action": "补抓指定日期可入库；建议检查该源日期解析规则，或接受其只靠 URL 去重",
                    })
            continue

        # 3) 水位停滞（有水位才判定）
        age = max(0, (now.date() - wm.date()).days)
        if age > stall_days:
            # 停滞超过两倍阈值升级为 danger（例如 3 天阈值、停滞 7 天以上）
            level = LEVEL_DANGER if age > stall_days * 2 else LEVEL_WARN
            issues.append({
                "level": level, "kind": "stalled", "name": name,
                "age_days": age, "fails": fails,
                "detail": f"水位停在 {wm.date()}（{age} 天前未见更新的发布日期）",
                "action": "请核实：站点停更/改版/反爬；若为低频源可忽略，否则用补抓工具补近期日期",
            })
        else:
            healthy += 1

    order = {LEVEL_DANGER: 0, LEVEL_WARN: 1, LEVEL_OK: 2}
    issues.sort(key=lambda x: (order.get(x["level"], 9), -(x.get("age_days") or 0), x["name"]))

    worst = LEVEL_OK
    for i in issues:
        if order.get(i["level"], 9) < order.get(worst, 9):
            worst = i["level"]

    return {
        "available": True,
        "total": total,
        "healthy": healthy,
        "abnormal": len(issues),
        "issues": issues,
        "pending": pending,
        "paged": track_paged_sources(rows, now, stall_days=stall_days,
                                     circuit_threshold=circuit_threshold),
        "cold_start": cold_start,
        "coverage": round(coverage, 3),
        "worst": worst,
        "stall_days": stall_days,
    }


def track_paged_sources(rows: list[dict], now: datetime, *,
                        stall_days: int = 3,
                        circuit_threshold: int = 3) -> list[dict]:
    """跟踪"配置了 page_pattern 的源"的专属状态。

    这些源是本轮刚逐站实测、手工配上翻页模板的，日常抓取还没跑过一轮，
    水位多为空。它们混在 cold_start 的 189 个待覆盖源里根本看不见，也无法
    验证"分页配置到底生效没"。这里单独成组展示，让运维能一眼看到：
        - 已建立水位（分页 + 增量都正常，最理想）
        - 待建立水位（分页已配、等下一轮增量；正常，不算异常）
        - 分页失效（配了分页却仍无水位，且已过建立宽限期 → 需核实）
        - 水位停滞 / 熔断（沿用主判定，警示分页虽配但站点出问题）

    关键：只跟踪、不放大。"待建立"绝不进 issues、不触发告警，否则刚配好
    就报异常，等于自造噪声。只有过了 grace 仍无水位才标记需核实。
    """
    out: list[dict] = []
    for r in rows:
        if not r.get("has_page_pattern"):
            continue
        name = r.get("name") or f"源#{r.get('id', '?')}"
        wm = parse_dt(r.get("last_max_publish"))
        fails = int(r.get("consecutive_fail") or 0)
        # 宽限期基准必须是"分页配置日期"，不是源的创建日期——源可能几个月前
        # 就入库了，分页却是今天才配的，用 created_at 会误报"配了很久没生效"。
        paged_at = parse_dt(r.get("paged_at")) or parse_dt(r.get("created_at"))

        if fails >= circuit_threshold:
            status, level = "circuit", LEVEL_DANGER
            detail = f"连续失败 {fails} 轮，已熔断；分页配置需等站点恢复后复核"
        elif wm is None:
            age_paged = (now - paged_at).days if paged_at else 0
            # 建立宽限期：stall_days 天内水位为空属正常（尚未跑过增量轮）
            if age_paged <= stall_days:
                status, level = "pending", LEVEL_OK
                detail = "分页已配，水位待建立（下一轮增量抓取后应自动建立）"
            else:
                status, level = "stale", LEVEL_WARN
                detail = f"分页已配但 {age_paged} 天仍无水位，疑似分页未生效，请核实"
        else:
            age = max(0, (now.date() - wm.date()).days)
            if age > stall_days:
                status = "stalled"
                level = LEVEL_DANGER if age > stall_days * 2 else LEVEL_WARN
                detail = f"水位停在 {wm.date()}（{age} 天前），请核实站点是否停更"
            else:
                status, level = "established", LEVEL_OK
                detail = f"分页与水位均正常（水位 {wm.date()}）"
        out.append({"name": name, "status": status, "level": level,
                    "detail": detail, "wm_date": wm.date().isoformat() if wm else None})
    return out


def unavailable_result() -> dict:
    """水位列不存在（旧库未迁移）时的占位结果，报告据此跳过该章节。"""
    return {
        "available": False, "total": 0, "healthy": 0, "abnormal": 0,
        "issues": [], "pending": [], "paged": [], "cold_start": False,
        "coverage": 0.0, "worst": LEVEL_OK, "stall_days": 0,
    }


def summary_line(w: dict) -> str:
    """给推送摘要用的一行话。冷启动期不制造「异常」假象。"""
    if not w or not w.get("available"):
        return ""
    # 已配分页源的一句话后缀（不并入异常，仅可见）
    paged = w.get("paged") or []
    paged_note = ""
    if paged:
        bad = sum(1 for p in paged if p["level"] in (LEVEL_WARN, LEVEL_DANGER))
        paged_note = (f"；已配翻页 {len(paged)} 源" +
                      (f"（{bad} 源待核实）" if bad else "（均正常/待建立）"))
    if w.get("cold_start"):
        return (f"水位覆盖 {int(w.get('coverage', 0) * 100)}%（功能上线初期，"
                f"{len(w.get('pending', []))} 源待覆盖）{paged_note}")
    if not w["abnormal"]:
        return f"水位健康：{w['healthy']}/{w['total']} 源正常{paged_note}"
    kinds = {}
    for i in w["issues"]:
        kinds[i["kind"]] = kinds.get(i["kind"], 0) + 1
    parts = {"circuit": "熔断", "stalled": "停滞", "never": "无水位"}
    detail = "、".join(f"{parts.get(k, k)} {v}" for k, v in kinds.items())
    return f"水位异常 {w['abnormal']} 源（{detail}）{paged_note}"
