"""
Z-Library 同步客户端

通过 HTML 页面抓取与当前 Z-Library 站点交互，替代已失效的旧 JSON API。
支持自定义域名、HTTP/SOCKS5 代理、Cookie 持久化、域名自动降级。

用法:
    # 邮箱密码登录
    client = Zlibrary(email="xxx@mail.com", password="pass")
    client.getProfile()
    client.search("Python", extensions=["epub"])

    # Token 登录（推荐）
    client = Zlibrary(remix_userid="12345", remix_userkey="abc")
    client.getDownloadsLeft()

    # 自定义域名 + 代理
    client = Zlibrary(remix_userid="12345", remix_userkey="abc",
                      domain="z-lib.id", proxy="socks5://127.0.0.1:1080")
"""

import re
import json
import time
import logging
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote
from typing import Optional

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_DOMAINS = [
    "z-lib.by",
    "z-library.gy",
    "zh.zlib.li",
    "zh.z-lib.rest",
]

LOGIN_ENDPOINTS = [
    "/rpc.php",
    "/eapi/user/login",
]

# 已知不支持下载的镜像站点（仅元数据/搜索）
DOMAIN_BLACKLIST = {"z-lib.id", "z-lib.cx", "z-lib.li", "z-lib.io"}

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


class ZLibraryError(Exception):
    """Z-Library 操作通用异常。"""


class LoginError(ZLibraryError):
    """登录失败。"""


class SearchError(ZLibraryError):
    """搜索失败。"""


class DownloadError(ZLibraryError):
    """下载失败。"""


class QuotaExceededError(ZLibraryError):
    """今日下载配额已用完。"""


CLOUDFLARE_STATUS_CODES = (503, 513)


def _detect_available_domain(
    domains: list[str],
    proxy: Optional[str] = None,
    timeout: int = 5,
    session: Optional[requests.Session] = None,
) -> str:
    """自动探测可用的域名，返回第一个能访问的。

    Cloudflare 挑战页（503/513）算「可达，待刷 cookies」而非不可用：探测发生在
    __init__ 里，比自愈链（_try_auto_refresh）更早，若在这里判死就会直接抛
    「所有域名均不可用」，刷新 cookies 的机会都没有。只有全部域名都拿不到
    响应时才算真的网络/代理问题。
    """
    if session is not None:
        get = session.get
        kwargs = {"timeout": timeout}
    else:
        get = requests.get
        kwargs = {
            "timeout": timeout,
            "headers": {"User-Agent": USER_AGENT},
            "proxies": {"http": proxy, "https": proxy} if proxy else None,
        }

    challenged: list[str] = []
    for domain in domains:
        try:
            resp = get(f"https://{domain}", **kwargs)
        except requests.RequestException as exc:
            logger.debug("域名不可达: %s (%s)", domain, exc)
            continue
        if resp.status_code == 200:
            logger.info("可用域名: %s", domain)
            return domain
        if resp.status_code in CLOUDFLARE_STATUS_CODES:
            logger.info("域名可达但撞 Cloudflare 验证，列为候选: %s", domain)
            challenged.append(domain)
        else:
            logger.debug("域名返回 HTTP %s: %s", resp.status_code, domain)

    if challenged:
        logger.info("选用候选域名 %s，稍后刷新 cookies 过 Cloudflare", challenged[0])
        return challenged[0]

    raise ZLibraryError(
        f"所有域名均不可用: {domains}。请检查网络连接或配置代理。"
    )


class Zlibrary:
    """Z-Library 同步客户端（基于页面抓取）。"""

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
        cookies_file: str = "",
        auto_refresh_hook=None,
    ):
        """
        Args:
            email: Z-Library 账号邮箱
            password: Z-Library 密码
            remix_userid: Remix token 的用户 ID
            remix_userkey: Remix token 的密钥
            domain: 指定 API 域名（留空则自动探测）
            proxy: 代理地址，如 socks5://127.0.0.1:1080
            fallback_domains: 备用域名列表
            timeout: HTTP 请求超时（秒）
            cookies_file: Cookie 文件路径（从 Playwright 浏览器导出），
                          用于绕过 Cloudflare 验证
            auto_refresh_hook: 可选回调。撞到 Cloudflare 拦截时调用它刷新
                          cookies，然后自动重试一次请求。传 None 则保持旧行为
                          （直接抛错）。签名: () -> bool，返回是否刷新成功。
        """
        self._domain = domain
        self._proxy = proxy
        self._fallback_domains = fallback_domains or []
        self._timeout = timeout
        self._loggedin = False
        self._userinfo = {}  # 缓存用户信息
        self._cookies_file = cookies_file
        self._auto_refresh_hook = auto_refresh_hook
        # 防重入：刷新过程本身会发请求，若那些请求也触发刷新就会无限递归
        self._refreshing = False

        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })
        if proxy:
            self._session.proxies = {"http": proxy, "https": proxy}

        # 从文件加载浏览器 cookies（绕过 Cloudflare）
        self._load_cookies_file()

        # 自动探测域名
        if not self._domain:
            all_domains = self._fallback_domains or DEFAULT_DOMAINS.copy()
            self._domain = _detect_available_domain(
                all_domains, proxy, timeout=5, session=self._session
            )

        logger.info("使用域名: %s", self._domain)

        # 存储凭据供自动重连使用
        self._email = email or ""
        self._password = password or ""
        self._remix_userid = remix_userid or ""
        self._remix_userkey = remix_userkey or ""

        if email and password:
            self.login(email, password)
        elif remix_userid and remix_userkey:
            self.login_with_token(remix_userid, remix_userkey)

    # ── HTTP 工具 ────────────────────────────────────────────

    def _resolve_url(self, path_or_url: str) -> str:
        """将路径或完整 URL 解析为绝对 URL。"""
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            return path_or_url
        return f"https://{self._domain}{path_or_url}"

    def _get(self, path_or_url: str, **kwargs) -> requests.Response:
        timeout = kwargs.pop("timeout", self._timeout)
        resp = self._session.get(
            self._resolve_url(path_or_url), timeout=timeout, **kwargs
        )
        if not self._is_cloudflare_blocked(resp):
            return resp

        # 撞到 Cloudflare：尝试自动刷新 cookies 后重试一次。
        # 只重试一次，且 _refreshing 期间不再触发，避免递归风暴。
        if self._try_auto_refresh():
            resp = self._session.get(
                self._resolve_url(path_or_url), timeout=timeout, **kwargs
            )
            if not self._is_cloudflare_blocked(resp):
                return resp
            raise ZLibraryError(
                "已自动刷新 cookies，但仍被 Cloudflare 拦截。"
                "可能 remix token 已失效或代理不通——请在 Web 界面「设置」重新填写账号并测试连接。"
            )

        raise ZLibraryError(
            "Cloudflare 验证拦截，且自动刷新 cookies 未成功。"
            "请在 Web 界面点「刷新 Cookies」，或检查 .env 里的代理配置。"
        )

    def _try_auto_refresh(self) -> bool:
        """调用注入的 hook 刷新 cookies 并重载到 session。返回是否刷新成功。"""
        if not self._auto_refresh_hook or self._refreshing:
            return False
        self._refreshing = True
        try:
            logger.info("撞到 Cloudflare，正在自动刷新 cookies…")
            ok = bool(self._auto_refresh_hook())
            if ok:
                # 清掉旧 cookie 再载入新的，避免同名 cookie 残留导致仍被拦
                self._session.cookies.clear()
                self._load_cookies_file()
                if self._remix_userid and self._remix_userkey:
                    self._session.cookies.set(
                        "remix_userid", str(self._remix_userid), domain=self._domain
                    )
                    self._session.cookies.set(
                        "remix_userkey", self._remix_userkey, domain=self._domain
                    )
                self._userinfo = {}  # 配额等缓存作废
                logger.info("cookies 刷新完成，重试请求")
            return ok
        except Exception as exc:  # 刷新失败不掩盖原始的拦截错误
            logger.warning("自动刷新 cookies 失败: %s", exc)
            return False
        finally:
            self._refreshing = False

    def _post(self, path_or_url: str, data=None, json=None, **kwargs) -> requests.Response:
        return self._session.post(
            self._resolve_url(path_or_url),
            data=data,
            json=json,
            timeout=kwargs.pop("timeout", self._timeout),
            **kwargs,
        )

    # ── Cookie 持久化（绕过 Cloudflare） ─────────────────────

    def _is_cloudflare_blocked(self, resp: requests.Response) -> bool:
        """检查响应是否被 Cloudflare 拦截。"""
        if resp.status_code in CLOUDFLARE_STATUS_CODES:
            text_lower = resp.text.lower()
            if "checking your browser" in text_lower or "diamwall" in text_lower:
                return True
        return False

    def _load_cookies_file(self):
        """从文件加载浏览器 cookies。"""
        if not self._cookies_file:
            return False
        cookie_path = Path(self._cookies_file)
        if not cookie_path.exists():
            logger.warning("Cookie 文件不存在: %s", self._cookies_file)
            return False
        try:
            import json as _json
            data = _json.loads(cookie_path.read_text(encoding="utf-8"))
            for item in data:
                domain = item.get("domain", self._domain)
                self._session.cookies.set(
                    item["name"], item["value"],
                    domain=domain.lstrip("."),
                )
            logger.info("已加载 %d 个 cookies（来自 %s）", len(data), self._cookies_file)
            return True
        except Exception as e:
            logger.warning("加载 cookie 文件失败: %s", e)
            return False

    def save_cookies_file(self, file_path: str = ""):
        """将当前 session cookies 保存到文件，供后续使用。"""
        file_path = file_path or self._cookies_file or "zlibrary_cookies.json"
        cookies_data = [
            {"name": c.name, "value": c.value, "domain": c.domain}
            for c in self._session.cookies
        ]
        Path(file_path).write_text(
            __import__("json").dumps(cookies_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("已保存 %d 个 cookies 到 %s", len(cookies_data), file_path)
        return file_path

    # ── 登录 ────────────────────────────────────────────────

    def login(self, email: str, password: str) -> dict:
        """使用邮箱密码登录。

        自动尝试以下方式:
        1. RPC 登录 (/rpc.php 或 /eapi/user/login)
        2. 表单登录 (适用于 z-lib.id 等镜像站)
        """
        # 先尝试 RPC 登录
        try:
            return self._login_via_rpc(email, password)
        except LoginError:
            # RPC 失败则尝试表单登录
            return self._login_via_form(email, password)

    def login_with_token(self, remix_userid: str, remix_userkey: str) -> dict:
        """使用已获取的 remix token 恢复会话。"""
        # 设置 cookie 后验证
        self._session.cookies.set("remix_userid", str(remix_userid), domain=self._domain)
        self._session.cookies.set("remix_userkey", remix_userkey, domain=self._domain)

        try:
            profile = self._fetch_profile()
        except ZLibraryError as e:
            # Cloudflare 拦截等网络错误
            raise LoginError(
                f"无法验证 Token（网络被拦截）: {e}\n"
                "请运行 refresh_zlibrary_cookies.py 更新浏览器 cookies。"
            )

        if profile.get("success"):
            self._loggedin = True
            self._userinfo = profile.get("user", {})
            return profile
        else:
            error_msg = profile.get("error", "")
            if "Cloudflare" in error_msg or "拦截" in error_msg:
                raise LoginError(
                    f"Token 验证被 Cloudflare 拦截。\n"
                    "请运行: .venv\\Scripts\\python refresh_zlibrary_cookies.py"
                )
            raise LoginError(
                f"Token 验证失败: {error_msg}\n"
                "请重新获取 remix token（运行 refresh_zlibrary_cookies.py）"
            )

    def _login_via_form(self, email: str, password: str) -> dict:
        """通过表单登录（适用于 z-lib.id 等使用 CSRF 的镜像站）。"""
        # 1. GET 登录页提取 CSRF token
        try:
            resp = self._get("/login")
            soup = BeautifulSoup(resp.text, "lxml")
            form = soup.find("form")
            if not form:
                raise LoginError("未找到登录表单")

            token_input = form.find("input", {"name": "_token"}) or form.find("input", {"name": re.compile(r"csrf|token", re.I)})
            csrf_token = token_input.get("value", "") if token_input else ""

            form_action = form.get("action", "/login")

            # 2. POST 登录
            login_data = {
                "_token": csrf_token,
                "email": email,
                "password": password,
            }
            login_resp = self._post(form_action, data=login_data, allow_redirects=True)

            # 3. 验证登录结果
            success = False

            # 检查 remix cookies（官方域名）
            for cookie in self._session.cookies:
                if cookie.name == "remix_userid":
                    self._userinfo["remix_userid"] = cookie.value
                    self._userinfo["id"] = cookie.value
                elif cookie.name == "remix_userkey":
                    self._userinfo["remix_userkey"] = cookie.value

            if self._userinfo.get("remix_userid") and self._userinfo.get("remix_userkey"):
                success = True

            # 检查是否已登录（跳离了 /login 页面）
            if not success:
                final_url = login_resp.url.rstrip("/")
                home_url = f"https://{self._domain}"
                if final_url.startswith(home_url) and "/login" not in final_url:
                    success = True

            if not success:
                raise LoginError("表单登录失败（可能账号或密码错误）")

            self._loggedin = True

            # 获取用户信息
            profile = self._fetch_profile()
            self._userinfo.update(profile.get("user", {}))
            return profile

        except LoginError:
            raise
        except Exception as e:
            raise LoginError(f"表单登录异常: {e}")

    def _login_via_rpc(self, email: str, password: str) -> dict:
        """通过 /rpc.php 登录（当前 Z-Library 主流的登录方式）。"""
        data = {
            "isModal": True,
            "email": email,
            "password": password,
            "site_mode": "books",
            "action": "login",
            "isSingleLogin": 1,
            "redirectUrl": "",
            "gg_json_mode": 1,
        }
        # 尝试多个登录端点
        login_paths = LOGIN_ENDPOINTS
        if self._domain not in ("1lib.sk",):
            login_paths = ["/rpc.php"]

        last_error = None
        for path in login_paths:
            try:
                resp = self._post(path, data=data)
                result = resp.json()
                if result.get("response", {}).get("validationError"):
                    last_error = LoginError(
                        f"登录被拒: {result['response'].get('validationError', '未知错误')}"
                    )
                    continue

                # 从 cookie jar 提取 remix token
                for cookie in self._session.cookies:
                    if cookie.name == "remix_userid":
                        uid = cookie.value
                    elif cookie.name == "remix_userkey":
                        ukey = cookie.value

                if hasattr(self._session.cookies, "list_domains"):
                    jar = self._session.cookies
                else:
                    jar = {}

                # 直接解析响应中的 remix token
                userid = None
                userkey = None
                for cookie in self._session.cookies:
                    if cookie.name == "remix_userid":
                        userid = cookie.value
                    elif cookie.name == "remix_userkey":
                        userkey = cookie.value

                if userid and userkey:
                    self._loggedin = True
                    profile = self._fetch_profile()
                    self._userinfo = profile.get("user", {})
                    return profile
                else:
                    last_error = LoginError("登录成功但未获取到 remix token")
                    continue

            except json.JSONDecodeError:
                last_error = LoginError(f"登录端点 {path} 返回非 JSON 响应")
                continue
            except requests.RequestException as e:
                last_error = LoginError(f"登录端点 {path} 请求失败: {e}")
                continue

        raise last_error or LoginError("所有登录端点均失败")

    # ── 用户信息 ────────────────────────────────────────────

    def _fetch_profile_via_eapi(self) -> Optional[dict]:
        """通过 /eapi/user/profile 获取用户信息（JSON，含真实下载配额）。

        实测该接口返回 {"success": 1, "user": {..., "downloads_today": int,
        "downloads_limit": int, ...}}。成功返回 profile dict，任何异常/非预期
        响应返回 None，由调用方回退到 HTML 抓取。
        """
        try:
            resp = self._get("/eapi/user/profile")
            if resp.status_code != 200:
                return None
            data = resp.json()
            if not data.get("success") or "user" not in data:
                return None
            src = data["user"]
            user = {
                "id": str(src.get("id", "")),
                "name": src.get("name", ""),
                "email": src.get("email", ""),
                "remix_userid": "",
                "remix_userkey": src.get("remix_userkey", ""),
                "downloads_limit": int(src.get("downloads_limit", 10)),
                "downloads_today": int(src.get("downloads_today", 0)),
                "kindle_email": src.get("kindle_email", ""),
            }
            # 从 cookie 补全 remix token
            for cookie in self._session.cookies:
                if cookie.name == "remix_userid":
                    user["remix_userid"] = cookie.value
                    if not user["id"]:
                        user["id"] = cookie.value
            return {"success": True, "user": user}
        except (json.JSONDecodeError, ValueError, ZLibraryError, requests.RequestException):
            return None

    def _fetch_profile(self) -> dict:
        """获取用户信息。

        优先调用 /eapi/user/profile（JSON 接口，含真实的 downloads_today /
        downloads_limit），失败再回退到 HTML 抓取。
        """
        eapi_result = self._fetch_profile_via_eapi()
        if eapi_result is not None:
            return eapi_result

        try:
            resp = self._get("/")

            # 从页面中提取用户信息（登录后页面会包含用户信息）
            soup = BeautifulSoup(resp.text, "lxml")

            # 尝试从多个地方提取用户信息
            user = {
                "id": "",
                "name": "",
                "email": "",
                "remix_userid": "",
                "remix_userkey": "",
                "downloads_limit": 10,
                "downloads_today": 0,
                "kindle_email": "",
            }

            # 从 cookie 获取 token
            for cookie in self._session.cookies:
                if cookie.name == "remix_userid":
                    user["id"] = cookie.value
                    user["remix_userid"] = cookie.value
                elif cookie.name == "remix_userkey":
                    user["remix_userkey"] = cookie.value

            # 从页面提取用户名
            name_elem = soup.select_one(".user-name, .profile-name, [class*=user][class*=name]")
            if name_elem:
                user["name"] = name_elem.text.strip()

            # 尝试访问用户信息页面
            for info_url in ["/users/profile", "/profile", "/user/profile"]:
                try:
                    info_resp = self._get(info_url)
                    if info_resp.status_code == 200:
                        info_soup = BeautifulSoup(info_resp.text, "lxml")
                        # 提取邮箱
                        email_input = info_soup.select_one('input[name="email"], input[type="email"]')
                        if email_input:
                            user["email"] = email_input.get("value", "")
                        break
                except requests.RequestException:
                    continue

            return {"success": True, "user": user}

        except Exception as e:
            return {"success": False, "error": str(e)}

    def getProfile(self, force_refresh: bool = False) -> dict:
        """获取用户信息。

        force_refresh=True 时跳过缓存重新抓取（下载配额会随下载递减，
        查询剩余次数必须实时刷新，不能用首次登录的缓存快照）。
        """
        if self._userinfo and not force_refresh:
            return {"success": True, "user": self._userinfo}
        profile = self._fetch_profile()
        if profile.get("success"):
            self._userinfo = profile.get("user", {})
        return profile

    def getDownloadsLeft(self) -> int:
        """获取今日剩余下载次数（实时刷新，不用缓存）。"""
        try:
            profile = self.getProfile(force_refresh=True)
            if profile.get("success"):
                user = profile["user"]
                limit = user.get("downloads_limit", 10)
                today = user.get("downloads_today", 0)
                return max(0, limit - today)

            # 备用：从下载页面抓取限额信息
            resp = self._get("/users/downloads")
            soup = BeautifulSoup(resp.text, "lxml")

            dcount = soup.select_one(".d-count, .download-count, [class*=download][class*=count]")
            if dcount:
                parts = dcount.text.strip().split("/")
                if len(parts) == 2:
                    return max(0, int(parts[1]) - int(parts[0]))

            return 10  # 默认值
        except Exception:
            return 10

    # ── 搜索 ────────────────────────────────────────────────

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
            dict: {"books": [...], "total": int, "page": int}
            每 book 的格式: {"id": str, "hash": str, "title": str, "author": str,
                            "extension": str, "year": str, "size": str, "cover": str}
        """
        if not message:
            raise SearchError("搜索关键词不能为空")

        # 构造搜索 URL（支持 /s?q= 和 /s/{q} 两种格式）
        q = quote(message)
        is_mirror = self._domain in DOMAIN_BLACKLIST

        if is_mirror:
            path = f"/s?q={q}"
        else:
            path = f"/s/{q}?"

        if yearFrom:
            path += f"{'&' if '?' in path else '?'}yearFrom={yearFrom}"
        if yearTo:
            path += f"&yearTo={yearTo}"
        if languages:
            path += f"&languages%5B%5D={languages}"
        # 镜像站不支持 URL 级别的扩展名过滤（会导致重定向）
        if not is_mirror and extensions:
            for ext in extensions:
                path += f"&extensions%5B%5D={ext}"
        if order:
            path += f"&order={order}"
        if page:
            path += f"&page={page}"

        try:
            resp = self._get(path)

            # 检测重定向到 /profile（会话可能已过期）
            if resp.url.rstrip("/").endswith("/profile") or resp.url.rstrip("/").endswith("/login"):
                logger.warning("搜索请求被重定向到 %s，尝试重新登录", resp.url)
                if self._email and self._password:
                    self.login(self._email, self._password)
                    resp = self._get(path)
                elif self._remix_userid and self._remix_userkey:
                    self.login_with_token(self._remix_userid, self._remix_userkey)
                    resp = self._get(path)

            result = self._parse_search_results(resp.text, page or 1)

            # 后置过滤：某些镜像站不支持 URL 层面的格式过滤
            if extensions and result["books"]:
                exts_lower = [e.lower().lstrip(".") for e in extensions]
                result["books"] = [
                    b for b in result["books"]
                    if b.get("extension", "").lower().lstrip(".") in exts_lower
                ]

            return result
        except requests.RequestException as e:
            raise SearchError(f"搜索请求失败: {e}")

    def _parse_search_results(self, html: str, current_page: int) -> dict:
        """解析搜索结果页面 HTML。

        支持两种格式:
        1. 新版 z-bookcard（z-library.sk 等）
        2. 经典 div.resItemBox（z-lib.id 等镜像站）
        """
        soup = BeautifulSoup(html, "lxml")
        books = []

        # 策略1: 经典 div.resItemBox 格式（z-lib.id 等镜像站）
        result_boxes = soup.find_all("div", class_="resItemBox")
        if result_boxes:
            for box in result_boxes:
                book = self._parse_classic_book_card(box)
                if book:
                    books.append(book)

        # 策略2: 现代 z-bookcard 标签（官方现代站点）
        if not books:
            book_cards = soup.find_all("z-bookcard")
            for card in book_cards:
                book = self._parse_webcomponent_book_card(card)
                if book:
                    books.append(book)

        # 策略3: 通用选择器兜底
        if not books:
            for selector in [
                '[class*="book"][class*="item"]',
                ".cardBook",
                ".result-card",
                "#searchResultBox > div",
            ]:
                items = soup.select(selector)
                if items:
                    for item in items:
                        book = self._parse_generic_book_card(item)
                        if book:
                            books.append(book)
                    break

        # 尝试获取总页数
        total = len(books)
        pager = soup.select_one(".pagination, .pager, [class*=pagination]")
        if pager:
            for a in pager.find_all("a"):
                try:
                    n = int(a.text.strip())
                    if n > total:
                        total = max(total, n)
                except ValueError:
                    continue

        if not books:
            logger.info("未解析到搜索结果（页面结构可能不兼容当前域名）")

        return {"books": books, "total": total, "page": current_page}

    # ── 三种书籍卡片解析器 ─────────────────────────────────

    def _parse_classic_book_card(self, div: BeautifulSoup) -> Optional[dict]:
        """解析经典 div.resItemBox 格式（z-lib.id 镜像站）。"""
        try:
            book = {}

            # data-book_id（z-lib.id 风格）
            book_id = div.get("data-book_id", "")
            if not book_id:
                nested = div.select_one("[data-book_id]")
                if nested:
                    book_id = nested.get("data-book_id", "")
            book["id"] = str(book_id) if book_id else ""

            # 标题
            title_link = div.select_one("h3 a, a[itemprop='name']")
            if not title_link:
                title_link = div.find("a", href=re.compile(r"/book/"))
            if title_link:
                book["title"] = title_link.text.strip()
                href = title_link.get("href", "")
                if href and not href.startswith("http"):
                    href = f"https://{self._domain}{href}"
                book["url"] = href

            # 作者
            author_div = div.select_one(".authors, .book-author")
            if author_div:
                author_links = author_div.find_all("a")
                authors = [a.text.strip() for a in author_links if a.text.strip()]
                if authors:
                    book["author"] = ", ".join(authors)

            # 出版社
            pub_link = div.select_one("a[itemprop='publisher'], [class*=publisher] a")
            if pub_link:
                book["publisher"] = pub_link.text.strip()

            # 从 bookDetailsBox 提取属性
            details_box = div.select_one(".bookDetailsBox")
            if details_box:
                for prop in details_box.find_all("div", class_=re.compile(r"bookProperty")):
                    label_el = prop.select_one(".property_label")
                    value_el = prop.select_one(".property_value")
                    if label_el and value_el:
                        lbl = label_el.text.strip().lower().rstrip(":")
                        val = value_el.text.strip()
                        if "year" in lbl:
                            book["year"] = val
                        elif "file" in lbl or "format" in lbl or "extension" in lbl:
                            parts = val.split(",")
                            book["extension"] = parts[0].strip()
                            if len(parts) > 1:
                                book["size"] = parts[1].strip()
                        elif "language" in lbl:
                            book["language"] = val
                        elif "isbn" in lbl:
                            book["isbn"] = val
                        elif "rating" in lbl:
                            book["rating"] = val

            # 封面
            img = div.select_one("img.cover, img.lazy, .z-book-precover img")
            if img:
                book["cover"] = img.get("src") or img.get("data-src", "")

            # 镜像站没有 hash
            book["hash"] = ""

            if book.get("title"):
                return book
            logger.debug("解析经典卡片失败: 无标题")
            return None
        except Exception as e:
            logger.debug("解析经典卡片异常: %s", e)
            return None

    def _parse_webcomponent_book_card(self, card) -> Optional[dict]:
        """解析现代 z-bookcard web component 格式。"""
        try:
            book = {}
            book["id"] = str(card.get("id", ""))
            book["hash"] = card.get("hash", card.get("data-hash", ""))
            book["termshash"] = card.get("termshash", "")
            book["download_url"] = card.get("download", "")  # 直接从 z-bookcard 取下载链接

            title_slot = card.select_one('[slot="title"]')
            book["title"] = title_slot.text.strip() if title_slot else ""

            author_slot = card.select_one('[slot="author"]')
            book["author"] = author_slot.text.strip() if author_slot else ""

            details_slot = card.select_one('[slot="details"]')
            if details_slot:
                parts = details_slot.text.strip().split(",")
                book["extension"] = parts[0].strip() if parts else ""
                book["size"] = parts[1].strip() if len(parts) > 1 else ""

            if not book.get("extension"):
                book["extension"] = card.get("extension", card.get("data-extension", ""))

            book["year"] = card.get("year", card.get("data-year", ""))

            img = card.select_one("img")
            book["cover"] = img.get("src") or img.get("data-src", "") if img else ""

            book["publisher"] = card.get("publisher", "")
            book["isbn"] = card.get("isbn", "")

            return book or None
        except Exception:
            return None

    def _parse_generic_book_card(self, item) -> Optional[dict]:
        """通用兜底解析器。"""
        try:
            book = {}
            a = item.find("a") if item.name != "a" else item
            if a and a.get("href"):
                book["url"] = f"https://{self._domain}{a['href']}"
            text = item.get_text(" ", strip=True)
            if text:
                book["title"] = text[:200]
            return book or None
        except Exception:
            return None

    # ── 下载 ────────────────────────────────────────────────

    def downloadBook(self, book: dict) -> tuple[Optional[str], Optional[bytes]]:
        """下载图书。

        Args:
            book: 包含 id（或 url）的书籍信息字典

        Returns:
            (filename, content) 或 (None, None)

        注意: z-lib.id 等镜像站不支持文件下载（仅元数据），
        如需下载请配置代理访问 1lib.sk 等官方域名，或使用 remix token。
        """
        book_id = book.get("id")
        book_url = book.get("url", "")
        book_download_url = book.get("download_url", "")  # z-bookcard 直接给出的下载路径

        if not book_id and not book_download_url:
            raise DownloadError("缺少书籍 id 或 download_url")

        try:
            # 如果搜索时已获得下载路径，直接使用
            if book_download_url:
                dl_link = self._resolve_url(book_download_url)
            else:
                # 否则进入详情页查找下载链接
                if book_url:
                    detail_url = book_url
                else:
                    detail_url = f"/book/{book_id}"

                resp = self._get(detail_url)
                soup = BeautifulSoup(resp.text, "lxml")

                # 寻找下载按钮，按优先级尝试
                dl_link = None

                # 1) z-bookcard 的 download 属性（新版 SPA 网站）
                if not dl_link:
                    card = soup.select_one("z-bookcard")
                    if card and card.get("download"):
                        dl_link = card["download"]

                # 2) addDownloadedBook 按钮（标准 Z-Library）
                if not dl_link:
                    dl_btn = soup.select_one("a.addDownloadedBook")
                    if dl_btn:
                        dl_link = dl_btn.get("href")

                # 3) class 含 download 的链接/按钮
                if not dl_link:
                    dl_btn = soup.select_one(
                        'a[class*=download], button[class*=download]'
                    )
                    if dl_btn:
                        dl_link = dl_btn.get("href")

                # 4) 任何带 download 关键字的链接
                if not dl_link:
                    for a in soup.find_all("a", href=re.compile(r"download", re.I)):
                        dl_link = a.get("href")
                        break

                # 5) /dl/ 或 /file/ 路径的链接
                if not dl_link:
                    for a in soup.find_all("a", href=re.compile(r"/(dl|file|get)/")):
                        dl_link = a.get("href")
                        break

                if not dl_link:
                    raise DownloadError(
                        "未找到下载链接。"
                        + ("z-lib.id 等镜像站不支持文件下载。" if self._domain in DOMAIN_BLACKLIST else "")
                        + "\n提示: 设置代理 (proxy) 访问官方域名后可下载，"
                        + "或参见 README 获取 remix token 后使用 token 登录。"
                    )

            # 处理相对链接
            if dl_link.startswith("/"):
                dl_link = f"https://{self._domain}{dl_link}"

            # 下载文件
            file_resp = self._session.get(
                dl_link,
                timeout=self._timeout,
                stream=True,
            )
            file_resp.raise_for_status()

            # 检查是否被 Cloudflare 拦截
            if self._is_cloudflare_blocked(file_resp):
                raise DownloadError(
                    "下载链接被 Cloudflare 拦截。请运行 refresh_zlibrary_cookies.py 更新 cookies。"
                )

            filename = self._extract_filename(file_resp, book)
            return filename, file_resp.content

        except DownloadError:
            raise
        except requests.RequestException as e:
            raise DownloadError(f"下载请求失败: {e}")
        except Exception as e:
            raise DownloadError(f"下载异常: {e}")

    def _extract_filename(self, response: requests.Response, book: dict) -> str:
        """从响应头或书籍信息中提取文件名。"""
        # 尝试从 Content-Disposition 获取
        cd = response.headers.get("Content-Disposition", "")
        fname_match = re.search(r'filename\*?=(?:UTF-8\'\')?["\']?([^"\';]+)', cd)
        if fname_match:
            return self._fix_header_mojibake(requests.utils.unquote(fname_match.group(1)))

        # 从 Content-Type 扩展名
        ext = book.get("extension", "")
        title = book.get("title", "unknown")
        if ext and not ext.startswith("."):
            ext = f".{ext}"
        return f"{title}{ext}".replace(" ", "_")

    @staticmethod
    def _fix_header_mojibake(name: str) -> str:
        """还原被 latin-1 误解码的 UTF-8 文件名。

        requests 按 HTTP 老规范用 latin-1 解析响应头，服务器发的 UTF-8
        文件名会变成 mojibake（如 "球状闪电" → "çç¶éªçµ"）。这里尝试
        latin-1→utf-8 还原：能还原说明确是被误解码的 UTF-8，用还原值；
        本来就是正常字符串则会抛异常，保持原样。
        """
        try:
            return name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            return name

    # ── 辅助 ────────────────────────────────────────────────

    def isLoggedIn(self) -> bool:
        return self._loggedin

    def getDomains(self) -> dict:
        """返回已知域名列表。"""
        return {
            "current": self._domain,
            "available": self._fallback_domains or DEFAULT_DOMAINS,
        }

    @property
    def domain(self) -> str:
        return self._domain

    @domain.setter
    def domain(self, value: str):
        self._domain = value
