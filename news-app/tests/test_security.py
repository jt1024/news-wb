"""公网加固回归：登录防爆破、发布模式只读、公开入口收拢、探活。

只使用临时库，不触碰生产数据（见 tests/__init__.py）。
"""
import json
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from starlette.requests import Request

from app import auth, config, main
from app.api import admin
from app.db import Base, engine


def _request(ip="1.2.3.4", xff=None, headers=None):
    raw = [(b"x-forwarded-for", xff.encode())] if xff else []
    if headers:
        raw = headers
    return Request({
        "type": "http", "method": "POST", "path": "/api/login",
        "headers": raw, "query_string": b"", "scheme": "http",
        "client": (ip, 12345), "server": ("test", 80),
    })


class LoginGuardTests(unittest.TestCase):
    def setUp(self):
        auth._failures.clear()
        auth._global_failures.update(n=0, until=0.0)

    def tearDown(self):
        auth._failures.clear()
        auth._global_failures.update(n=0, until=0.0)

    def test_client_key_prefers_forwarded_for(self):
        self.assertEqual(auth._client_key(_request(xff="9.9.9.9, 10.0.0.1")), "9.9.9.9")
        self.assertEqual(auth._client_key(_request(ip="7.7.7.7")), "7.7.7.7")

    def test_lockout_after_consecutive_failures(self):
        with patch.object(config, "ADMIN_PASSWORD", "unit-test-strong-secret"), \
             patch.object(config, "LOGIN_MAX_FAILURES", 3), \
             patch.object(config, "LOGIN_LOCK_SECONDS", 60):
            req = _request(ip="5.5.5.5")
            for _ in range(3):
                with self.assertRaises(HTTPException) as cm:
                    auth.login({"password": "wrong"}, req)
                self.assertEqual(cm.exception.status_code, 403)
            with self.assertRaises(HTTPException) as cm:
                auth.login({"password": "wrong"}, req)
            self.assertEqual(cm.exception.status_code, 429)
            # 锁定只影响该来源，其它 IP 仍可登录
            resp = auth.login({"password": "unit-test-strong-secret"}, _request(ip="6.6.6.6"))
            self.assertTrue(auth.verify_token(json.loads(resp.body)["token"]))

    def test_success_clears_counter(self):
        with patch.object(config, "ADMIN_PASSWORD", "unit-test-strong-secret"), \
             patch.object(config, "LOGIN_MAX_FAILURES", 3):
            req = _request(ip="5.5.5.5")
            with self.assertRaises(HTTPException):
                auth.login({"password": "wrong"}, req)
            auth.login({"password": "unit-test-strong-secret"}, req)
            self.assertNotIn("5.5.5.5", auth._failures)

    def test_login_sets_cookie(self):
        with patch.object(config, "ADMIN_PASSWORD", "unit-test-strong-secret"):
            resp = auth.login({"password": "unit-test-strong-secret"}, _request())
            self.assertIn("nb_token=", resp.headers.get("set-cookie", ""))
            self.assertIn("HttpOnly", resp.headers.get("set-cookie", ""))


class ProxyHeaderTests(unittest.TestCase):
    """发布平台反代会占用 Authorization 头，必须还能靠自定义头/cookie 鉴权。"""

    def test_custom_header_and_cookie_are_accepted(self):
        with patch.object(config, "AUTH_SECRET", "unit-test-key"):
            token = auth.create_token()
            auth.require_auth(_request(headers=[(b"x-nb-token", token.encode())]))
            auth.require_auth(_request(headers=[(b"cookie", f"nb_token={token}".encode())]))
            with self.assertRaises(HTTPException):
                auth.require_auth(_request())


class PublishModeTests(unittest.TestCase):
    def test_docs_and_openapi_are_disabled(self):
        self.assertIsNone(main.app.docs_url)
        self.assertIsNone(main.app.redoc_url)
        self.assertIsNone(main.app.openapi_url)

    def test_weak_password_rejected_in_publish_mode(self):
        with patch.object(config, "PUBLISH_MODE", True), \
             patch.object(config, "AUTH_SECRET", "x" * 40), \
             patch.object(config, "ADMIN_PASSWORD", "123456"):
            with self.assertRaises(RuntimeError):
                main._check_auth_security()
        with patch.object(config, "PUBLISH_MODE", True), \
             patch.object(config, "AUTH_SECRET", "x" * 40), \
             patch.object(config, "ADMIN_PASSWORD", "a-32-char-strong-secret-value"):
            main._check_auth_security()

    def test_write_endpoints_are_readonly(self):
        with patch.object(config, "PUBLISH_MODE", True):
            with self.assertRaises(HTTPException) as cm:
                admin._read_only_guard()
            self.assertEqual(cm.exception.status_code, 403)
        with patch.object(config, "PUBLISH_MODE", False):
            admin._read_only_guard()

    def test_health_reports_db_state(self):
        Base.metadata.create_all(engine)
        data = main.health()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(data["db"])
        self.assertIn("news", data)


if __name__ == "__main__":
    unittest.main()
