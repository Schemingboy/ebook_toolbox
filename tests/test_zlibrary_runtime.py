import tempfile
import unittest
from pathlib import Path

from zlibrary_runtime import (
    DEFAULT_COOKIES_FILE,
    ZLibraryAuth,
    create_zlibrary_client,
    find_pending_result_files,
    load_zlibrary_auth,
)


class ZlibraryRuntimeTests(unittest.TestCase):
    def test_load_zlibrary_auth_exchanges_email_password_for_tokens(self):
        captured_kwargs = {}

        class FakeClient:
            def __init__(self, **kwargs):
                captured_kwargs.update(kwargs)

            def getProfile(self):
                return {"success": True, "user": {"id": 42, "remix_userkey": "abc-token"}}

            def isLoggedIn(self):
                return True

        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "ZLIBRARY_EMAIL=test@example.com\n"
                "ZLIBRARY_PASSWORD=secret123\n",
                encoding="utf-8",
            )

            auth = load_zlibrary_auth(env_path=env_path, client_factory=FakeClient)

        self.assertEqual(captured_kwargs, {"email": "test@example.com", "password": "secret123", "domain": "", "proxy": ""})
        self.assertEqual(auth, ZLibraryAuth(remix_userid="42", remix_userkey="abc-token"))

    def test_load_zlibrary_auth_uses_existing_tokens_without_login(self):
        class FailingClient:
            def __init__(self, **kwargs):
                raise AssertionError("client_factory should not be called when remix tokens exist")

        with tempfile.TemporaryDirectory() as temp_dir:
            env_path = Path(temp_dir) / ".env"
            env_path.write_text(
                "ZLIBRARY_REMIX_USERID=12345\n"
                "ZLIBRARY_REMIX_USERKEY=token-value\n",
                encoding="utf-8",
            )

            auth = load_zlibrary_auth(env_path=env_path, client_factory=FailingClient)

        self.assertEqual(auth, ZLibraryAuth(remix_userid="12345", remix_userkey="token-value"))

    def test_create_zlibrary_client_requires_auth_and_passes_tokens(self):
        captured_kwargs = {}

        class FakeClient:
            def __init__(self, **kwargs):
                captured_kwargs.update(kwargs)

        with self.assertRaises(ValueError):
            create_zlibrary_client(ZLibraryAuth(), client_factory=FakeClient)

        client = create_zlibrary_client(
            ZLibraryAuth(remix_userid="123", remix_userkey="token"),
            client_factory=FakeClient,
        )

        self.assertIsInstance(client, FakeClient)
        # 默认挂上 cookies 自动刷新 hook，撞 Cloudflare 时客户端自己修
        hook = captured_kwargs.pop("auto_refresh_hook", None)
        self.assertTrue(callable(hook), "默认应注入 auto_refresh_hook")
        self.assertEqual(
            captured_kwargs,
            {
                "remix_userid": "123",
                "remix_userkey": "token",
                "domain": "",
                "proxy": "",
                "cookies_file": DEFAULT_COOKIES_FILE,
            },
        )

    def test_create_zlibrary_client_can_disable_auto_refresh(self):
        captured_kwargs = {}

        class FakeClient:
            def __init__(self, **kwargs):
                captured_kwargs.update(kwargs)

        create_zlibrary_client(
            ZLibraryAuth(remix_userid="123", remix_userkey="token"),
            client_factory=FakeClient,
            auto_refresh=False,
        )

        self.assertNotIn("auto_refresh_hook", captured_kwargs)

    def test_create_zlibrary_client_falls_back_when_factory_rejects_hook(self):
        """老的 client_factory（不接受 auto_refresh_hook）必须仍然可用。"""
        calls = []

        class LegacyClient:
            def __init__(self, remix_userid="", remix_userkey="", domain="",
                         proxy="", cookies_file=""):
                calls.append(remix_userid)

        client = create_zlibrary_client(
            ZLibraryAuth(remix_userid="777", remix_userkey="k"),
            client_factory=LegacyClient,
        )

        self.assertIsInstance(client, LegacyClient)
        self.assertEqual(calls, ["777"])

    def test_find_pending_result_files_filters_processed_entries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root_dir = Path(temp_dir)
            first = root_dir / "A" / "处理结果.txt"
            second = root_dir / "B" / "处理结果.txt"
            first.parent.mkdir()
            second.parent.mkdir()
            first.write_text("", encoding="utf-8")
            second.write_text("", encoding="utf-8")

            pending_files = find_pending_result_files(root_dir, processed_files={str(first)})

        self.assertEqual(pending_files, [second])


if __name__ == "__main__":
    unittest.main()
