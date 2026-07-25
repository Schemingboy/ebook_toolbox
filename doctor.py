"""启动自检与自愈：跑任务前把环境问题查出来，能自己修的直接修。

为什么需要它：这套工具的失败模式高度集中在几个外部条件上——.env 没填、代理没开、
Cloudflare cookies 过期、配额用完。以前这些问题都是「跑到一半炸掉 + 一句让你去开
终端的提示」。这里把检查前置到启动/跑任务之前，并且把可自动修复的部分（cookies）
直接修掉，用户全程不碰命令行。

设计约定：
- 每一项检查返回 CheckResult，级别只有三种：ok / warn / error。
  error = 跑不起来，必须处理；warn = 能跑但可能出问题；ok = 通过。
- 检查按成本递增排序，前面的失败会让后面的跳过（没填账号就不用去探测域名了）。
- fix=True 时才动文件/发请求做修复，默认只读诊断。
- 所有函数可被 web_api 和 CLI 共用，不 print 到 stdout 以外的地方。

对外接口：
    run_checks(fix=False)     -> DoctorReport
    format_report(report)     -> str      给终端/WS 日志看的人类可读文本
    preflight(emit=print)     -> bool     跑任务前调用，自动修 cookies，返回能否继续
"""
from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import urlparse

PROJECT_DIR = Path(__file__).resolve().parent

OK = "ok"
WARN = "warn"
ERROR = "error"

# 国内常见本地代理端口，用于「没填代理」时给出可用建议
COMMON_PROXY_PORTS = [7897, 7890, 7891, 1080, 10809, 20171, 8889]


@dataclass
class CheckResult:
    name: str
    level: str = OK
    message: str = ""
    hint: str = ""          # 给用户的下一步（人话，不含命令行）
    fixed: bool = False     # 本次是否自动修复了
    detail: dict = field(default_factory=dict)

    @property
    def is_error(self) -> bool:
        return self.level == ERROR


@dataclass
class DoctorReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(not c.is_error for c in self.checks)

    @property
    def errors(self) -> list[CheckResult]:
        return [c for c in self.checks if c.level == ERROR]

    @property
    def warnings(self) -> list[CheckResult]:
        return [c for c in self.checks if c.level == WARN]

    @property
    def needs_setup(self) -> bool:
        """是否需要走首次运行向导（缺 .env 或缺凭据）。"""
        return any(
            c.name in ("env_file", "credentials") and c.is_error for c in self.checks
        )

    def get(self, name: str) -> Optional[CheckResult]:
        for c in self.checks:
            if c.name == name:
                return c
        return None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "needs_setup": self.needs_setup,
            "checks": [
                {
                    "name": c.name,
                    "level": c.level,
                    "message": c.message,
                    "hint": c.hint,
                    "fixed": c.fixed,
                    "detail": c.detail,
                }
                for c in self.checks
            ],
        }


# ── 单项检查 ────────────────────────────────────────────────


def check_dependencies() -> CheckResult:
    """核心依赖是否装齐。缺了就是没跑安装步骤，属 error。"""
    missing = []
    for mod, pkg in [
        ("requests", "requests"),
        ("bs4", "beautifulsoup4"),
        ("lxml", "lxml"),
        ("fastapi", "fastapi"),
        ("playwright", "playwright"),
    ]:
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        return CheckResult(
            "dependencies",
            ERROR,
            f"缺少依赖: {', '.join(missing)}",
            hint="用 start.cmd（Windows 双击）或 start.sh 启动，会自动安装依赖。",
            detail={"missing": missing},
        )
    return CheckResult("dependencies", OK, "依赖齐全")


def check_browser() -> CheckResult:
    """Playwright 的 Chromium 在不在。过 Cloudflare 必须有真浏览器。"""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return CheckResult(
            "browser",
            ERROR,
            "playwright 未安装",
            hint="用 start.cmd / start.sh 启动，会自动安装。",
        )
    try:
        with sync_playwright() as p:
            path = Path(p.chromium.executable_path)
        if not path.exists():
            raise FileNotFoundError(path)
    except Exception as exc:
        return CheckResult(
            "browser",
            ERROR,
            "Playwright 的 Chromium 浏览器没装好",
            hint="用 start.cmd / start.sh 启动会自动下载（约 150MB，只需一次）。",
            detail={"error": str(exc)},
        )
    return CheckResult("browser", OK, "浏览器就绪", detail={"path": str(path)})


def check_env_file() -> CheckResult:
    """.env 存不存在。不存在则需要走首次运行向导。"""
    from env_config import ENV_FILE

    if not ENV_FILE.exists():
        return CheckResult(
            "env_file",
            ERROR,
            "还没有配置文件 .env",
            hint="打开 Web 界面会自动进入首次配置向导，填邮箱密码即可，不用手动改文件。",
        )
    return CheckResult("env_file", OK, "配置文件已存在")


def check_credentials() -> CheckResult:
    """凭据够不够用：remix token 或 邮箱密码，二者有其一即可。"""
    from env_config import load_zlibrary_env

    cfg = load_zlibrary_env()
    has_token = bool(cfg.get("remix_userid") and cfg.get("remix_userkey"))
    has_login = bool(cfg.get("email") and cfg.get("password"))

    # .env.example 的占位值不算填了
    if cfg.get("email", "").startswith("your_email"):
        has_login = False

    if not has_token and not has_login:
        return CheckResult(
            "credentials",
            ERROR,
            "还没填 Z-Library 账号",
            hint="在 Web 界面「设置」里填邮箱和密码，点测试并保存，会自动换取登录凭证。",
            detail={"has_token": False, "has_login": False},
        )
    return CheckResult(
        "credentials",
        OK,
        "账号已配置（" + ("登录凭证" if has_token else "邮箱密码") + "）",
        detail={"has_token": has_token, "has_login": has_login},
    )


def _port_open(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def detect_local_proxies() -> list[str]:
    """探测本机常见代理端口，返回可直接填进配置的地址列表（供向导预填）。"""
    return [
        f"http://127.0.0.1:{port}"
        for port in COMMON_PROXY_PORTS
        if _port_open("127.0.0.1", port)
    ]


def check_proxy() -> CheckResult:
    """代理端口通不通。国内不走代理基本连不上官方域名，所以没填也给 warn。"""
    from env_config import load_zlibrary_env

    proxy = load_zlibrary_env().get("proxy", "").strip()
    if not proxy:
        found = [p for p in COMMON_PROXY_PORTS if _port_open("127.0.0.1", p)]
        if found:
            return CheckResult(
                "proxy",
                WARN,
                f"没填代理，但检测到本机 {found[0]} 端口有代理在跑",
                hint=f"国内访问 Z-Library 一般需要代理。建议在设置里填 http://127.0.0.1:{found[0]}",
                detail={"suggested": f"http://127.0.0.1:{found[0]}", "found": found},
            )
        return CheckResult(
            "proxy",
            WARN,
            "没填代理",
            hint="如果你在国内且连不上，打开代理软件后在设置里填它的端口。",
            detail={"found": []},
        )

    parsed = urlparse(proxy if "://" in proxy else f"http://{proxy}")
    host, port = parsed.hostname, parsed.port
    if not host or not port:
        return CheckResult(
            "proxy",
            WARN,
            f"代理地址看不懂: {proxy}",
            hint="格式应为 http://127.0.0.1:7897 或 socks5://127.0.0.1:1080",
        )
    if not _port_open(host, port):
        found = [p for p in COMMON_PROXY_PORTS if p != port and _port_open("127.0.0.1", p)]
        hint = "代理软件没开，或端口填错了。"
        if found:
            hint += f" 检测到 {found[0]} 端口是通的，可以改成它。"
        return CheckResult(
            "proxy",
            ERROR,
            f"代理 {host}:{port} 连不上",
            hint=hint,
            detail={"found": found},
        )
    return CheckResult("proxy", OK, f"代理 {host}:{port} 通", detail={"proxy": proxy})


def check_cookies(fix: bool = False, emit: Optional[Callable[[str], None]] = None) -> CheckResult:
    """Cloudflare cookies 是否新鲜。fix=True 时过期就自动刷新——这是自愈的核心。"""
    import cookie_manager

    status = cookie_manager.cookies_status()
    if not status.stale:
        return CheckResult(
            "cookies",
            OK,
            f"Cookies 正常（{status.summary}）",
            detail=status.to_dict(),
        )

    reason = "还没有" if not status.exists else (
        "缺少登录信息" if not status.has_login else f"已过期（{status.summary}）"
    )

    if not fix:
        return CheckResult(
            "cookies",
            WARN,
            f"Cookies {reason}",
            hint="跑任务时会自动刷新，无需手动操作。",
            detail=status.to_dict(),
        )

    # 自动修复
    if emit:
        emit(f"[自检] Cookies {reason}，正在自动刷新（约 10-30 秒）…")
    try:
        result = cookie_manager.refresh_cookies()
    except Exception as exc:
        return CheckResult(
            "cookies",
            ERROR,
            f"Cookies 自动刷新失败: {exc}",
            hint="通常是代理没开或账号凭证失效。检查代理后，在设置里重新测试连接。",
            detail=status.to_dict(),
        )
    if emit:
        emit(f"[自检] Cookies 刷新完成（{result.count} 个），继续。")
    return CheckResult(
        "cookies",
        OK,
        f"Cookies 已自动刷新（{result.count} 个）",
        fixed=True,
        detail=result.to_dict() if hasattr(result, "to_dict") else {},
    )


def check_quota() -> CheckResult:
    """今日剩余下载配额。0 不是错误，只是今天下不了了。"""
    try:
        from zlibrary_runtime import create_zlibrary_client, load_zlibrary_auth

        client = create_zlibrary_client(load_zlibrary_auth())
        left = client.getDownloadsLeft()
    except Exception as exc:
        return CheckResult(
            "quota",
            WARN,
            f"查不到剩余配额: {exc}",
            hint="不影响启动。若下载失败，先在设置里点测试连接。",
        )
    if left <= 0:
        return CheckResult(
            "quota",
            WARN,
            "今日下载配额已用完",
            hint="Z-Library 普通账号每天 10 本，明天恢复。进度会自动保存。",
            detail={"left": 0},
        )
    return CheckResult("quota", OK, f"今日还可下载 {left} 本", detail={"left": left})


# ── 编排 ────────────────────────────────────────────────────


def run_checks(
    fix: bool = False,
    include_network: bool = True,
    emit: Optional[Callable[[str], None]] = None,
) -> DoctorReport:
    """按成本递增跑检查。前置项失败时跳过后续网络检查，避免无谓等待。

    Args:
        fix: 是否自动修复（目前只有 cookies 可自动修）
        include_network: 是否做联网检查（cookies 探针 / 配额）
        emit: 进度回调，用于把「正在自动刷新」这类信息实时推给用户
    """
    report = DoctorReport()

    report.checks.append(check_dependencies())
    if report.get("dependencies").is_error:
        return report  # 依赖都没装，后面全跑不了

    report.checks.append(check_browser())
    report.checks.append(check_env_file())
    if report.get("env_file").is_error:
        return report  # 没配置文件 → 走向导，不用继续查

    report.checks.append(check_credentials())
    if report.get("credentials").is_error:
        return report

    report.checks.append(check_proxy())

    if not include_network:
        return report

    # 代理不通就别去刷 cookies 了，必然失败且要等超时
    if report.get("proxy").is_error:
        report.checks.append(
            CheckResult(
                "cookies",
                WARN,
                "跳过 Cookies 检查（代理不通）",
                hint="先解决代理问题。",
            )
        )
        return report

    report.checks.append(check_cookies(fix=fix, emit=emit))
    if report.get("cookies").is_error:
        return report

    report.checks.append(check_quota())
    return report


_LEVEL_ICON = {OK: "✓", WARN: "!", ERROR: "✗"}


def format_report(report: DoctorReport) -> str:
    """渲染成人类可读文本。给终端和 Web 日志共用。"""
    lines = []
    for c in report.checks:
        icon = _LEVEL_ICON.get(c.level, "?")
        line = f"  {icon} {c.message}"
        if c.level != OK and c.hint:
            line += f"\n      → {c.hint}"
        lines.append(line)
    body = "\n".join(lines)
    if report.ok:
        tail = "\n环境正常，可以开始。"
    else:
        tail = "\n有问题需要处理（见上面的 → 提示）。"
    return body + tail


def preflight(emit: Callable[[str], None] = print, need_quota: bool = True) -> bool:
    """跑下载任务前的预检 + 自愈。返回 True 表示可以继续。

    这是「开箱即用」的关键钩子：把过期 cookies 在开跑前就修好，而不是等批量任务
    跑到第 3 本时炸掉。cookies 修不好或代理不通则返回 False，让调用方早停。
    """
    report = run_checks(fix=True, emit=emit)
    if not report.ok:
        emit("[自检] 环境有问题，无法开始：")
        for c in report.errors:
            emit(f"  ✗ {c.message}")
            if c.hint:
                emit(f"    → {c.hint}")
        return False

    quota = report.get("quota")
    if need_quota and quota and quota.detail.get("left") == 0:
        emit("[自检] 今日下载配额已用完，明天再跑。进度已保存。")
        return False

    fixed = [c for c in report.checks if c.fixed]
    if fixed:
        emit("[自检] 已自动修复: " + "、".join(c.name for c in fixed))
    return True


def main() -> int:
    """CLI 入口：python doctor.py [--fix]"""
    import sys

    fix = "--fix" in sys.argv
    print("zlibrary-batch-download 环境自检" + ("（含自动修复）" if fix else ""))
    print("-" * 46)
    report = run_checks(fix=fix, emit=print)
    print(format_report(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
