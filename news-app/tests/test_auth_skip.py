"""认证密钥隔离、无正文条目抑制。"""
import hashlib
import hmac
import time
import unittest
from datetime import datetime, timedelta

from app import auth, config, models  # noqa: F401
from app.crawler.runner import _is_permanent_failure, is_suppressed, suppress
from app.db import Base, SessionLocal, engine
from app.dedup import url_hash
from app.models import SkippedURL


class AuthSecretTests(unittest.TestCase):
    def setUp(self):
        self.original = config.AUTH_SECRET

    def tearDown(self):
        config.AUTH_SECRET = self.original

    def test_secret_is_independent_from_password(self):
        config.AUTH_SECRET = "high-entropy-random-secret"
        self.assertNotEqual(config.auth_signing_key(), config.ADMIN_PASSWORD)
        token = auth.create_token()
        self.assertTrue(auth.verify_token(token))
        config.AUTH_SECRET = "rotated-secret"
        self.assertFalse(auth.verify_token(token))

    def test_fallback_when_secret_missing(self):
        config.AUTH_SECRET = ""
        self.assertEqual(config.auth_signing_key(), config.ADMIN_PASSWORD)
        self.assertTrue(auth.verify_token(auth.create_token()))

    def test_tampered_token_rejected(self):
        config.AUTH_SECRET = "k"
        token = auth.create_token()
        exp, sig = token.rsplit(".", 1)
        self.assertFalse(auth.verify_token(f"{exp}.{'0' * len(sig)}"))
        self.assertFalse(auth.verify_token("not-a-token"))

    def test_expired_token_rejected(self):
        config.AUTH_SECRET = "k"
        exp = str(int(time.time()) - 10)
        sig = hmac.new(b"k", exp.encode(), hashlib.sha256).hexdigest()
        self.assertFalse(auth.verify_token(f"{exp}.{sig}"))


class SuppressionTests(unittest.TestCase):
    def setUp(self):
        Base.metadata.create_all(engine)
        self.db = SessionLocal()
        self.db.query(SkippedURL).delete()
        self.db.commit()
        self.url = "https://www.heyuan.gov.cn/ywdt/bmdt/content/post_1.html"
        self.u_h = url_hash(self.url)

    def tearDown(self):
        self.db.close()

    def test_lifecycle_and_hit_count(self):
        self.assertFalse(is_suppressed(self.db, self.u_h))
        suppress(self.db, self.u_h, self.url, "empty")
        self.assertTrue(is_suppressed(self.db, self.u_h))
        row = self.db.get(SkippedURL, self.u_h)
        self.assertEqual(row.reason, "empty")
        self.assertEqual(row.hit_count, 2)  # 登记 1 次 + 命中 1 次

        suppress(self.db, self.u_h, self.url, "not_found")
        row = self.db.get(SkippedURL, self.u_h)
        self.assertEqual(self.db.query(SkippedURL).count(), 1)  # 不产生重复行
        self.assertEqual(row.reason, "not_found")

    def test_expired_entry_is_removed_and_retried(self):
        suppress(self.db, self.u_h, self.url, "empty")
        row = self.db.get(SkippedURL, self.u_h)
        row.expires_at = datetime.now() - timedelta(seconds=1)
        self.db.commit()
        self.assertFalse(is_suppressed(self.db, self.u_h))
        self.assertIsNone(self.db.get(SkippedURL, self.u_h))

    def test_only_permanent_errors_are_suppressed(self):
        self.assertTrue(_is_permanent_failure(RuntimeError("HTTP 404 for https://x")))
        self.assertTrue(_is_permanent_failure(RuntimeError("HTTP 410 for https://x")))
        self.assertFalse(_is_permanent_failure(TimeoutError("read timeout")))
        self.assertFalse(_is_permanent_failure(RuntimeError("curl failed: SSL certificate problem")))


if __name__ == "__main__":
    unittest.main()
