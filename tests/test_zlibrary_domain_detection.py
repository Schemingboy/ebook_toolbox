"""域名自动探测：Cloudflare 挑战页不能当作域名不可用。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from Zlibrary import ZLibraryError, _detect_available_domain  # noqa: E402


def _resp(status: int) -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    return resp


class FakeSession:
    """记录请求过的 URL，按预设表返回状态码或抛异常。"""

    def __init__(self, outcomes: dict):
        self.outcomes = outcomes
        self.requested: list[str] = []

    def get(self, url, **kwargs):
        self.requested.append(url)
        outcome = self.outcomes[url]
        if isinstance(outcome, Exception):
            raise outcome
        return _resp(outcome)


class DetectAvailableDomainTest(unittest.TestCase):
    def test_prefers_first_http_200(self):
        session = FakeSession({
            "https://a.test": 200,
            "https://b.test": 200,
        })
        self.assertEqual(
            _detect_available_domain(["a.test", "b.test"], session=session),
            "a.test",
        )
        self.assertEqual(session.requested, ["https://a.test"])

    def test_cloudflare_challenge_is_a_candidate_not_a_failure(self):
        """503/513 说明域名可达，只是要刷 cookies —— 必须选中它而不是抛错。"""
        for status in (503, 513):
            with self.subTest(status=status):
                session = FakeSession({"https://a.test": status})
                self.assertEqual(
                    _detect_available_domain(["a.test"], session=session),
                    "a.test",
                )

    def test_http_200_wins_over_earlier_challenge(self):
        session = FakeSession({
            "https://a.test": 503,
            "https://b.test": 200,
        })
        self.assertEqual(
            _detect_available_domain(["a.test", "b.test"], session=session),
            "b.test",
        )

    def test_falls_back_to_first_challenged_domain(self):
        session = FakeSession({
            "https://a.test": requests.ConnectionError("boom"),
            "https://b.test": 513,
            "https://c.test": 503,
        })
        self.assertEqual(
            _detect_available_domain(["a.test", "b.test", "c.test"], session=session),
            "b.test",
        )

    def test_other_error_codes_are_not_candidates(self):
        session = FakeSession({"https://a.test": 404})
        with self.assertRaises(ZLibraryError):
            _detect_available_domain(["a.test"], session=session)

    def test_raises_only_when_nothing_is_reachable(self):
        session = FakeSession({
            "https://a.test": requests.ConnectionError("boom"),
            "https://b.test": requests.Timeout("slow"),
        })
        with self.assertRaisesRegex(ZLibraryError, "所有域名均不可用"):
            _detect_available_domain(["a.test", "b.test"], session=session)

    def test_uses_the_session_so_loaded_cookies_apply(self):
        """探测必须走同一 session，否则已加载的 Cloudflare cookies 白费。"""
        session = FakeSession({"https://a.test": 200})
        _detect_available_domain(["a.test"], session=session)
        self.assertEqual(session.requested, ["https://a.test"])


if __name__ == "__main__":
    unittest.main()
