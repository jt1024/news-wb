"""应用配置：从环境变量/.env 读取。"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
AUTH_TOKEN_EXPIRE_HOURS = int(os.getenv("AUTH_TOKEN_EXPIRE_HOURS", "72"))

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'data' / 'news.db'}")

# ---- AI ----
AI_PROVIDER = os.getenv("AI_PROVIDER", "").strip().lower()  # deepseek|minimax|qwen
AI_MODEL = os.getenv("AI_MODEL", "").strip()
# 强模型：用于政策文件类精读；留空则全部用 AI_MODEL
AI_MODEL_STRONG = os.getenv("AI_MODEL_STRONG", "").strip()
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
# 主通道返回 402（额度耗尽）时自动切换的备用通道；留空表示不启用，
# 此时仍会中止解读并推送告警，新闻照常入库、恢复后自动补解读。
AI_FALLBACK_PROVIDER = os.getenv("AI_FALLBACK_PROVIDER", "").strip().lower()
AI_FALLBACK_API_KEY = os.getenv("AI_FALLBACK_API_KEY", "").strip()
AI_FALLBACK_MODEL = os.getenv("AI_FALLBACK_MODEL", "").strip()

AI_BASE_URLS = {
    "deepseek": "https://api.deepseek.com/v1",
    "minimax": "https://api.minimax.chat/v1",
    "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1",
}
AI_DEFAULT_MODELS = {
    "deepseek": "deepseek-chat",
    "minimax": "MiniMax-M3.1-Flash",
    "qwen": "qwen-plus",
}

def ai_enabled() -> bool:
    return bool(AI_PROVIDER and AI_API_KEY)


def ai_base_url() -> str:
    return AI_BASE_URLS.get(AI_PROVIDER, "")


def ai_model() -> str:
    return AI_MODEL or AI_DEFAULT_MODELS.get(AI_PROVIDER, "")


def ai_strong_model() -> str:
    """政策文件精读用强模型；未配置则退回普通模型。"""
    return AI_MODEL_STRONG or ai_model()


def ai_fallback_enabled() -> bool:
    """备用通道三项齐全且 provider 已知才算可用。"""
    return bool(
        AI_FALLBACK_PROVIDER and AI_FALLBACK_API_KEY
        and AI_BASE_URLS.get(AI_FALLBACK_PROVIDER)
    )


def ai_fallback_base_url() -> str:
    return AI_BASE_URLS.get(AI_FALLBACK_PROVIDER, "")


def ai_fallback_model() -> str:
    return AI_FALLBACK_MODEL or AI_DEFAULT_MODELS.get(AI_FALLBACK_PROVIDER, "")


# ---- 抓取 ----
FETCH_CONCURRENCY = int(os.getenv("FETCH_CONCURRENCY", "4"))
FETCH_DELAY_SECONDS = float(os.getenv("FETCH_DELAY_SECONDS", "1.5"))
TITLE_SIMILARITY_THRESHOLD = float(os.getenv("TITLE_SIMILARITY_THRESHOLD", "0.9"))
SIMHASH_DISTANCE_THRESHOLD = int(os.getenv("SIMHASH_DISTANCE_THRESHOLD", "3"))
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
FETCH_TIMEOUT = 20

# ---- 定时 ----
# CRON_HOURS：每天触发的小时列表（逗号分隔，如 "6,12,21"）；
# 未设置时回退到旧的 CRON_HOUR 单时刻。分钟统一用 CRON_MINUTE。
def _parse_cron_hours() -> list[int]:
    raw = os.getenv("CRON_HOURS", "").strip()
    if raw:
        try:
            hours = sorted({int(h) for h in raw.split(",") if h.strip() != ""})
            if hours:
                return hours
        except ValueError:
            pass
    return [int(os.getenv("CRON_HOUR", "7"))]

CRON_HOURS = _parse_cron_hours()
CRON_MINUTE = int(os.getenv("CRON_MINUTE", "30"))

# ---- AI 解读 ----
INTERPRET_BATCH_SIZE = int(os.getenv("INTERPRET_BATCH_SIZE", "20"))
INTERPRET_RETRIES = int(os.getenv("INTERPRET_RETRIES", "2"))
