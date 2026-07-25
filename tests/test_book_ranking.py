"""book_ranking 版本优先级引擎的单元测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from book_ranking import (
    DEFAULT_PREFERENCES,
    load_preferences,
    parse_rating,
    parse_size_to_bytes,
    parse_year,
    pick_best,
    rank_books,
    save_preferences,
)


def _book(**kwargs):
    """构造一本书的最小 dict，缺省字段留空。"""
    base = {"title": "", "author": "", "extension": "", "language": "", "year": "", "size": "", "rating": ""}
    base.update(kwargs)
    return base


class TestParsers(unittest.TestCase):
    def test_parse_size_to_bytes(self):
        self.assertEqual(parse_size_to_bytes("1 KB"), 1024)
        self.assertEqual(parse_size_to_bytes("1.5 MB"), int(1.5 * 1024 * 1024))
        self.assertEqual(parse_size_to_bytes("2 GB"), 2 * 1024 ** 3)
        self.assertEqual(parse_size_to_bytes("1,024 bytes"), 1024)
        self.assertEqual(parse_size_to_bytes(2048), 2048)
        self.assertEqual(parse_size_to_bytes(""), 0)
        self.assertEqual(parse_size_to_bytes(None), 0)
        self.assertEqual(parse_size_to_bytes("garbage"), 0)

    def test_parse_rating(self):
        self.assertEqual(parse_rating("4.5"), 4.5)
        self.assertEqual(parse_rating("Rating: 3.2/5"), 3.2)
        self.assertEqual(parse_rating(5), 5.0)
        self.assertEqual(parse_rating(""), 0.0)
        self.assertEqual(parse_rating(None), 0.0)
        self.assertEqual(parse_rating("no digits"), 0.0)

    def test_parse_year(self):
        self.assertEqual(parse_year("2020"), 2020)
        self.assertEqual(parse_year("Published 2019"), 2019)
        self.assertEqual(parse_year(2021), 2021)
        self.assertEqual(parse_year(""), 0)
        self.assertEqual(parse_year(None), 0)
        self.assertEqual(parse_year("abc"), 0)


class TestFormatPriority(unittest.TestCase):
    def test_format_wins_over_everything(self):
        # 默认 format_priority = epub > pdf > mobi > azw3
        books = [
            _book(title="pdf ver", extension="pdf", year="2022"),
            _book(title="epub ver", extension="epub", year="2000"),
        ]
        best = pick_best(books, DEFAULT_PREFERENCES)
        self.assertEqual(best["extension"], "epub")

    def test_unknown_format_goes_last(self):
        books = [
            _book(title="djvu", extension="djvu"),
            _book(title="mobi", extension="mobi"),
        ]
        best = pick_best(books, DEFAULT_PREFERENCES)
        self.assertEqual(best["extension"], "mobi")

    def test_custom_format_priority(self):
        prefs = {**DEFAULT_PREFERENCES, "format_priority": ["pdf", "epub"]}
        books = [
            _book(title="epub", extension="epub"),
            _book(title="pdf", extension="pdf"),
        ]
        best = pick_best(books, prefs)
        self.assertEqual(best["extension"], "pdf")


class TestLanguagePriority(unittest.TestCase):
    def test_language_ignored_by_default(self):
        # 默认 language_priority=[] → 语言不影响，格式相同则看年份
        prefs = DEFAULT_PREFERENCES
        books = [
            _book(title="cn", extension="epub", language="chinese", year="2010"),
            _book(title="en", extension="epub", language="english", year="2020"),
        ]
        best = pick_best(books, prefs)
        # 语言打平 → 年份新的（2020 english）胜出
        self.assertEqual(best["title"], "en")

    def test_language_priority_applies(self):
        prefs = {**DEFAULT_PREFERENCES, "language_priority": ["english"]}
        books = [
            _book(title="cn", extension="epub", language="chinese", year="2020"),
            _book(title="en", extension="epub", language="english", year="2000"),
        ]
        best = pick_best(books, prefs)
        # english 优先于年份
        self.assertEqual(best["title"], "en")


class TestYearAndSize(unittest.TestCase):
    def test_prefer_newer_year(self):
        prefs = {**DEFAULT_PREFERENCES, "prefer_newer_year": True}
        books = [
            _book(extension="epub", year="2001", title="old"),
            _book(extension="epub", year="2021", title="new"),
        ]
        self.assertEqual(pick_best(books, prefs)["title"], "new")

    def test_prefer_older_year(self):
        prefs = {**DEFAULT_PREFERENCES, "prefer_newer_year": False}
        books = [
            _book(extension="epub", year="2001", title="old"),
            _book(extension="epub", year="2021", title="new"),
        ]
        self.assertEqual(pick_best(books, prefs)["title"], "old")

    def test_size_larger(self):
        prefs = {**DEFAULT_PREFERENCES, "size_preference": "larger"}
        books = [
            _book(extension="epub", year="2020", size="1 MB", title="small"),
            _book(extension="epub", year="2020", size="5 MB", title="big"),
        ]
        self.assertEqual(pick_best(books, prefs)["title"], "big")

    def test_size_smaller_ignores_unknown(self):
        prefs = {**DEFAULT_PREFERENCES, "size_preference": "smaller"}
        books = [
            _book(extension="epub", year="2020", size="", title="unknown"),
            _book(extension="epub", year="2020", size="3 MB", title="known-small"),
        ]
        # 未知体积不该抢到 smaller 的第一
        self.assertEqual(pick_best(books, prefs)["title"], "known-small")


class TestMinRating(unittest.TestCase):
    def test_min_rating_filters(self):
        prefs = {**DEFAULT_PREFERENCES, "min_rating": 4.0}
        books = [
            _book(extension="epub", rating="3.0", title="low"),
            _book(extension="pdf", rating="4.5", title="high"),
        ]
        # low 被过滤，虽然 epub 格式更优也不选
        best = pick_best(books, prefs)
        self.assertEqual(best["title"], "high")

    def test_min_rating_all_filtered_falls_back(self):
        prefs = {**DEFAULT_PREFERENCES, "min_rating": 5.0}
        books = [
            _book(extension="epub", rating="3.0", title="a"),
            _book(extension="pdf", rating="4.0", title="b"),
        ]
        # 全被过滤 → 放弃过滤，仍按格式返回 epub
        best = pick_best(books, prefs)
        self.assertEqual(best["title"], "a")


class TestEdgeCases(unittest.TestCase):
    def test_empty_list(self):
        self.assertEqual(rank_books([], DEFAULT_PREFERENCES), [])
        self.assertIsNone(pick_best([], DEFAULT_PREFERENCES))

    def test_missing_fields(self):
        # 完全缺字段的 book 不应崩
        books = [{"title": "bare"}, _book(extension="epub", title="full")]
        best = pick_best(books, DEFAULT_PREFERENCES)
        self.assertEqual(best["title"], "full")

    def test_stable_order_tiebreak(self):
        # 完全同权 → 保持原顺序
        books = [
            _book(extension="epub", year="2020", title="first"),
            _book(extension="epub", year="2020", title="second"),
        ]
        ranked = rank_books(books, DEFAULT_PREFERENCES)
        self.assertEqual([b["title"] for b in ranked], ["first", "second"])


class TestPreferencesIO(unittest.TestCase):
    def test_load_missing_returns_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "nope.json"
            prefs = load_preferences(p)
            self.assertEqual(prefs["format_priority"], DEFAULT_PREFERENCES["format_priority"])

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "preferences.json"
            saved = save_preferences({"format_priority": ["pdf", "epub"], "min_rating": 4}, p)
            self.assertEqual(saved["format_priority"], ["pdf", "epub"])
            self.assertEqual(saved["min_rating"], 4.0)
            loaded = load_preferences(p)
            self.assertEqual(loaded["format_priority"], ["pdf", "epub"])
            self.assertEqual(loaded["min_rating"], 4.0)

    def test_load_partial_fills_defaults(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "preferences.json"
            with p.open("w", encoding="utf-8") as f:
                json.dump({"format_priority": ["mobi"]}, f)
            loaded = load_preferences(p)
            self.assertEqual(loaded["format_priority"], ["mobi"])
            # 缺失字段回落默认
            self.assertEqual(loaded["language_priority"], [])
            self.assertTrue(loaded["prefer_newer_year"])

    def test_load_corrupt_returns_default(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "preferences.json"
            p.write_text("{ not valid json", encoding="utf-8")
            loaded = load_preferences(p)
            self.assertEqual(loaded["format_priority"], DEFAULT_PREFERENCES["format_priority"])

    def test_normalize_dirty_format_list(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "preferences.json"
            with p.open("w", encoding="utf-8") as f:
                json.dump({"format_priority": [".EPUB", "PDF ", ""]}, f)
            loaded = load_preferences(p)
            self.assertEqual(loaded["format_priority"], ["epub", "pdf"])


if __name__ == "__main__":
    unittest.main()
