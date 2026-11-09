"""兜底守护：轮次判定、告警去重、补跑节流、跨进程互斥锁。"""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from app import round_guard
from app.watchdog_logic import (
    alert_key, find_issues, latest_due_round, parse_ts,
    should_alert, should_retry_action,
)


class ParseTsTest(unittest.TestCase):
    def test_iso_variants(self):
        self.assertEqual(parse_ts("2026-11-08T21:04:15"),
                         datetime(2026, 11, 8, 21, 4, 15))
        self.assertEqual(parse_ts("2026-11-08 21:04:15"),
                         datetime(2026, 11, 8, 21, 4, 15))
        self.assertEqual(parse_ts("2026-11-08 21:04:15.123456").second, 15)

    def test_invalid_and_datetime(self):
        d = datetime(2026, 11, 8, 21)
        self.assertIs(parse_ts(d), d)
        self.assertIsNone(parse_ts(""))
        self.assertIsNone(parse_ts(None))
        self.assertIsNone(parse_ts("不是时间"))


class DueRoundTest(unittest.TestCase):
    def test_before_deadline_no_due_round_yet(self):
        # 12:20 时 12:00 轮还没过 30 分钟宽限，最近应完成的是昨晚 21:00
        now = datetime(2026, 11, 10, 12, 20)
        self.assertEqual(latest_due_round(now, [12, 21], 0, 30),
                         datetime(2026, 11, 9, 21, 0))

    def test_after_deadline_current_round_is_due(self):
        now = datetime(2026, 11, 10, 12, 31)
        self.assertEqual(latest_due_round(now, [12, 21], 0, 30),
                         datetime(2026, 11, 10, 12, 0))

    def test_evening_round(self):
        now = datetime(2026, 11, 10, 23, 59)
        self.assertEqual(latest_due_round(now, [12, 21], 0, 30),
                         datetime(2026, 11, 10, 21, 0))

    def test_custom_minute_and_grace(self):
        now = datetime(2026, 11, 10, 7, 45)
        self.assertEqual(latest_due_round(now, [6, 12, 21], 30, 10),
                         datetime(2026, 11, 10, 6, 30))


class FindIssuesTest(unittest.TestCase):
    DUE = datetime(2026, 11, 10, 12, 0)
    BASE = datetime(2026, 11, 10, 3, 50)

    def test_all_good(self):
        self.assertEqual(find_issues(
            service_ok=True, last_fetch=datetime(2026, 11, 10, 12, 2),
            report_at=datetime(2026, 11, 10, 12, 8), due=self.DUE,
            baseline_at=self.BASE), [])

    def test_service_down_alone(self):
        self.assertEqual(find_issues(
            service_ok=False, last_fetch=datetime(2026, 11, 10, 12, 2),
            report_at=datetime(2026, 11, 10, 12, 8), due=self.DUE,
            baseline_at=self.BASE), ["service"])

    def test_round_missing_also_flags_report_missing(self):
        # 整轮没跑时只报 round，避免补跑与补发报告同时启动
        self.assertEqual(find_issues(
            service_ok=False, last_fetch=datetime(2026, 11, 9, 21, 2),
            report_at=datetime(2026, 11, 9, 21, 8), due=self.DUE,
            baseline_at=self.BASE), ["service", "round"])

    def test_report_missing_only(self):
        self.assertEqual(find_issues(
            service_ok=True, last_fetch=datetime(2026, 11, 10, 12, 2),
            report_at=None, due=self.DUE, baseline_at=self.BASE), ["report"])

    def test_baseline_skips_history_before_watchdog_started(self):
        # 守护 03:50 上线，不追溯 11-09 21:00 的历史漏跑
        self.assertEqual(find_issues(
            service_ok=True, last_fetch=datetime(2026, 11, 8, 21, 2),
            report_at=datetime(2026, 11, 8, 21, 8),
            due=datetime(2026, 11, 9, 21, 0), baseline_at=self.BASE), [])

    def test_service_down_still_reported_before_baseline(self):
        self.assertEqual(find_issues(
            service_ok=False, last_fetch=None, report_at=None,
            due=datetime(2026, 11, 9, 21, 0), baseline_at=self.BASE), ["service"])

    def test_no_due_round_only_service(self):
        self.assertEqual(find_issues(
            service_ok=True, last_fetch=None, report_at=None, due=None,
            baseline_at=self.BASE), [])


class AlertStateTest(unittest.TestCase):
    NOW = datetime(2026, 11, 10, 12, 40)

    def test_key_is_order_independent(self):
        self.assertEqual(
            alert_key(["service", "round"], datetime(2026, 11, 10, 12)),
            alert_key(["round", "service"], datetime(2026, 11, 10, 12)))

    def test_key_differs_by_round_and_issue(self):
        k1 = alert_key(["round"], datetime(2026, 11, 10, 12))
        self.assertNotEqual(k1, alert_key(["round"], datetime(2026, 11, 10, 21)))
        self.assertNotEqual(k1, alert_key(["report"], datetime(2026, 11, 10, 12)))

    def test_service_only_key_ignores_round_change(self):
        # 长时间服务故障不能因为轮次从 12 点翻到 21 点就绕过冷却
        self.assertEqual(alert_key(["service"], datetime(2026, 11, 10, 12)), "service")
        self.assertEqual(alert_key(["service"], datetime(2026, 11, 10, 21)), "service")

    def test_cooldown(self):
        key = "2026-11-10 12:round"
        self.assertTrue(should_alert({}, key, self.NOW))
        recent = {"alerts": {key: (self.NOW - timedelta(hours=1)).isoformat()}}
        self.assertFalse(should_alert(recent, key, self.NOW, 6))
        old = {"alerts": {key: (self.NOW - timedelta(hours=7)).isoformat()}}
        self.assertTrue(should_alert(old, key, self.NOW, 6))

    def test_retry_action_throttle(self):
        key = "2026-11-10 12"
        self.assertTrue(should_retry_action({}, key, self.NOW))
        recent = {"handling": {key: (self.NOW - timedelta(minutes=10)).isoformat()}}
        self.assertFalse(should_retry_action(recent, key, self.NOW, 90))
        old = {"handling": {key: (self.NOW - timedelta(minutes=100)).isoformat()}}
        self.assertTrue(should_retry_action(old, key, self.NOW, 90))


class ExclusiveLockTest(unittest.TestCase):
    def test_second_holder_skips_and_lock_is_released(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(round_guard, "DATA_DIR", Path(d)):
                with round_guard.exclusive_lock("unit_test") as first:
                    self.assertTrue(first)
                    with round_guard.exclusive_lock("unit_test") as second:
                        self.assertFalse(second)
                with round_guard.exclusive_lock("unit_test") as third:
                    self.assertTrue(third)

    def test_round_lock_uses_own_file(self):
        with tempfile.TemporaryDirectory() as d:
            with patch.object(round_guard, "DATA_DIR", Path(d)):
                with round_guard.round_lock() as got:
                    self.assertTrue(got)
                self.assertTrue((Path(d) / "round.lock").exists())


if __name__ == "__main__":
    unittest.main()
