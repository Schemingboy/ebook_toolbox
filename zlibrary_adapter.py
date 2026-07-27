"""
Z-Library 同步适配器

基于 `zlibrary` (PyPI) 异步包的同步封装，提供与原 Zlibrary.py 兼容的接口。
支持:
  - 邮箱密码登录 / Remix token 登录
  - HTTP/SOCKS5 代理链
  - Tor/Onion 路由
  - 域名配置

依赖: pip install zlibrary
"""

import asyncio
import logging
from typing import Optional

from Zlibrary import (
    ZLibraryError, LoginError, SearchError, DownloadError, QuotaExceededError
)

logger = logging.getLogger(__name__)

# 尝试导入 zlibrary 异步包
try:
    import zlibrary
    from zlibrary.libasync import AsyncZlib
    HAS_ZLIBRARY_PKG = True
except ImportError:
    HAS_ZLIBRARY_PKG = False


def _run_async(coro):
    """在已有或新事件循环中运行异步协程。"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # 已有运行中循环（如 Jupyter），新建一个
            return asyncio.run(coro)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


class ZlibraryAdapter:
    """Z-Library 同步客户端（基于 zlibrary 异步包）。"""

    def __init__(
        self,
        email: str = None,
        password: str = None,
        remix_userid: Optional[str] = None,
        remix_userkey: Optional[str] = None,
        domain: str = "",
        proxy: str = "",
        fallback_domains: list[str] = None,
        timeout: int = 30,
    ):
        if not HAS_ZLIBRARY_PKG:
            raise ImportError(
                "缺少依赖包 'zlibrary'。请运行: pip install zlibrary"
            )

        self._domain = domain
        self._proxy = proxy
        self._timeout = timeout
        self._loggedin = False
        self._userinfo = {}
        self._remaining = 10  # 默认剩余配额

        # 解析代理列表
        proxy_list = None
        if proxy:
            proxy_list = [proxy]

        # 创建异步客户端
        self._async_client = AsyncZlib(
            proxy_list=proxy_list,
        )

        # 设置自定义域名
        if domain:
            self._async_client.mirror = domain

        # 登录
        if email and password:
            self._login_sync(email, password)
        elif remix_userid and remix_userkey:
            self._login_with_token_sync(remix_userid, remix_userkey)

    def _login_sync(self, email: str, password: str):
        """同步登录。"""
        try:
            profile = _run_async(self._async_client.login(email, password))
            self._loggedin = True
            # 获取用户信息
            limits = _run_async(profile.get_limits())
            self._userinfo = {
                "name": "",
                "email": email,
                "downloads_limit": limits.get("daily_allowed", 10),
                "downloads_today": limits.get("daily_amount", 0),
            }
            # 从 cookies 获取 remix tokens
            if self._async_client.cookies:
                self._userinfo["remix_userid"] = self._async_client.cookies.get("remix_userid", "")
                self._userinfo["remix_userkey"] = self._async_client.cookies.get("remix_userkey", "")
            self._remaining = limits.get("daily_remaining", 10)
        except Exception as e:
            raise LoginError(f"登录失败: {e}")

    def _login_with_token_sync(self, remix_userid: str, remix_userkey: str):
        """使用 remix token 恢复会话（设置 cookies 后验证）。"""
        try:
            # 设置 cookies 到客户端
            self._async_client.cookies = {
                "remix_userid": str(remix_userid),
                "remix_userkey": remix_userkey,
            }
            # 验证：获取 profile
            url = f"{self._async_client.mirror}/"
            _run_async(self._async_client._r(url))
            self._loggedin = True

            limits = _run_async(self._async_client.profile.get_limits())
            self._userinfo = {
                "name": "",
                "email": "",
                "remix_userid": remix_userid,
                "remix_userkey": remix_userkey,
                "downloads_limit": limits.get("daily_allowed", 10),
                "downloads_today": limits.get("daily_amount", 0),
            }
            self._remaining = limits.get("daily_remaining", 10)
        except Exception as e:
            raise LoginError(f"Token 验证失败: {e}")

    # ── 公共 API ──────────────────────────────────────────

    def getProfile(self) -> dict:
        """获取用户信息（与旧 Zlibrary.py 兼容）。"""
        return {"success": self._loggedin, "user": self._userinfo}

    def getDownloadsLeft(self) -> int:
        """获取今日剩余下载次数。"""
        if self._loggedin and self._async_client.profile:
            try:
                limits = _run_async(self._async_client.profile.get_limits())
                self._remaining = limits.get("daily_remaining", self._remaining)
            except Exception:
                pass
        return self._remaining

    def isLoggedIn(self) -> bool:
        return self._loggedin

    def search(
        self,
        message: str = "",
        yearFrom: int = None,
        yearTo: int = None,
        languages: str = None,
        extensions: list[str] = None,
        order: str = None,
        page: int = None,
        limit: int = None,
    ) -> dict:
        """搜索图书。

        Returns:
            dict: 与旧 Zlibrary.py 兼容的格式
        """
        if not message:
            raise SearchError("搜索关键词不能为空")

        try:
            # 转换扩展名枚举
            ext_enums = []
            if extensions:
                from zlibrary.const import Extension
                ext_map = {e.value.upper(): e for e in Extension}
                for ext in extensions:
                    ext_upper = ext.upper().lstrip(".")
                    if ext_upper in ext_map:
                        ext_enums.append(ext_map[ext_upper])

            paginator = _run_async(
                self._async_client.search(
                    q=message,
                    from_year=yearFrom,
                    to_year=yearTo,
                    extensions=ext_enums or None,
                    count=limit or 10,
                )
            )

            books = []
            # 遍历分页器结果
            page_items = paginator.storage.get(paginator.page, [])
            for item in page_items:
                book = {
                    "id": item.get("id", ""),
                    "hash": "",
                    "title": item.get("name", ""),
                    "author": "",
                    "extension": item.get("extension", ""),
                    "year": item.get("year", ""),
                    "size": item.get("size", ""),
                    "cover": item.get("cover", ""),
                    "isbn": item.get("isbn", ""),
                    "publisher": item.get("publisher", ""),
                    "url": item.get("url", ""),
                }
                # 解析作者
                authors = item.get("authors", [])
                if authors:
                    if isinstance(authors, list):
                        book["author"] = "; ".join(
                            a.get("author", a) if isinstance(a, dict) else str(a)
                            for a in authors
                        )
                    else:
                        book["author"] = str(authors)
                books.append(book)

            return {
                "books": books,
                "total": paginator.total,
                "page": paginator.page,
            }

        except Exception as e:
            raise SearchError(f"搜索失败: {e}")

    def downloadBook(self, book: dict) -> tuple[Optional[str], Optional[bytes]]:
        """下载图书。

        Args:
            book: 包含 id (或 url) 的书籍信息字典

        Returns:
            (filename, content)
        """
        book_url = book.get("url", "")
        book_id = book.get("id", "")

        if not book_url and not book_id:
            raise DownloadError("缺少书籍 URL 或 ID")

        try:
            # 方法1: 通过 URL 获取书籍详情和下载链接
            from zlibrary.abs import BookItem

            if book_url and not book_url.startswith("http"):
                book_url = f"{self._async_client.mirror}{book_url}"

            # 使用 BookItem 获取书籍详情
            fetch_item = BookItem(self._async_client._r, self._async_client.mirror)
            if book_url:
                fetch_item["url"] = book_url
            elif book_id:
                fetch_item["url"] = f"{self._async_client.mirror}/book/{book_id}"
            else:
                raise DownloadError("无法构造书籍详情页 URL")

            parsed = _run_async(fetch_item.fetch())

            # 获取下载链接
            dl_url = parsed.get("download_url", "")
            if not dl_url or "unavailable" in dl_url.lower():
                raise DownloadError("下载链接不可用（可能需要 Tor）")

            # 下载文件
            import aiohttp
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }

            async def _do_download(url: str) -> tuple[str, bytes]:
                async with aiohttp.ClientSession(headers=headers) as sess:
                    async with sess.get(url) as resp:
                        content = await resp.read()
                        # 从 URL 或 Content-Disposition 获取文件名
                        fname = url.split("/")[-1].split("?")[0]
                        cd = resp.headers.get("Content-Disposition", "")
                        import re
                        m = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)', cd)
                        if m:
                            from Zlibrary import Zlibrary as _Z
                            fname = _Z._unquote_filename(m.group(1))
                        return fname, content

            import requests as req_lib
            fname, content = _run_async(_do_download(dl_url))

            return fname, content

        except Exception as e:
            raise DownloadError(f"下载失败: {e}")


def create_adapter(
    email: str = None,
    password: str = None,
    remix_userid: str = None,
    remix_userkey: str = None,
    domain: str = "",
    proxy: str = "",
) -> ZlibraryAdapter:
    """便捷工厂方法。"""
    return ZlibraryAdapter(
        email=email,
        password=password,
        remix_userid=remix_userid,
        remix_userkey=remix_userkey,
        domain=domain,
        proxy=proxy,
    )
