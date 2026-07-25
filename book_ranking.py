"""版本优先级引擎：对 Z-Library 搜索结果按用户偏好排序、选出最优版本。

搜索结果 book dict 的相关字段（见 Zlibrary.py 的解析器）：
    extension / language / year / size / rating / title / author

设计原则（用户 2026-07-24 决策）：格式优先、默认不管语言。
偏好存独立文件 preferences.json，绝不塞进 .env（不碰 ZLIBRARY_* 命名红线）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).parent
PREFERENCES_FILE = PROJECT_DIR / "preferences.json"

# 默认偏好：格式优先，语言不限（空列表 = 不参与排序）
DEFAULT_PREFERENCES: dict[str, Any] = {
    "format_priority": ["epub", "pdf", "mobi", "azw3"],
    "language_priority": [],          # 空 = 不管语言
    "prefer_newer_year": True,         # True: 年份新的优先
    "size_preference": "none",         # none | larger | smaller
    "min_rating": 0.0,                 # 硬过滤：低于此评分的丢弃
}

# 排到末尾用的大数（未列进优先级的格式/语言）
_RANK_TAIL = 9999


def load_preferences(path: Path | str | None = None) -> dict[str, Any]:
    """读取偏好。缺文件返回默认；字段缺失用默认兜底（向后兼容）。"""
    pref_path = Path(path) if path is not None else PREFERENCES_FILE
    prefs = dict(DEFAULT_PREFERENCES)
    if pref_path.exists():
        try:
            with pref_path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for key in DEFAULT_PREFERENCES:
                    if key in data and data[key] is not None:
                        prefs[key] = data[key]
        except (json.JSONDecodeError, OSError):
            # 损坏或不可读 → 回退默认，不抛
            pass
    return _normalize_preferences(prefs)


def save_preferences(prefs: dict[str, Any], path: Path | str | None = None) -> dict[str, Any]:
    """写入偏好（只保留已知字段，规整后落盘）。返回规整后的偏好。"""
    pref_path = Path(path) if path is not None else PREFERENCES_FILE
    clean = _normalize_preferences({**DEFAULT_PREFERENCES, **(prefs or {})})
    with pref_path.open("w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    return clean


def _normalize_preferences(prefs: dict[str, Any]) -> dict[str, Any]:
    """把偏好规整成安全类型，容错脏输入。"""
    out = dict(DEFAULT_PREFERENCES)

    fmt = prefs.get("format_priority", DEFAULT_PREFERENCES["format_priority"])
    if isinstance(fmt, list):
        out["format_priority"] = [str(x).lower().lstrip(".").strip() for x in fmt if str(x).strip()]

    lang = prefs.get("language_priority", DEFAULT_PREFERENCES["language_priority"])
    if isinstance(lang, list):
        out["language_priority"] = [str(x).lower().strip() for x in lang if str(x).strip()]

    out["prefer_newer_year"] = bool(prefs.get("prefer_newer_year", True))

    size_pref = str(prefs.get("size_preference", "none")).lower().strip()
    out["size_preference"] = size_pref if size_pref in ("none", "larger", "smaller") else "none"

    try:
        out["min_rating"] = float(prefs.get("min_rating", 0) or 0)
    except (TypeError, ValueError):
        out["min_rating"] = 0.0

    return out


def parse_size_to_bytes(size: Any) -> int:
    """把 '1.2 MB' / '800 KB' / '1,024 bytes' 归一成字节。解析失败返回 0。"""
    if size is None:
        return 0
    if isinstance(size, (int, float)):
        return int(size)
    text = str(size).strip().lower().replace(",", "")
    if not text:
        return 0
    match = re.search(r"([\d.]+)\s*(tb|gb|mb|kb|b|bytes)?", text)
    if not match:
        return 0
    try:
        value = float(match.group(1))
    except ValueError:
        return 0
    unit = (match.group(2) or "b").rstrip("s")  # bytes -> byte -> byte; b -> b
    factor = {
        "tb": 1024 ** 4,
        "gb": 1024 ** 3,
        "mb": 1024 ** 2,
        "kb": 1024,
        "b": 1,
        "byte": 1,
    }.get(unit, 1)
    return int(value * factor)


def parse_rating(rating: Any) -> float:
    """把评分解析成 float。解析失败返回 0。"""
    if rating is None:
        return 0.0
    if isinstance(rating, (int, float)):
        return float(rating)
    match = re.search(r"[\d.]+", str(rating))
    if not match:
        return 0.0
    try:
        return float(match.group(0))
    except ValueError:
        return 0.0


def parse_year(year: Any) -> int:
    """把年份解析成 int。解析失败返回 0。"""
    if year is None:
        return 0
    match = re.search(r"\d{4}", str(year))
    if not match:
        return 0
    return int(match.group(0))


def _format_rank(book: dict, format_priority: list[str]) -> int:
    ext = str(book.get("extension", "")).lower().lstrip(".").strip()
    if ext in format_priority:
        return format_priority.index(ext)
    return _RANK_TAIL


def _language_rank(book: dict, language_priority: list[str]) -> int:
    if not language_priority:
        return 0  # 不管语言：所有书语言维度打平
    lang = str(book.get("language", "")).lower().strip()
    if lang in language_priority:
        return language_priority.index(lang)
    return _RANK_TAIL


def _sort_key(book: dict, prefs: dict[str, Any]):
    """生成排序键（元组，全部升序；越小越优先）。"""
    fmt_rank = _format_rank(book, prefs["format_priority"])
    lang_rank = _language_rank(book, prefs["language_priority"])

    year = parse_year(book.get("year"))
    # prefer_newer_year=True → 年份大的优先 → 取负值升序
    year_key = -year if prefs["prefer_newer_year"] else year

    size_bytes = parse_size_to_bytes(book.get("size"))
    if prefs["size_preference"] == "larger":
        size_key = -size_bytes
    elif prefs["size_preference"] == "smaller":
        # 0（未知体积）不该排到最前，给它变成极大
        size_key = size_bytes if size_bytes > 0 else float("inf")
    else:
        size_key = 0

    rating = parse_rating(book.get("rating"))
    rating_key = -rating  # 评分高优先

    return (fmt_rank, lang_rank, year_key, size_key, rating_key)


def rank_books(books: list[dict], prefs: dict[str, Any] | None = None) -> list[dict]:
    """按偏好排序。min_rating 作硬过滤。稳定排序保留原相对顺序作最终 tiebreak。"""
    if not books:
        return []
    prefs = _normalize_preferences(prefs) if prefs else load_preferences()

    min_rating = prefs["min_rating"]
    if min_rating > 0:
        pool = [b for b in books if parse_rating(b.get("rating")) >= min_rating]
        # 全被过滤掉则放弃过滤（宁可给结果也不空手）
        if not pool:
            pool = list(books)
    else:
        pool = list(books)

    return sorted(pool, key=lambda b: _sort_key(b, prefs))


def pick_best(books: list[dict], prefs: dict[str, Any] | None = None) -> dict | None:
    """返回排序后最优的一本，空列表返回 None。"""
    ranked = rank_books(books, prefs)
    return ranked[0] if ranked else None
