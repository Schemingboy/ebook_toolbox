"""cookie_manager 单元测试。

不碰真浏览器、不发网络请求：refresh_cookies 用 monkeypatch 替掉，
只验证「什么时候该刷」「刷完状态怎么算」「写 .env 保不保留旧行」这些纯逻辑。
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import cookie_manager


def _write_cookies(path: Path, *, with_login: bool = True, age_hours: float = 0.0):
    data = [{"name": "bsrv", "value": "x", "domain": "z-lib.by"}]
    if with_login:
        data.append({"name": "remix_userid", "value": "123", "domain": "z-lib.by"})
    path.write_text(json.dumps(data), encoding="utf-8")
    if age_hours:
        old = time.time() - age_hours * 3600
        os.utime(path, (old, old))
    return path


class CookiesStatusTests(unittest.TestCase):
    def test_missing_file_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            status = cookie_manager.cookies_status(Path(tmp) / "nope.json")
            self.assertFalse(status.exists)
            self.assertTrue(status.stale)
            self.assertIn("不存在", status.summary)

    def test_fresh_cookies_not_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_cookies(Path(tmp) / "c.json")
            status = cookie_manager.cookies_status(path)
            self.assertTrue(status.exists)
            self.assertTrue(status.has_login)
            self.assertEqual(status.count, 2)
            self.assertFalse(status.stale)

    def test_old_cookies_are_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_cookies(Path(tmp) / "c.json", age_hours=48)
            status = cookie_manager.cookies_status(path)
            self.assertTrue(status.stale)
            self.assertGreater(status.age_hours, 24)

    def test_cookies_without_login_are_stale(self):
        """有文件但没有 remix_userid，等于没登录，必须视为该刷。"""
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_cookies(Path(tmp) / "c.json", with_login=False)
            status = cookie_manager.cookies_status(path)
            self.assertTrue(status.exists)
            self.assertFalse(status.has_login)
            self.assertTrue(status.stale)

    def test_max_age_env_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_cookies(Path(tmp) / "c.json", age_hours=5)
            os.environ["ZLIBRARY_COOKIES_MAX_AGE_HOURS"] = "1"
            try:
                self.assertTrue(cookie_manager.cookies_status(path).stale)
            finally:
                del os.environ["ZLIBRARY_COOKIES_MAX_AGE_HOURS"]
            self.assertFalse(cookie_manager.cookies_status(path).stale)

    def test_corrupt_json_is_stale_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text("{not json", encoding="utf-8")
            status = cookie_manager.cookies_status(path)
            self.assertTrue(status.stale)


class EnsureFreshCookiesTests(unittest.TestCase):
    """ensure_fresh_cookies 调的是模块级 refresh_cookies，这里替掉它。"""

    def setUp(self):
        self._original = cookie_manager.refresh_cookies
        self.calls = []

    def tearDown(self):
        cookie_manager.refresh_cookies = self._original

    def _stub(self, **kwargs):
        self.calls.append(kwargs)
        return cookie_manager.CookiesStatus(
            exists=True, count=5, has_login=True, age_hours=0.0
        )

    def test_skips_refresh_when_fresh(self):
        cookie_manager.refresh_cookies = self._stub
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_cookies(Path(tmp) / "c.json")
            cookie_manager.ensure_fresh_cookies(cookies_file=path, log=lambda *a: None)
        self.assertEqual(self.calls, [], "cookies 还新鲜时不该刷新")

    def test_refreshes_when_stale(self):
        cookie_manager.refresh_cookies = self._stub
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_cookies(Path(tmp) / "c.json", age_hours=48)
            result = cookie_manager.ensure_fresh_cookies(
                cookies_file=path, log=lambda *a: None
            )
        self.assertEqual(len(self.calls), 1, "过期就该刷一次")
        self.assertFalse(result.stale)

    def test_force_refreshes_even_when_fresh(self):
        cookie_manager.refresh_cookies = self._stub
        with tempfile.TemporaryDirectory() as tmp:
            path = _write_cookies(Path(tmp) / "c.json")
            cookie_manager.ensure_fresh_cookies(
                cookies_file=path, log=lambda *a: None, force=True
            )
        self.assertEqual(len(self.calls), 1)


class WriteEnvTests(unittest.TestCase):
    def test_updates_key_and_keeps_other_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text(
                "# comment\nZLIBRARY_EMAIL=old@x.com\nZLIBRARY_PROXY=http://127.0.0.1:1\n",
                encoding="utf-8",
            )
            cookie_manager.write_env(
                {"ZLIBRARY_EMAIL": "new@x.com", "ZLIBRARY_DOMAIN": "z-lib.by"},
                env_path=env,
            )
            text = env.read_text(encoding="utf-8")
        self.assertIn("# comment", text)
        self.assertIn("ZLIBRARY_EMAIL=new@x.com", text)
        self.assertNotIn("old@x.com", text)
        self.assertIn("ZLIBRARY_PROXY=http://127.0.0.1:1", text)
        self.assertIn("ZLIBRARY_DOMAIN=z-lib.by", text)

    def test_empty_values_do_not_clobber(self):
        """向导没填的字段不能把已有配置清空。"""
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("ZLIBRARY_PROXY=http://127.0.0.1:7897\n", encoding="utf-8")
            cookie_manager.write_env({"ZLIBRARY_PROXY": ""}, env_path=env)
            text = env.read_text(encoding="utf-8")
        self.assertIn("ZLIBRARY_PROXY=http://127.0.0.1:7897", text)

    def test_creates_file_when_absent(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            cookie_manager.write_env({"ZLIBRARY_EMAIL": "a@b.c"}, env_path=env)
            self.assertTrue(env.exists())
            self.assertIn("ZLIBRARY_EMAIL=a@b.c", env.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
