"""ISBN 识别与规整。用于"按 ISBN 批量下载"入口。"""

from __future__ import annotations

import re


def normalize_isbn(s: str) -> str:
    """去掉连字符/空格，大写（ISBN-10 末位可能是 X）。"""
    return re.sub(r"[\s\-]", "", str(s)).upper()


def _valid_isbn10(digits: str) -> bool:
    if len(digits) != 10 or not re.fullmatch(r"\d{9}[\dX]", digits):
        return False
    total = 0
    for i, ch in enumerate(digits):
        val = 10 if ch == "X" else int(ch)
        total += val * (10 - i)
    return total % 11 == 0


def _valid_isbn13(digits: str) -> bool:
    if len(digits) != 13 or not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(digits):
        total += int(ch) * (1 if i % 2 == 0 else 3)
    return total % 10 == 0


def is_isbn(s: str) -> bool:
    """校验（含校验位）是否为合法 ISBN-10 或 ISBN-13。"""
    if not s:
        return False
    code = normalize_isbn(s)
    return _valid_isbn10(code) or _valid_isbn13(code)


def looks_like_isbn(s: str) -> bool:
    """宽松判断：去分隔符后是 10 或 13 位、且只含数字（末位可 X）。

    用于批量输入时把"像 ISBN 的行"和"书名行"分开，不强制校验位
    （用户手抄可能位数对但校验位错，仍想尝试搜索）。
    """
    if not s:
        return False
    code = normalize_isbn(s)
    return bool(re.fullmatch(r"\d{9}[\dX]", code) or re.fullmatch(r"\d{13}", code))


def extract_isbns(text: str) -> list[str]:
    """从多行文本里逐行提取 ISBN（一行一个），去重保序。"""
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        code = normalize_isbn(line)
        if looks_like_isbn(code) and code not in seen:
            seen.add(code)
            found.append(code)
    return found
