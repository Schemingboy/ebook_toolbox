"""下载文件名的编码还原。

两类损坏来源不同、修法也不同，必须分开锁住：
  - Content-Disposition 发裸 UTF-8 字节 → requests 用 latin-1 读头 → mojibake（可逆）
  - Content-Disposition 发非 UTF-8 的 percent-encoding → 若按 UTF-8 解就变 U+FFFD（不可逆）
"""

import unittest
from unittest.mock import MagicMock

from Zlibrary import Zlibrary

REPLACEMENT = "�"


def _resp(content_disposition: str):
    resp = MagicMock()
    resp.headers = {"Content-Disposition": content_disposition}
    return resp


def _extract(cd: str, book: dict = None) -> str:
    return Zlibrary._extract_filename(
        Zlibrary, _resp(cd), book if book is not None else {}
    )


class UnquoteFilenameTest(unittest.TestCase):
    def test_latin1_percent_encoding_is_recovered_not_replaced(self):
        """实测过的真实故障：服务器按 latin-1 做 percent-encoding。

        按 UTF-8 解会得到 'H�bitos_At�micos.epub'——字符已丢失，
        后续任何修复都救不回来，所以必须在解码这一步就退到 latin-1。
        """
        got = Zlibrary._unquote_filename("H%E1bitos_At%F3micos.epub")
        self.assertEqual(got, "Hábitos_Atómicos.epub")
        self.assertNotIn(REPLACEMENT, got)

    def test_utf8_percent_encoding_still_wins(self):
        """中文名是合法 UTF-8，必须走第一个候选，不能被 latin-1 抢走。"""
        got = Zlibrary._unquote_filename("%E7%90%83%E7%8A%B6%E9%97%AA%E7%94%B5.epub")
        self.assertEqual(got, "球状闪电.epub")

    def test_cp1252_specific_bytes(self):
        """0x92/0x97 在 latin-1 是控制符，在 cp1252 才是可见标点。"""
        self.assertEqual(
            Zlibrary._unquote_filename("na%92ive%97dash.epub"),
            "na’ive—dash.epub",
        )

    def test_plain_ascii_is_untouched(self):
        self.assertEqual(
            Zlibrary._unquote_filename("Atomic_Habits.epub"), "Atomic_Habits.epub"
        )

    def test_never_emits_replacement_character(self):
        """兜底保证：任何输入都不该产出 U+FFFD。"""
        for raw in (
            "H%E1bitos.epub",
            "%FF%FE%00.epub",
            "%E7%90%83.epub",
            "%zz%not-hex.epub",
        ):
            self.assertNotIn(REPLACEMENT, Zlibrary._unquote_filename(raw), raw)


class ExtractFilenameTest(unittest.TestCase):
    def test_latin1_encoded_header_end_to_end(self):
        got = _extract('attachment; filename="H%E1bitos_At%F3micos.epub"')
        self.assertEqual(got, "Hábitos_Atómicos.epub")
        self.assertNotIn(REPLACEMENT, got)

    def test_mojibake_header_still_fixed(self):
        """旧的 latin-1 误解码路径不能因为这次改动而回归。"""
        mojibake = "球状闪电.epub".encode("utf-8").decode("latin-1")
        self.assertEqual(
            _extract(f'attachment; filename="{mojibake}"'), "球状闪电.epub"
        )

    def test_falls_back_to_book_title(self):
        got = _extract("", {"title": "Atomic Habits", "extension": "epub"})
        self.assertEqual(got, "Atomic_Habits.epub")


if __name__ == "__main__":
    unittest.main()
