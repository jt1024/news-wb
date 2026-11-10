"""认证：单用户口令换无状态签名 token（服务重启不失效）。

公网部署时口令是唯一入口，补上两件事：
1. 常数时间比较，避免按字符响应时间侧信道；
2. 按来源 IP 的失败计数 + 临时锁定，挡住暴力破解。
反向代理后面优先取 X-Forwarded-For 首跳，否则所有用户会被算成代理一个 IP。
"""
import hashlib
import hmac
import threading
import time

from fastapi import APIRouter, HTTPException, Request

from . import config

router = APIRouter()

TOKEN_EXPIRE_SECONDS = config.AUTH_TOKEN_EXPIRE_HOURS * 3600

_state_lock = threading.Lock()
_failures: dict[str, tuple[int, float]] = {}   # key -> (连续失败次数, 解锁时间)
_global_failures = {"n": 0, "until": 0.0}      # 防止伪造 XFF 绕过单 IP 限制


def _sign(exp: str) -> str:
    return hmac.new(config.auth_signing_key().encode("utf-8"), exp.encode(), hashlib.sha256).hexdigest()


def create_token() -> str:
    exp = str(int(time.time()) + TOKEN_EXPIRE_SECONDS)
    return f"{exp}.{_sign(exp)}"


def verify_token(token: str) -> bool:
    try:
        exp, sig = token.rsplit(".", 1)
        if int(exp) < time.time():
            return False
        return hmac.compare_digest(sig, _sign(exp))
    except (ValueError, TypeError):
        return False


def require_auth(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer ") and verify_token(auth[7:]):
        return
    if verify_token(request.cookies.get("nb_token") or ""):
        return
    raise HTTPException(status_code=401, detail="未登录")


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    first = forwarded.split(",", 1)[0].strip() if forwarded else ""
    return first or (request.client.host if request.client else "unknown")


def _is_locked(key: str) -> bool:
    now = time.time()
    with _state_lock:
        if _global_failures["until"] > now:
            return True
        entry = _failures.get(key)
        return bool(entry and entry[1] > now)


def _record_failure(key: str) -> None:
    now = time.time()
    limit = max(1, config.LOGIN_MAX_FAILURES)
    lock_for = max(1, config.LOGIN_LOCK_SECONDS)
    with _state_lock:
        count, until = _failures.get(key, (0, 0.0))
        if until and until <= now:      # 上次锁定已过期，重新开始计数
            count = 0
        count += 1
        _failures[key] = (count, now + lock_for if count >= limit else 0.0)
        # 全局兜底：伪造 XFF 时仍会在总量到线后短锁，随后自动清零
        if _global_failures["until"] <= now:
            _global_failures["n"] = 0
        _global_failures["n"] += 1
        if _global_failures["n"] >= limit * 4:
            _global_failures["until"] = now + 60
            _global_failures["n"] = 0
        # 控制内存：清理已过期的记录
        if len(_failures) > 500:
            for k, v in list(_failures.items()):
                if v[1] and v[1] <= now:
                    _failures.pop(k, None)


def _clear_failures(key: str) -> None:
    with _state_lock:
        _failures.pop(key, None)


@router.post("/api/login")
def login(body: dict, request: Request):
    key = _client_key(request)
    if _is_locked(key):
        raise HTTPException(status_code=429, detail="尝试次数过多，请稍后再试")
    supplied = body.get("password")
    supplied = supplied if isinstance(supplied, str) else ""
    if not hmac.compare_digest(supplied, config.ADMIN_PASSWORD):
        _record_failure(key)
        raise HTTPException(status_code=403, detail="口令错误")
    _clear_failures(key)
    return {"token": create_token()}
