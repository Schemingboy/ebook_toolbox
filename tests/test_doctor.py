"""doctor 自检的单元测试。

只测不发网络请求的部分（cookies 判断走 monkeypatch，代理探测走假端口探针）。
真实链路已在端到端验证里跑过。
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cookie_manager
import doctor
import env_config


class CheckEnvFileTests(unittest.TestCase):
    """check_env_file 内部是 `from env_config import ENV_FILE`，所以要 patch 源模块。"""

    def setUp(self):
        self._original = env_config.ENV_FILE

    def tearDown(self):
        env_config.ENV_FILE = self._original

    def test_missing_env_is_error_and_triggers_setup(self):
        with tempfile.TemporaryDirectory() as tmp:
            env_config.ENV_FILE = Path(tmp) / ".env"
            result = doctor.check_env_file()
        self.assertEqual(result.level, doctor.ERROR)
        self.assertTrue(result.is_error)

    def test_existing_env_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("ZLIBRARY_EMAIL=a@b.c\n", encoding="utf-8")
            env_config.ENV_FILE = env
            result = doctor.check_env_file()
        self.assertEqual(result.level, doctor.OK)


class CheckCookiesTests(unittest.TestCase):
    def setUp(self):
        self._status = cookie_manager.cookies_status
        self._refresh = cookie_manager.refresh_cookies

    def tearDown(self):
        cookie_manager.cookies_status = self._status
        cookie_manager.refresh_cookies = self._refresh

    def test_fresh_cookies_ok(self):
        cookie_manager.cookies_status = lambda *a, **k: cookie_manager.CookiesStatus(
            exists=True, count=5, has_login=True, age_hours=1.0
        )
        result = doctor.check_cookies(fix=False)
        self.assertEqual(result.level, doctor.OK)

    def test_stale_cookies_warn_when_not_fixing(self):
        """不修的时候只给 warn，不是 error——跑任务时会自动修，不该拦住用户。"""
        cookie_manager.cookies_status = lambda *a, **k: cookie_manager.CookiesStatus(
            exists=True, count=5, has_login=True, age_hours=99.0
        )
        result = doctor.check_cookies(fix=False)
        self.assertEqual(result.level, doctor.WARN)
        self.assertFalse(result.is_error)

    def test_stale_cookies_auto_fixed(self):
        cookie_manager.cookies_status = lambda *a, **k: cookie_manager.CookiesStatus(
            exists=False
        )
        calls = []

        def fake_refresh(**kwargs):
            calls.append(kwargs)
            return cookie_manager.CookiesStatus(
                exists=True, count=5, has_login=True, age_hours=0.0
            )

        cookie_manager.refresh_cookies = fake_refresh
        result = doctor.check_cookies(fix=True, emit=lambda *a: None)
        self.assertEqual(len(calls), 1)
        self.assertEqual(result.level, doctor.OK)
        self.assertTrue(result.fixed)

    def test_refresh_failure_becomes_error_with_hint(self):
        cookie_manager.cookies_status = lambda *a, **k: cookie_manager.CookiesStatus(
            exists=False
        )

        def boom(**kwargs):
            raise cookie_manager.CookieRefreshError("代理没开")

        cookie_manager.refresh_cookies = boom
        result = doctor.check_cookies(fix=True, emit=lambda *a: None)
        self.assertEqual(result.level, doctor.ERROR)
        self.assertTrue(result.hint)


class ProxyDetectTests(unittest.TestCase):
    def setUp(self):
        self._port_open = doctor._port_open

    def tearDown(self):
        doctor._port_open = self._port_open

    def test_detect_local_proxies_returns_open_ports(self):
        target = doctor.COMMON_PROXY_PORTS[0]
        doctor._port_open = lambda host, port, timeout=0.35: port == target
        found = doctor.detect_local_proxies()
        self.assertEqual(found, [f"http://127.0.0.1:{target}"])

    def test_detect_local_proxies_empty_when_nothing_open(self):
        doctor._port_open = lambda host, port, timeout=0.35: False
        self.assertEqual(doctor.detect_local_proxies(), [])


class ReportTests(unittest.TestCase):
    def test_needs_setup_when_credentials_missing(self):
        report = doctor.DoctorReport(
            checks=[
                doctor.CheckResult("env_file", doctor.OK, "ok"),
                doctor.CheckResult("credentials", doctor.ERROR, "缺凭据"),
            ]
        )
        self.assertTrue(report.needs_setup)
        self.assertFalse(report.ok)

    def test_warnings_do_not_break_ok(self):
        report = doctor.DoctorReport(
            checks=[
                doctor.CheckResult("cookies", doctor.WARN, "过期"),
                doctor.CheckResult("proxy", doctor.OK, "通"),
            ]
        )
        self.assertTrue(report.ok)
        self.assertFalse(report.needs_setup)
        self.assertEqual(len(report.warnings), 1)

    def test_to_dict_shape(self):
        report = doctor.DoctorReport(
            checks=[doctor.CheckResult("proxy", doctor.OK, "通")]
        )
        data = report.to_dict()
        self.assertIn("ok", data)
        self.assertIn("needs_setup", data)
        self.assertEqual(data["checks"][0]["name"], "proxy")


if __name__ == "__main__":
    unittest.main()
