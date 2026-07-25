"""Cookies 生命周期管理：状态查询 / 自动刷新 / 真实探针验证。

为什么单独一个模块：Cloudflare cookies 会过期，过期后所有下载请求返回 503。
原先的做法是抛错让用户去终端手动跑 refresh_zlibrary_cookies.py，人必须在场。
这里把「查状态 → 刷新 → 验证」收成可被程序调用的函数，让 Zlibrary 撞墙时
自己修，用户全程不碰命令行。

对外接口：
    cookies_status()          查当前 cookies 健康度，不发网络请求
    refresh_cookies()         用真浏览器过 Cloudflare 并导出 cookies
    ensure_fresh_cookies()    过期/缺失才刷，够新就跳过
    login_and_capture_token() 邮箱密码 → remix token（首次运行向导用）

不 import Zlibrary：探针用 requests 裸调，避免循环依赖。
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import requests

PROJECT_DIR = Path(__file__).resolve().parent
COOKIES_FILE = PROJECT_DIR / "zlibrary_cookies.json"
LOCK_FILE = PROJECT_DIR / ".cookies.lock"
ENV_FILE_PATH = PROJECT_DIR / ".env"

# cookies 超过这个时长就视为该刷了。Z-Library 的 Cloudflare cookie 实测能活几天到
# 几周，但过期时刻不可预测；12 小时是「刷一次成本约 10 秒」与「跑批量时中途炸掉」
# 之间的折中。可用环境变量 ZLIBRARY_COOKIES_MAX_AGE_HOURS 覆盖。
DEFAULT_MAX_AGE_HOURS = 12.0

# 判定「已登录」必须存在的 cookie
LOGIN_COOKIE = "remix_userid"

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

LOCK_STALE_SECONDS = 180.0


class CookieRefreshError(RuntimeError):
    """刷新 cookies 失败（浏览器不可用、登录态无效、探针不通等）。"""


@dataclass
class CookiesStatus:
    exists: bool = False
    count: int = 0
    has_login: bool = False
    age_hours: Optional[float] = None
    max_age_hours: float = DEFAULT_MAX_AGE_HOURS
    domains: list[str] = field(default_factory=list)
    path: str = str(COOKIES_FILE)

    @property
    def stale(self) -> bool:
        """是否该刷新了。缺失、无登录态、或超龄都算。"""
        if not self.exists or not self.has_login:
            return True
        if self.age_hours is None:
            return True
        return self.age_hours > self.max_age_hours

    @property
    def summary(self) -> str:
        if not self.exists:
            return "cookies 文件不存在"
        if not self.has_login:
            return f"cookies 存在但缺少登录态（{self.count} 个）"
        age = "未知" if self.age_hours is None else f"{self.age_hours:.1f} 小时前"
        return f"cookies {self.count} 个，更新于 {age}" + ("（已过期）" if self.stale else "")

    def to_dict(self) -> dict:
        return {
            "exists": self.exists,
            "count": self.count,
            "has_login": self.has_login,
            "age_hours": None if self.age_hours is None else round(self.age_hours, 2),
            "max_age_hours": self.max_age_hours,
            "domains": self.domains,
            "stale": self.stale,
            "summary": self.summary,
            "path": self.path,
        }


def _max_age_hours() -> float:
    raw = os.environ.get("ZLIBRARY_COOKIES_MAX_AGE_HOURS", "").strip()
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
    return DEFAULT_MAX_AGE_HOURS


def cookies_status(cookies_file: Path | str = COOKIES_FILE) -> CookiesStatus:
    """查 cookies 健康度。纯本地文件判断，不发网络请求。"""
    path = Path(cookies_file)
    status = CookiesStatus(max_age_hours=_max_age_hours(), path=str(path))
    if not path.exists():
        return status

    status.exists = True
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        # 文件坏了等同于没有：让上层去刷新覆盖它
        status.exists = False
        return status

    if not isinstance(data, list):
        status.exists = False
        return status

    status.count = len(data)
    names = set()
    domains = []
    for item in data:
        if not isinstance(item, dict):
            continue
        names.add(item.get("name", ""))
        domain = (item.get("domain") or "").lstrip(".")
        if domain and domain not in domains:
            domains.append(domain)
    status.has_login = LOGIN_COOKIE in names
    status.domains = domains

    try:
        status.age_hours = (time.time() - path.stat().st_mtime) / 3600.0
    except OSError:
        status.age_hours = None
    return status


def probe_cookies(
    cookies: list[dict],
    domain: str,
    proxy: str = "",
    timeout: int = 20,
) -> bool:
    """用一份 cookies 真实请求 /eapi/user/profile，200 且 success 才算过关。

    只看文件里有没有 remix_userid 是不够的——Cloudflare 拦截时 cookie 照样在，
    但请求会返回 503。所以刷新后必须打一次真实探针。
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    if proxy:
        session.proxies = {"http": proxy, "https": proxy}
    for item in cookies:
        name = item.get("name")
        value = item.get("value")
        if not name or value is None:
            continue
        session.cookies.set(name, value, domain=(item.get("domain") or domain).lstrip("."))
    try:
        resp = session.get(f"https://{domain}/eapi/user/profile", timeout=timeout)
        if resp.status_code != 200:
            return False
        payload = resp.json()
    except (requests.RequestException, ValueError):
        return False
    return bool(payload.get("success")) and "user" in payload


class _FileLock:
    """跨进程互斥，防止两个任务同时开浏览器刷 cookies 互相覆盖。

    用 O_CREAT|O_EXCL 建锁文件（Windows / POSIX 通用）。超过 LOCK_STALE_SECONDS
    的锁视为上次崩溃留下的残骸，直接夺取。
    """

    def __init__(self, path: Path = LOCK_FILE, timeout: float = 120.0):
        self.path = Path(path)
        self.timeout = timeout
        self._fd: Optional[int] = None

    def __enter__(self):
        deadline = time.time() + self.timeout
        while True:
            try:
                self._fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(self._fd, str(os.getpid()).encode())
                return self
            except FileExistsError:
                try:
                    age = time.time() - self.path.stat().st_mtime
                except OSError:
                    age = 0.0
                if age > LOCK_STALE_SECONDS:
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                if time.time() > deadline:
                    # 拿不到锁不阻断主流程：另一个进程正在刷，让调用方继续用旧 cookies
                    return self
                time.sleep(1.0)

    def __exit__(self, *exc):
        if self._fd is not None:
            try:
                os.close(self._fd)
            except OSError:
                pass
            try:
                self.path.unlink()
            except OSError:
                pass
        return False


def _resolve_env(domain: str = "", proxy: str = "", remix_userid: str = "", remix_userkey: str = ""):
    """参数缺失时回落到 .env。让调用方可以只传一部分。"""
    if domain and remix_userid and remix_userkey:
        return domain, proxy, remix_userid, remix_userkey
    try:
        from env_config import load_zlibrary_env

        env = load_zlibrary_env()
    except Exception:
        env = {}
    return (
        domain or env.get("domain") or "z-lib.by",
        proxy or env.get("proxy", ""),
        remix_userid or env.get("remix_userid", ""),
        remix_userkey or env.get("remix_userkey", ""),
    )


def _browser_export(
    domain: str,
    proxy: str,
    remix_userid: str,
    remix_userkey: str,
    headless: bool,
    log,
) -> list[dict]:
    """开一次真浏览器，过 Cloudflare，返回 cookies 列表。"""
    from playwright.sync_api import sync_playwright

    base_url = f"https://{domain}"
    proxy_cfg = {"server": proxy} if proxy else None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, proxy=proxy_cfg)
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=USER_AGENT,
            )
            if remix_userid and remix_userkey:
                context.add_cookies([
                    {"name": "remix_userid", "value": remix_userid, "domain": domain, "path": "/"},
                    {"name": "remix_userkey", "value": remix_userkey, "domain": domain, "path": "/"},
                ])
            page = context.new_page()
            log(f"打开 {base_url}（{'静默' if headless else '可见窗口'}模式）...")
            page.goto(base_url, timeout=60000)
            try:
                page.wait_for_load_state("networkidle", timeout=30000)
            except Exception:
                # networkidle 超时不致命：页面可能已可用，继续走探针判定
                log("页面未进入空闲状态，继续尝试导出。")
            page.wait_for_timeout(3000)
            return [
                {"name": c["name"], "value": c["value"], "domain": c["domain"].lstrip(".")}
                for c in context.cookies()
            ]
        finally:
            browser.close()


def refresh_cookies(
    domain: str = "",
    proxy: str = "",
    remix_userid: str = "",
    remix_userkey: str = "",
    cookies_file: Path | str = COOKIES_FILE,
    log=print,
    verify: bool = True,
) -> CookiesStatus:
    """用真浏览器过 Cloudflare 并导出 cookies。

    headless 失败或探针不通时，自动改「可见窗口」重试一次——有头模式过 Cloudflare
    的成功率更高（部分检测会识别 headless 特征）。两轮都不过才抛 CookieRefreshError。

    Returns: 刷新后的 CookiesStatus
    Raises:  CookieRefreshError
    """
    domain, proxy, remix_userid, remix_userkey = _resolve_env(
        domain, proxy, remix_userid, remix_userkey
    )
    path = Path(cookies_file)

    try:
        import playwright  # noqa: F401
    except ImportError as exc:
        raise CookieRefreshError(
            "缺少 playwright。请重新运行启动器 start.cmd 安装依赖，"
            "或手动执行：.venv\\Scripts\\pip install playwright && "
            ".venv\\Scripts\\python -m playwright install chromium"
        ) from exc

    errors: list[str] = []
    with _FileLock():
        for headless in (True, False):
            try:
                cookies = _browser_export(domain, proxy, remix_userid, remix_userkey, headless, log)
            except Exception as exc:  # playwright 各类异常统一转人话
                errors.append(f"{'静默' if headless else '可见'}模式失败: {exc}")
                log(f"浏览器启动失败（{'静默' if headless else '可见'}模式）: {exc}")
                continue

            names = {c["name"] for c in cookies}
            if LOGIN_COOKIE not in names:
                errors.append(f"{'静默' if headless else '可见'}模式未拿到登录态 cookie")
                log("未检测到 remix_userid：Remix Token 可能已失效。")
                continue

            if verify and not probe_cookies(cookies, domain, proxy):
                errors.append(f"{'静默' if headless else '可见'}模式探针未通过")
                log("cookies 已导出但真实探针未通过，换可见窗口重试...")
                continue

            path.write_text(
                json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            log(f"cookies 已刷新：{len(cookies)} 个 → {path.name}")
            return cookies_status(path)

    raise CookieRefreshError(
        "自动刷新 cookies 失败。可能原因：代理未开启、Remix Token 已过期、"
        "或 Z-Library 域名不可访问。\n详情：" + "; ".join(errors)
    )


def ensure_fresh_cookies(
    domain: str = "",
    proxy: str = "",
    remix_userid: str = "",
    remix_userkey: str = "",
    cookies_file: Path | str = COOKIES_FILE,
    log=print,
    force: bool = False,
) -> CookiesStatus:
    """够新就跳过，过期或缺失才刷。批量任务开跑前调一次，避免跑到一半炸。"""
    status = cookies_status(cookies_file)
    if not force and not status.stale:
        return status
    reason = "强制刷新" if force else status.summary
    log(f"[cookies] {reason} → 正在自动刷新...")
    refreshed = refresh_cookies(
        domain=domain,
        proxy=proxy,
        remix_userid=remix_userid,
        remix_userkey=remix_userkey,
        cookies_file=cookies_file,
        log=log,
    )
    log(f"[cookies] 刷新完成：{refreshed.summary}")
    return refreshed


def login_and_capture_token(
    email: str,
    password: str,
    domain: str = "",
    proxy: str = "",
    cookies_file: Path | str = COOKIES_FILE,
    log=print,
) -> dict:
    """邮箱密码 → remix token + cookies。首次运行向导用，免去手翻 DevTools。

    用真浏览器走一遍登录表单，成功后 remix_userid / remix_userkey 会出现在
    cookies 里，顺手把整份 cookies 也存下来（等于同时完成了 Cloudflare 绕过）。

    Returns: {"remix_userid": ..., "remix_userkey": ..., "cookies_saved": bool}
    Raises:  CookieRefreshError
    """
    from playwright.sync_api import sync_playwright

    domain, proxy, _, _ = _resolve_env(domain, proxy, "-", "-")
    base_url = f"https://{domain}"
    proxy_cfg = {"server": proxy} if proxy else None
    path = Path(cookies_file)

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True, proxy=proxy_cfg)
        except Exception as exc:
            raise CookieRefreshError(f"无法启动浏览器：{exc}") from exc
        try:
            context = browser.new_context(
                viewport={"width": 1280, "height": 800}, user_agent=USER_AGENT
            )
            page = context.new_page()
            log(f"打开登录页 {base_url} ...")
            page.goto(f"{base_url}/", timeout=60000)
            page.wait_for_timeout(2000)

            # Z-Library 的登录入口在不同镜像上布局不一，逐个选择器兜底
            opened = False
            for selector in (
                "a[href*='login']",
                "a.login",
                "text=Sign in",
                "text=登录",
            ):
                try:
                    page.click(selector, timeout=3000)
                    opened = True
                    break
                except Exception:
                    continue
            if not opened:
                page.goto(f"{base_url}/login", timeout=60000)
            page.wait_for_timeout(2000)

            filled = False
            for email_sel in ("input[name=email]", "input[type=email]", "#email"):
                try:
                    page.fill(email_sel, email, timeout=3000)
                    filled = True
                    break
                except Exception:
                    continue
            if not filled:
                raise CookieRefreshError("未找到邮箱输入框，站点结构可能已变化。")

            for pwd_sel in ("input[name=password]", "input[type=password]", "#password"):
                try:
                    page.fill(pwd_sel, password, timeout=3000)
                    break
                except Exception:
                    continue

            for submit_sel in (
                "button[type=submit]",
                "input[type=submit]",
                "text=Sign in",
                "text=登录",
            ):
                try:
                    page.click(submit_sel, timeout=3000)
                    break
                except Exception:
                    continue

            page.wait_for_timeout(5000)
            cookies = [
                {"name": c["name"], "value": c["value"], "domain": c["domain"].lstrip(".")}
                for c in context.cookies()
            ]
        finally:
            browser.close()

    jar = {c["name"]: c["value"] for c in cookies}
    uid = jar.get("remix_userid", "")
    key = jar.get("remix_userkey", "")
    if not uid or not key:
        raise CookieRefreshError(
            "登录未成功：没拿到 remix token。请确认邮箱密码正确；"
            "国内网络还需在设置里填写本地代理地址。"
        )

    saved = False
    if probe_cookies(cookies, domain, proxy):
        path.write_text(json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
        saved = True
        log("登录成功，token 与 cookies 均已保存。")
    else:
        log("登录成功并取得 token，但 cookies 探针未通过，稍后会自动重刷。")

    return {"remix_userid": uid, "remix_userkey": key, "cookies_saved": saved}


def write_env(values: dict[str, str], env_path: Path | str = ENV_FILE_PATH) -> Path:
    """把配置写进 .env，保留文件里已有的其它行与注释。

    只覆盖传进来的 key；值为空字符串的 key 跳过，避免向导没填的字段清空已有配置。
    """
    path = Path(env_path)
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True) if path.exists() else []

    for key, value in values.items():
        if not value:
            continue
        replaced = False
        for i, line in enumerate(lines):
            if line.strip().startswith(f"{key}="):
                lines[i] = f"{key}={value}\n"
                replaced = True
                break
        if not replaced:
            if lines and not lines[-1].endswith("\n"):
                lines[-1] += "\n"
            lines.append(f"{key}={value}\n")

    path.write_text("".join(lines), encoding="utf-8")
    return path


def setup_from_credentials(
    email: str = "",
    password: str = "",
    remix_userid: str = "",
    remix_userkey: str = "",
    proxy: str = "",
    domain: str = "",
    log=print,
) -> dict:
    """首次运行向导的后端：一次调用完成「配置 → 换 token → 存 cookies」。

    两条路：
      给了 remix token  → 直接写 .env，然后刷 cookies 验证；
      只给邮箱密码      → 真浏览器登录抓 token，写 .env，顺带存下 cookies。

    这样新用户不用开 DevTools 翻 cookies，也不用碰命令行。

    Returns: {"remix_userid", "cookies_saved", "env_path", "message"}
    Raises:  CookieRefreshError
    """
    if not (remix_userid and remix_userkey) and not (email and password):
        raise CookieRefreshError("请填写邮箱和密码，或直接填 Remix Token。")

    # 先落盘代理/域名：后面的浏览器登录要用它们，_resolve_env 从 .env 读
    write_env({
        "ZLIBRARY_PROXY": proxy,
        "ZLIBRARY_DOMAIN": domain,
    })

    if remix_userid and remix_userkey:
        write_env({
            "ZLIBRARY_REMIX_USERID": remix_userid,
            "ZLIBRARY_REMIX_USERKEY": remix_userkey,
        })
        log("已保存 Remix Token，正在验证并导出 cookies…")
        status = refresh_cookies(
            domain=domain, proxy=proxy,
            remix_userid=remix_userid, remix_userkey=remix_userkey,
            log=log,
        )
        return {
            "remix_userid": remix_userid,
            "cookies_saved": status.exists and status.has_login,
            "env_path": str(ENV_FILE_PATH),
            "message": f"配置完成，{status.summary}",
        }

    log("正在用邮箱密码登录并获取 Token（约 20-40 秒）…")
    result = login_and_capture_token(
        email=email, password=password, domain=domain, proxy=proxy, log=log
    )
    write_env({
        "ZLIBRARY_EMAIL": email,
        "ZLIBRARY_REMIX_USERID": result["remix_userid"],
        "ZLIBRARY_REMIX_USERKEY": result["remix_userkey"],
    })

    cookies_saved = result.get("cookies_saved", False)
    if not cookies_saved:
        # 登录拿到了 token 但 cookies 探针没过，用 token 再刷一轮
        try:
            status = refresh_cookies(
                domain=domain, proxy=proxy,
                remix_userid=result["remix_userid"],
                remix_userkey=result["remix_userkey"],
                log=log,
            )
            cookies_saved = status.exists and status.has_login
        except CookieRefreshError as exc:
            log(f"cookies 补刷失败（不影响 token 已保存）: {exc}")

    return {
        "remix_userid": result["remix_userid"],
        "cookies_saved": cookies_saved,
        "env_path": str(ENV_FILE_PATH),
        "message": "配置完成，账号已就绪。" if cookies_saved
                   else "账号已保存，但 cookies 未通过验证——首次下载时会自动重试。",
    }


if __name__ == "__main__":
    print(cookies_status().summary)
