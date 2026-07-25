import unittest

from isbn_utils import (
    normalize_isbn,
    is_isbn,
    looks_like_isbn,
    extract_isbns,
)


class TestNormalizeIsbn(unittest.TestCase):
    def test_strips_hyphens_and_spaces(self):
        self.assertEqual(normalize_isbn("978-7-115-42802-8"), "9787115428028")
        self.assertEqual(normalize_isbn("0 306 40615 2"), "0306406152")

    def test_uppercases_x(self):
        self.assertEqual(normalize_isbn("080442957x"), "080442957X")


class TestIsIsbn(unittest.TestCase):
    def test_valid_isbn13(self):
        # 真实合法 ISBN-13
        self.assertTrue(is_isbn("978-3-16-148410-0"))
        self.assertTrue(is_isbn("9787115428028"))

    def test_valid_isbn10(self):
        # 经典 ISBN-10（校验位 X）
        self.assertTrue(is_isbn("0-8044-2957-X"))
        self.assertTrue(is_isbn("0306406152"))

    def test_invalid_checksum(self):
        self.assertFalse(is_isbn("9787115428029"))  # 校验位错
        self.assertFalse(is_isbn("0306406153"))

    def test_wrong_length(self):
        self.assertFalse(is_isbn("12345"))
        self.assertFalse(is_isbn("978311542802"))  # 12 位

    def test_non_isbn(self):
        self.assertFalse(is_isbn(""))
        self.assertFalse(is_isbn("三体"))
        self.assertFalse(is_isbn("hello world"))


class TestLooksLikeIsbn(unittest.TestCase):
    def test_length_only_no_checksum(self):
        # 位数对但校验位错，宽松判断仍算"像"
        self.assertTrue(looks_like_isbn("9787115428029"))
        self.assertTrue(looks_like_isbn("0306406153"))

    def test_isbn10_with_x(self):
        self.assertTrue(looks_like_isbn("080442957X"))

    def test_rejects_wrong_length(self):
        self.assertFalse(looks_like_isbn("12345"))
        self.assertFalse(looks_like_isbn("三体"))
        self.assertFalse(looks_like_isbn(""))


class TestExtractIsbns(unittest.TestCase):
    def test_one_per_line(self):
        text = "978-3-16-148410-0\n0306406152\n"
        self.assertEqual(extract_isbns(text), ["9783161484100", "0306406152"])

    def test_skips_book_names_and_blanks(self):
        text = "《三体》\n9787115428028\n\n随便一行\n"
        self.assertEqual(extract_isbns(text), ["9787115428028"])

    def test_dedupes_preserving_order(self):
        text = "978-3-16-148410-0\n9783161484100\n0306406152\n"
        self.assertEqual(extract_isbns(text), ["9783161484100", "0306406152"])

    def test_empty(self):
        self.assertEqual(extract_isbns(""), [])


if __name__ == "__main__":
    unittest.main()
