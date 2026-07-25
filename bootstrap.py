"""开箱即用启动器：备好环境，然后起 Web 服务。

为什么用 Python 而不是把逻辑写在 .cmd / .ps1 里：
  1. Windows PowerShell 5.1 读取无 BOM 的 UTF-8 脚本时按 ANSI 解析，中文提示会变乱码。
     Python 3 默认按 UTF-8 读源码，中文天然安全。
  2. 一份逻辑同时服务 Windows / macOS / Linux，不用维护三套。
启动器（start.cmd / start.ps1 / start.sh）因此只是纯 ASCII 的薄壳：找到 python，跑本文件。

本文件必须能用「系统 python」直接运行，所以只允许 import 标准库——
第三方依赖此刻可能还没装。

干的事，按顺序：
  1. 校验 Python 版本
  2. 没有 .venv 就建
  3. requirements.txt 变了才装依赖（用指纹比对，装过就秒过）
  4. Playwright 的 Chromium 缺了才下载
  5. frontend/dist 缺了才尝试构建（有 Node 才行）
  6. 起 web_server.py

用 --check 只做环境检查不起服务；用 --no-browser 不自动开浏览器。
"""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
VENV_DIR = PROJECT_DIR / ".venv"
REQUIREMENTS = PROJECT_DIR / "requirements.txt"
FINGERPRINT_FILE = VENV_DIR / ".deps-fingerprint"
FRONTEND_DIR = PROJECT_DIR / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"

MIN_PYTHON = (3, 11)

IS_WINDOWS = os.name == "nt"


def _log(message: str = "") -> None:
    print(message, flush=True)


def _step(message: str) -> None:
    print(f"  {message}", flush=True)


def venv_python() -> Path:
    """venv 里的解释器路径（可能还不存在）。"""
    if IS_WINDOWS:
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def check_python_version() -> bool:
    if sys.version_info < MIN_PYTHON:
        current = ".".join(str(p) for p in sys.version_info[:3])
        need = ".".join(str(p) for p in MIN_PYTHON)
        _log(f"[×] 需要 Python {need} 或更新，当前是 {current}。")
        _log("    下载： https://www.python.org/downloads/")
        if IS_WINDOWS:
            _log("    安装时记得勾上 “Add python.exe to PATH”。")
        return False
    return True


def ensure_venv() -> bool:
    """没有虚拟环境就建一个。已存在则直接复用。"""
    if venv_python().exists():
        return True

    _step("首次运行：正在创建虚拟环境 .venv（约 10 秒）…")
    try:
        subprocess.run(
            [sys.executable, "-m", "venv", str(VENV_DIR)],
            check=True,
            cwd=str(PROJECT_DIR),
        )
    except subprocess.CalledProcessError as exc:
        _log(f"[×] 创建虚拟环境失败（退出码 {exc.returncode}）。")
        if IS_WINDOWS:
            _log("    如果提示缺少 venv 模块，重装 Python 时勾选完整安装即可。")
        else:
            _log("    Debian/Ubuntu 可能需要先装： sudo apt install python3-venv")
        return False

    if not venv_python().exists():
        _log("[×] 虚拟环境建好了但找不到解释器，路径异常。")
        return False
    return True


def _requirements_fingerprint() -> str:
    """requirements.txt 的内容指纹。内容没变就跳过安装，省掉每次启动几十秒。"""
    if not REQUIREMENTS.exists():
        return ""
    return hashlib.sha256(REQUIREMENTS.read_bytes()).hexdigest()


def ensure_dependencies(force: bool = False) -> bool:
    """依赖清单变了（或首次）才 pip install。"""
    if not REQUIREMENTS.exists():
        _log("[×] 找不到 requirements.txt，项目文件不完整。")
        return False

    fingerprint = _requirements_fingerprint()
    recorded = ""
    if FINGERPRINT_FILE.exists():
        recorded = FINGERPRINT_FILE.read_text(encoding="utf-8").strip()

    if not force and recorded == fingerprint:
        return True

    if recorded:
        _step("依赖清单有更新，正在同步…")
    else:
        _step("首次运行：正在安装依赖（约 1-3 分钟，取决于网速）…")

    try:
        subprocess.run(
            [str(venv_python()), "-m", "pip", "install", "-q", "-r", str(REQUIREMENTS)],
            check=True,
            cwd=str(PROJECT_DIR),
        )
    except subprocess.CalledProcessError as exc:
        _log(f"[×] 安装依赖失败（退出码 {exc.returncode}）。")
        _log("    网络不通时可换国内源重试：")
        _log(f"    {venv_python()} -m pip install -r requirements.txt "
             "-i https://pypi.tuna.tsinghua.edu.cn/simple")
        return False

    FINGERPRINT_FILE.write_text(fingerprint, encoding="utf-8")
    return True


def _chromium_ready() -> bool:
    """Playwright 的 Chromium 下载好了没。问 playwright 自己要路径，别猜目录。"""
    probe = (
        "import sys\n"
        "try:\n"
        "    from playwright.sync_api import sync_playwright\n"
        "except Exception:\n"
        "    sys.exit(2)\n"
        "from pathlib import Path\n"
        "with sync_playwright() as p:\n"
        "    sys.exit(0 if Path(p.chromium.executable_path).exists() else 1)\n"
    )
    try:
        result = subprocess.run(
            [str(venv_python()), "-c", probe],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            timeout=90,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return result.returncode == 0


def ensure_browser() -> bool:
    """Cloudflare 人机验证要真浏览器跑一遍，所以 Chromium 是必需的。"""
    if _chromium_ready():
        return True

    _step("首次运行：正在下载 Chromium 浏览器（约 150MB，用于通过人机验证）…")
    try:
        subprocess.run(
            [str(venv_python()), "-m", "playwright", "install", "chromium"],
            check=True,
            cwd=str(PROJECT_DIR),
        )
    except subprocess.CalledProcessError as exc:
        _log(f"[×] 下载 Chromium 失败（退出码 {exc.returncode}）。")
        _log("    可能是网络问题。挂上代理后重新运行启动器即可。")
        return False

    if not _chromium_ready():
        _log("[×] Chromium 装完仍不可用。")
        return False
    return True


def _which(name: str) -> str:
    from shutil import which

    return which(name) or ""


def ensure_frontend() -> bool:
    """Web 界面的静态文件。

    frontend/dist 已随仓库提交，正常情况下这里什么都不用做。
    只有当它意外缺失时才兜底：本机有 Node 就现场构建，没有就说清楚怎么办。
    界面缺失不阻止服务启动（命令行脚本仍可用），所以永远返回 True。
    """
    if (FRONTEND_DIST / "index.html").exists():
        return True

    _step("Web 界面文件缺失，尝试现场构建…")
    npm = _which("npm")
    if not npm:
        _log("[!] 没检测到 Node.js，无法构建 Web 界面。")
        _log("    办法一：装 Node.js（https://nodejs.org）后重新运行启动器。")
        _log("    办法二：重新拉取完整仓库（frontend/dist 本应随仓库一起下载）。")
        return True

    try:
        subprocess.run([npm, "install"], check=True, cwd=str(FRONTEND_DIR))
        subprocess.run([npm, "run", "build"], check=True, cwd=str(FRONTEND_DIR))
    except (subprocess.CalledProcessError, OSError) as exc:
        _log(f"[!] 构建 Web 界面失败：{exc}")
        _log("    服务仍会启动，但网页可能打不开。")
        return True

    if (FRONTEND_DIST / "index.html").exists():
        _step("Web 界面构建完成。")
    return True


def run_server(open_browser: bool = True) -> int:
    """把控制权交给 web_server.py。用 venv 的解释器跑，依赖都在那儿。"""
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    if not open_browser:
        env["EBOOK_TOOLBOX_NO_BROWSER"] = "1"

    cmd = [str(venv_python()), "-u", str(PROJECT_DIR / "web_server.py")]
    try:
        return subprocess.call(cmd, cwd=str(PROJECT_DIR), env=env)
    except KeyboardInterrupt:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ebook_toolbox 启动器")
    parser.add_argument("--check", action="store_true", help="只检查环境，不启动服务")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--reinstall", action="store_true", help="强制重装依赖")
    args = parser.parse_args(argv)

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    _log("ebook_toolbox")
    _log("=" * 46)

    if not check_python_version():
        return 1
    if not ensure_venv():
        return 1
    if not ensure_dependencies(force=args.reinstall):
        return 1
    if not ensure_browser():
        return 1
    ensure_frontend()

    _log("环境就绪。")

    if args.check:
        # 顺手跑一遍配置层面的自检（账号 / 代理 / cookies）
        _log("")
        return subprocess.call(
            [str(venv_python()), "-u", str(PROJECT_DIR / "doctor.py")],
            cwd=str(PROJECT_DIR),
        )

    _log("正在启动 Web 界面… 浏览器会自动打开 http://127.0.0.1:8000")
    _log("（关掉这个窗口即停止服务）")
    _log("")
    return run_server(open_browser=not args.no_browser)


if __name__ == "__main__":
    raise SystemExit(main())
