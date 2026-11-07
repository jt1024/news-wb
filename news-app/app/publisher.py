"""执行报告的「固定链接」产出层。

本机每轮把最新报告覆盖写到 data/reports/latest.html，同时写一份元信息；
在线版本由 WorkBuddy 定时自动化读取这两个文件、发到同一个活页方案
（LIVEPAGE_PROPOSAL_ID），因此微信/飞书里那条链接永远不变、内容自动更新。

这一层只做本机落盘与配置读取，不依赖网络、不依赖 AI 会话，
所以每轮定时任务一定能产出最新报告；在线发布失败也不影响本地报告。
"""
import json
import os
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
OUT_DIR = BASE_DIR / "data" / "reports"
load_dotenv(BASE_DIR / ".env", override=True)

LATEST_HTML = OUT_DIR / "latest.html"
LATEST_META = OUT_DIR / "latest.meta.json"


def public_url() -> str:
    """在线报告固定链接；未配置时返回空串（飞书卡片会退回本地路径）。"""
    return os.getenv("REPORT_PUBLIC_URL", "").strip()


def proposal_id() -> str:
    return os.getenv("LIVEPAGE_PROPOSAL_ID", "").strip()


def publish_local(html_path: str, md_path: str = "", round_key: str = "") -> dict:
    """把本轮报告覆盖为 latest.html，并写元信息供定时自动化发布使用。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(html_path, LATEST_HTML)
    meta = {
        "round": round_key,
        "html": str(LATEST_HTML),
        "md": md_path,
        "proposal_id": proposal_id(),
        "public_url": public_url(),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    LATEST_META.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return meta


def latest_meta() -> dict:
    try:
        return json.loads(LATEST_META.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
