"""认证：单用户口令换无状态签名 token（服务重启不失效）。"""
import hashlib
import hmac
import time

from fastapi import APIRouter, HTTPException, Request

from . import config

router = APIRouter()

TOKEN_EXPIRE_SECONDS = config.AUTH_TOKEN_EXPIRE_HOURS * 3600


def _sign(exp: str) -> str:
    return hmac.new(config.ADMIN_PASSWORD.encode("utf-8"), exp.encode(), hashlib.sha256).hexdigest()


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


@router.post("/api/login")
def login(body: dict):
    if body.get("password") != config.ADMIN_PASSWORD:
        raise HTTPException(status_code=403, detail="口令错误")
    return {"token": create_token()}
