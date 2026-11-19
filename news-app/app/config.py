"""应用配置：从环境变量/.env 读取。"""
import os
import time
from pathlib import Path

from dotenv import load_dotenv

# 容器/沙箱默认 UTC 会让 datetime.now() 把日期算到前一天；统一固定北京时间。
os.environ.setdefault("TZ", "Asia/Shanghai")
if hasattr(time, "tzset"):
    time.tzset()

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "changeme")
# 登录口令与 token 签名密钥分离：口令可能被人记住/复用且强度有限，
# 签名密钥应是独立的高熵随机串。未配置时回退旧口令，保证老部署仍可用。
AUTH_SECRET = os.getenv("AUTH_SECRET", "").strip()
AUTH_TOKEN_EXPIRE_HOURS = int(os.getenv("AUTH_TOKEN_EXPIRE_HOURS", "72"))

# 登录防爆破：同一来源连续失败 N 次锁定 M 秒（发布到公网后必须保持开启）。
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_LOCK_SECONDS = int(os.getenv("LOGIN_LOCK_SECONDS", "300"))

# WorkBuddy「发布为应用」沙箱只有一个 HTTP 端口，没有 Chrome、也不该跑抓取/推送。
# 开启后不挂定时任务，线上仅提供新闻/趋势/报告的只读浏览。
PUBLISH_MODE = os.getenv("PUBLISH_MODE", "").strip().lower() in ("1", "true", "yes", "on")


def auth_signing_key() -> str:
    return AUTH_SECRET or ADMIN_PASSWORD

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

# ---- 增量抓取（水位 + 翻页 + 早停）----
# WATERMARK_OVERLAP_DAYS：水位往回退几天重扫，吸收补发/时钟误差/列表乱序。
WATERMARK_OVERLAP_DAYS = int(os.getenv("WATERMARK_OVERLAP_DAYS", "2"))
# 列表翻页：每轮最多翻几页、每页条数、连续多少条早于阈值就停。
PAGE_MAX = int(os.getenv("PAGE_MAX", "6"))
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "50"))
EARLY_STOP_STREAK = int(os.getenv("EARLY_STOP_STREAK", "12"))
# 补抓上限：单次补抓最多翻多少页、多少条，防止误操作把站翻穿。
BACKFILL_PAGE_MAX = int(os.getenv("BACKFILL_PAGE_MAX", "40"))
BACKFILL_ITEM_MAX = int(os.getenv("BACKFILL_ITEM_MAX", "2000"))
# 补抓并发度：同时跑几个源（每源独立 Session，域名级限速仍保留）。
# 数据库是单写者，并发主要加速网络等待；保守默认 3，最高 8。
BACKFILL_CONCURRENCY = int(os.getenv("BACKFILL_CONCURRENCY", "3"))
# 水位健康告警：水位（最新发布日期）距今超过 N 天视为停滞；超过 2N 天升级红色。
# 政务站周末/节假日停更常见，默认 3 天（翻倍 6 天才红），避免误报。
# 新源启用未满 N 天、水位仍为空属正常建立期，不算异常。
WATERMARK_STALL_DAYS = int(os.getenv("WATERMARK_STALL_DAYS", "3"))
WATERMARK_NEVER_GRACE_DAYS = int(os.getenv("WATERMARK_NEVER_GRACE_DAYS", "2"))
# 冷启动日期下限：新源首次抓取最多往前追 N 天，更旧的历史稿不入库。
# 防止批量接入新源时，冷启动深翻把半年前的旧闻全捞回来（撑爆解读队列）。
COLD_START_MAX_AGE_DAYS = int(os.getenv("COLD_START_MAX_AGE_DAYS", "60"))

# ---- 安全抓取 ----
# 同一域名两次请求的最小间隔（秒），带随机抖动，降低被限流/封禁风险。
DOMAIN_MIN_INTERVAL = float(os.getenv("DOMAIN_MIN_INTERVAL", "2.5"))
DOMAIN_JITTER = float(os.getenv("DOMAIN_JITTER", "1.5"))
# 连续失败熔断：达到次数后本源跳过 N 分钟。
CIRCUIT_FAIL_THRESHOLD = int(os.getenv("CIRCUIT_FAIL_THRESHOLD", "3"))
CIRCUIT_COOLDOWN_MINUTES = int(os.getenv("CIRCUIT_COOLDOWN_MINUTES", "60"))
# 每轮全局发起的列表页请求上限，兜底防止异常站点拖垮整轮。
MAX_LIST_REQUESTS_PER_ROUND = int(os.getenv("MAX_LIST_REQUESTS_PER_ROUND", "800"))

# ---- 创宇盾新版 412 挑战（卫健委 / 药监局）----
# 这类 WAF 的外链混淆 JS 需要完整浏览器 DOM，quickjs 解不了；用本机 Chrome
# headless + CDP 跑完挑战取回 cookie。找不到 Chrome 时这两个源本轮失败，不影响其它源。
CHROME_PATH = os.getenv(
    "CHROME_PATH", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
)
WAF_COOKIE_TTL = int(os.getenv("WAF_COOKIE_TTL", "600"))       # 412 cookie 缓存秒数
WAF_CHROME_WAIT = float(os.getenv("WAF_CHROME_WAIT", "6"))     # 留给挑战 JS 执行/重载的秒数
WAF_CHROME_TIMEOUT = int(os.getenv("WAF_CHROME_TIMEOUT", "40"))  # 单次预热总超时

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
# 两档解读：分界日当天及之后走细致解读（逐篇全量），之前走粗略解读
# （一次 AI 调用打包多篇，只出短摘要），既省 token 又提速。
ROUGH_INTERPRET_CUTOFF = os.getenv("ROUGH_INTERPRET_CUTOFF", "2026-10-01")
ROUGH_INTERPRET_BATCH = int(os.getenv("ROUGH_INTERPRET_BATCH", "10"))
