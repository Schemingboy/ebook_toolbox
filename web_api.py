import os
import sys
import asyncio
from pathlib import Path
from textwrap import dedent
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from env_config import load_zlibrary_env, ENV_FILE
from book_ranking import load_preferences, save_preferences

app = FastAPI()
PROJECT_DIR = Path(__file__).parent


def _resolve_python_executable() -> str:
    """优先使用项目内 .venv 的解释器（依赖装在这里），找不到再回退当前解释器。

    GUI 若用系统 python 启动本服务，sys.executable 会指向缺依赖的系统解释器，
    导致子进程 import pyperclip 等失败。这里显式探测项目虚拟环境。
    """
    if os.name == "nt":
        candidate = PROJECT_DIR / ".venv" / "Scripts" / "python.exe"
    else:
        candidate = PROJECT_DIR / ".venv" / "bin" / "python"
    if candidate.exists():
        return str(candidate)
    return sys.executable


PYTHON_EXECUTABLE = _resolve_python_executable()
COOKIES_FILE = str(PROJECT_DIR / "zlibrary_cookies.json")
DEFAULT_LIBRARY_DIR = PROJECT_DIR / "library"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "output"

DEFAULT_LIBRARY_DIR.mkdir(exist_ok=True)
DEFAULT_OUTPUT_DIR.mkdir(exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

frontend_dist = Path(__file__).parent / "frontend" / "dist"

class EnvConfigModel(BaseModel):
    zlibrary_email: str = ""
    zlibrary_password: str = ""
    zlibrary_remix_userid: str = ""
    zlibrary_remix_userkey: str = ""
    zlibrary_domain: str = ""
    zlibrary_proxy: str = ""

@app.get("/api/settings")
def get_settings():
    config = load_zlibrary_env()
    return config

@app.post("/api/settings")
def save_settings(config: EnvConfigModel):
    lines = []
    if ENV_FILE.exists():
        with ENV_FILE.open("r", encoding="utf-8") as f:
            lines = f.readlines()

    def update_or_append(lines_arr, key, val, keep_if_empty=False):
        """写入环境变量。keep_if_empty=True 时，如果 val 为空则不覆盖已有值。"""
        if keep_if_empty and not val:
            return
        found = False
        for i, line in enumerate(lines_arr):
            if line.strip().startswith(f"{key}="):
                lines_arr[i] = f"{key}={val}\n"
                found = True
                break
        if not found:
            lines_arr.append(f"{key}={val}\n")

    update_or_append(lines, "ZLIBRARY_EMAIL", config.zlibrary_email)
    update_or_append(lines, "ZLIBRARY_PASSWORD", config.zlibrary_password)
    update_or_append(lines, "ZLIBRARY_REMIX_USERID", config.zlibrary_remix_userid)
    update_or_append(lines, "ZLIBRARY_REMIX_USERKEY", config.zlibrary_remix_userkey)
    # 域名和代理：用户没填时不覆盖已有的值
    update_or_append(lines, "ZLIBRARY_DOMAIN", config.zlibrary_domain, keep_if_empty=True)
    update_or_append(lines, "ZLIBRARY_PROXY", config.zlibrary_proxy, keep_if_empty=True)

    with ENV_FILE.open("w", encoding="utf-8") as f:
        f.writelines(lines)

    return {"status": "ok"}

class AuthTestResponse(BaseModel):
    success: bool
    message: str
    user_info: dict | None = None

@app.post("/api/settings/test-auth", response_model=AuthTestResponse)
def test_auth(config: EnvConfigModel):
    """测试 Z-Library 账号连接。"""
    try:
        from Zlibrary import Zlibrary, ZLibraryError, LoginError

        # 优先使用前端传入的值，如果为空则从 .env 读取
        env_config = load_zlibrary_env()
        domain = config.zlibrary_domain.strip() or env_config.get("domain", "z-lib.by")
        proxy = config.zlibrary_proxy.strip() or env_config.get("proxy", "")

        # 优先尝试 token 登录（前端传入 > .env）
        remix_uid = config.zlibrary_remix_userid or env_config.get("remix_userid", "")
        remix_key = config.zlibrary_remix_userkey or env_config.get("remix_userkey", "")
        email = config.zlibrary_email or env_config.get("email", "")
        password = config.zlibrary_password or env_config.get("password", "")

        if remix_uid and remix_key:
            client = Zlibrary(
                remix_userid=remix_uid,
                remix_userkey=remix_key,
                domain=domain,
                proxy=proxy,
                cookies_file=COOKIES_FILE,
            )
        elif email and password:
            client = Zlibrary(
                email=email,
                password=password,
                domain=domain,
                proxy=proxy,
                cookies_file=COOKIES_FILE,
            )
        else:
            return AuthTestResponse(
                success=False,
                message="请至少填写 邮箱+密码 或 Remix Token",
            )

        profile = client.getProfile()
        if profile.get("success"):
            user = profile["user"]
            remaining = client.getDownloadsLeft()
            return AuthTestResponse(
                success=True,
                message=f"连接成功！用户: {user.get('name', '未知')}，今日剩余配额: {remaining} 本",
                user_info={
                    "name": user.get("name"),
                    "email": user.get("email"),
                    "remix_userid": user.get("remix_userid"),
                    "downloads_left": remaining,
                },
            )
        else:
            return AuthTestResponse(
                success=False,
                message=f"登录失败: {profile.get('error', '凭据无效')}",
            )

    except LoginError as e:
        return AuthTestResponse(success=False, message=f"登录失败: {e}")
    except ZLibraryError as e:
        return AuthTestResponse(success=False, message=f"连接失败: {e}")
    except Exception as e:
        return AuthTestResponse(success=False, message=f"未知错误: {e}")

class PreferencesModel(BaseModel):
    format_priority: list[str] = []
    language_priority: list[str] = []
    prefer_newer_year: bool = True
    size_preference: str = "none"
    min_rating: float = 0.0


@app.get("/api/preferences")
def get_preferences():
    """读取版本优先级偏好（缺文件返回默认）。"""
    return load_preferences()


@app.post("/api/preferences")
def post_preferences(prefs: PreferencesModel):
    """保存版本优先级偏好，返回规整后的值。"""
    return save_preferences(prefs.model_dump())


# 需要联网（因此需要预检 cookies/代理/配额）的脚本。纯本地检索不必等自检。
NEEDS_NETWORK_SCRIPTS = {"download_by_isbn", "collect_ebooks"}


async def _run_preflight(websocket: WebSocket) -> bool:
    """跑任务前的环境自检 + 自愈，把过程实时推给前端。返回是否可以继续。

    起子进程：doctor 的修复路径会调 playwright 同步 API，在事件循环线程里
    直接调会抛 "Sync API inside asyncio loop"。
    """
    code = (
        "import sys, io\n"
        "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)\n"
        "import doctor\n"
        "ok = doctor.preflight(emit=print)\n"
        "print('__PREFLIGHT__' + ('ok' if ok else 'fail'))\n"
    )
    process = await asyncio.create_subprocess_exec(
        PYTHON_EXECUTABLE, "-u", "-c", code,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(PROJECT_DIR),
    )
    ok = False
    while True:
        raw = await process.stdout.readline()
        if not raw:
            break
        line = raw.decode("utf-8", errors="replace")
        if "__PREFLIGHT__" in line:
            ok = "__PREFLIGHT__ok" in line
            continue
        await websocket.send_text(line)
    await process.wait()
    if not ok:
        await websocket.send_text("\n[已中止] 环境未就绪，任务没有开始。按上面的提示处理后重试。\n")
    return ok


class SetupModel(BaseModel):
    email: str = ""
    password: str = ""
    remix_userid: str = ""
    remix_userkey: str = ""
    proxy: str = ""
    domain: str = ""


@app.get("/api/doctor")
def get_doctor(fix: bool = False):
    """环境自检。fix=true 时顺手自动修（刷 cookies 等）。

    前端启动时先调这个：needs_setup=true 就进首次运行向导，否则直接进主界面。
    """
    import doctor

    return doctor.run_checks(fix=fix).to_dict()


@app.get("/api/cookies/status")
def get_cookies_status():
    """Cookies 健康度（纯本地判断，不发网络请求）。"""
    import cookie_manager

    return cookie_manager.cookies_status().to_dict()


@app.post("/api/cookies/refresh")
def post_cookies_refresh():
    """手动刷新 cookies。

    起子进程跑：cookie_manager 用的是 playwright 同步 API，在 FastAPI 的事件循环
    线程里直接调会抛 "Sync API inside asyncio loop"。同 web_api 拉脚本的既有约定。
    """
    import json as _json
    import subprocess

    code = (
        "import json, sys\n"
        "import cookie_manager\n"
        "try:\n"
        "    st = cookie_manager.refresh_cookies(log=lambda *a: None)\n"
        "    print('__RESULT__' + json.dumps({'success': True, 'status': st.to_dict()}, ensure_ascii=False))\n"
        "except Exception as exc:\n"
        "    print('__RESULT__' + json.dumps({'success': False, 'message': str(exc)}, ensure_ascii=False))\n"
    )
    try:
        proc = subprocess.run(
            [PYTHON_EXECUTABLE, "-u", "-c", code],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(
            {"success": False, "message": "刷新超时（180 秒）。检查代理是否开启。"},
            status_code=504,
        )

    for line in (proc.stdout or "").splitlines():
        if line.startswith("__RESULT__"):
            payload = _json.loads(line[len("__RESULT__"):])
            return JSONResponse(payload, status_code=200 if payload.get("success") else 400)

    return JSONResponse(
        {"success": False, "message": f"刷新进程异常退出（{proc.returncode}）: {(proc.stderr or '')[-400:]}"},
        status_code=500,
    )


@app.post("/api/setup")
def post_setup(payload: SetupModel):
    """首次运行向导：邮箱密码 → 自动换 remix token → 写 .env → 导出 cookies。

    让新用户不必开 DevTools 翻 cookies。同样起子进程（playwright 同步 API）。
    """
    import json as _json
    import subprocess

    args = _json.dumps(payload.model_dump(), ensure_ascii=False)
    code = (
        "import json, sys\n"
        "import cookie_manager\n"
        f"args = json.loads({args!r})\n"
        "try:\n"
        "    result = cookie_manager.setup_from_credentials(**args)\n"
        "    print('__RESULT__' + json.dumps({'success': True, **result}, ensure_ascii=False))\n"
        "except Exception as exc:\n"
        "    print('__RESULT__' + json.dumps({'success': False, 'message': str(exc)}, ensure_ascii=False))\n"
    )
    try:
        proc = subprocess.run(
            [PYTHON_EXECUTABLE, "-u", "-c", code],
            cwd=str(PROJECT_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=240,
        )
    except subprocess.TimeoutExpired:
        return JSONResponse(
            {"success": False, "message": "配置超时（240 秒）。检查网络或代理。"},
            status_code=504,
        )

    for line in (proc.stdout or "").splitlines():
        if line.startswith("__RESULT__"):
            result = _json.loads(line[len("__RESULT__"):])
            return JSONResponse(result, status_code=200 if result.get("success") else 400)

    return JSONResponse(
        {"success": False, "message": f"配置进程异常退出（{proc.returncode}）: {(proc.stderr or '')[-400:]}"},
        status_code=500,
    )


@app.get("/api/proxy/detect")
def get_proxy_detect():
    """探测本机常见代理端口，供向导预填。"""
    import doctor

    return {"candidates": doctor.detect_local_proxies()}


@app.get("/api/scripts")
def get_scripts():
    return [
        {
            "id": "collect_ebooks",
            "name": "整理 / 补全本地书库",
            "description": "粘贴书名（可带《》，不带也行，按行/顿号自动拆）搜索本地书库：已有文件复制到输出目录，未找到的写入处理结果。可选让缺失的书从 Z-Library 补下。",
            "params": [
                {"key": "clipboard_content", "label": "粘贴书名运行", "type": "checkbox", "default": "true", "tooltip": "默认开启。读取剪贴板书名文本，不需要准备书单文件。书名可用《》包裹，也可每行一个或用、，；分隔。"},
                {"key": "list_dir", "label": "书单文件目录（关闭剪贴板时用）", "default": "", "tooltip": "关闭剪贴板模式后使用：填写包含 TXT 或 MD 书单的目录。"},
                {"key": "fill_from_zlibrary", "label": "本地缺失的从 Z-Library 补下", "type": "checkbox", "default": "false", "tooltip": "仅目录模式生效：本地搜完后，未找到的书自动去 Z-Library 下载（消耗每日配额，按版本优先级选版本）。剪贴板模式只搜本地不下载。"},
                {"key": "search_dir", "label": "本地电子书库", "default": str(DEFAULT_LIBRARY_DIR), "tooltip": "把已有的 EPUB、PDF、TXT、MOBI 或 AZW3 文件放在这里；程序只搜索，不删改。"},
                {"key": "skip_index_update", "label": "不更新索引", "type": "checkbox", "default": "false", "tooltip": "勾选后跳过文件索引的刷新检查，直接使用已有索引。适用于索引已是最新的情况，可节省等待时间。"},
                {"key": "output_dir", "label": "整理结果目录", "default": str(DEFAULT_OUTPUT_DIR), "tooltip": "找到的电子书和处理结果统一保存在这里。"},
            ]
        },
        {
            "id": "download_by_isbn",
            "name": "按 ISBN 批量下载",
            "description": "粘贴 ISBN（一行一个，10 或 13 位，带不带连字符都行），逐个去 Z-Library 搜索下载，按版本优先级自动选版本。消耗每日下载配额。",
            "params": [
                {"key": "clipboard_content", "label": "粘贴 ISBN 运行", "type": "checkbox", "default": "true", "tooltip": "默认开启。读取剪贴板里的 ISBN 文本，一行一个。"},
                {"key": "isbn_text", "label": "ISBN 列表（每行一个）", "type": "textarea", "default": "", "tooltip": "关闭剪贴板时在此手动粘贴，一行一个 ISBN。"},
                {"key": "output_dir", "label": "下载保存目录", "default": str(DEFAULT_OUTPUT_DIR), "tooltip": "下载的电子书保存在这里。"},
            ]
        }
    ]


def validate_workflow_path(value: str, label: str, must_exist: bool = False) -> Path:
    path = Path(value.strip())
    if not path.is_absolute():
        raise ValueError(f"{label}必须是完整路径，例如：{DEFAULT_OUTPUT_DIR}")
    if must_exist and not path.exists():
        raise ValueError(f"{label}不存在：{path}")
    return path


@app.websocket("/api/ws/run/{script_id}")
async def run_script_websocket(websocket: WebSocket, script_id: str):
    await websocket.accept()
    # receive params
    data = await websocket.receive_json()
    params = data.get("params", {})

    use_clipboard = params.get("clipboard_content", "false") == "true"
    clipboard_text = params.get("clipboard_text", "") if use_clipboard else ""

    # 通用前导代码
    # line_buffering=True：子进程 stdout 是管道（非终端），默认块缓冲会让 print
    # 攒在缓冲区里，父进程 readline() 收不到换行 → GUI 卡在"正在启动"。按行刷新解决。
    preamble = (
        "import sys\n"
        "import io\n"
        "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)\n"
        "sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)\n"
    )

    temp_script = Path(__file__).parent / f"temp_run_{script_id}.py"

    # 跑任务前自动过一遍环境自检并自愈（过期 cookies 在这里就修好，
    # 而不是等批量任务跑到第 3 本时撞 Cloudflare 炸掉）。
    # 放在子进程里跑：doctor 的修复路径会调 playwright 同步 API。
    if script_id in NEEDS_NETWORK_SCRIPTS:
        ok = await _run_preflight(websocket)
        if not ok:
            await websocket.close()
            return

    # ── 按 ISBN 批量下载 ──────────────────────────────────
    if script_id == "download_by_isbn":
        isbn_text = clipboard_text if use_clipboard else params.get("isbn_text", "")
        if not isbn_text.strip():
            await websocket.send_text("错误：未收到 ISBN 内容！请在文本框粘贴（一行一个），或勾选剪贴板模式后复制 ISBN。\n")
            await websocket.close()
            return
        try:
            output_dir = repr(str(validate_workflow_path(
                params.get("output_dir", str(DEFAULT_OUTPUT_DIR)),
                "下载保存目录",
            )))
        except ValueError as error:
            await websocket.send_text(f"错误：{error}\n")
            await websocket.close()
            return

        isbn_repr = repr(isbn_text)
        script_code = preamble + dedent(f"""\
            import time
            from pathlib import Path
            from isbn_utils import extract_isbns
            from download_ebooks_from_zlibrary import (
                DOWNLOAD_INTERVAL_SECONDS,
                ZLibraryConfig,
                ZLibraryDownloader,
            )

            output_dir = Path({output_dir})
            output_dir.mkdir(parents=True, exist_ok=True)

            isbns = extract_isbns({isbn_repr})
            print(f"识别到 {{len(isbns)}} 个 ISBN")
            if not isbns:
                print("未识别到合法 ISBN（需 10 或 13 位）。请检查输入。")
            else:
                config = ZLibraryConfig.load_account_info()
                config.target_dir = output_dir
                try:
                    downloader = ZLibraryDownloader(config)
                except Exception as e:
                    print(f"初始化失败（检查账号配置）: {{e}}")
                    downloader = None
                if downloader is not None:
                    ok = 0
                    for idx, isbn in enumerate(isbns, 1):
                        print(f"\\n[{{idx}}/{{len(isbns)}}] 处理 ISBN: {{isbn}}")
                        try:
                            result = downloader.search_and_download_by_isbn(isbn)
                            if result:
                                ok += 1
                        except Exception as e:
                            if str(e) == "QUOTA_EXCEEDED":
                                print("今日下载配额已用完，停止。剩余 ISBN 请明天再跑。")
                                break
                            print(f"处理 ISBN {{isbn}} 出错: {{e}}")
                        # 与书名下载路径同一节流常量：每本至少 3 个请求
                        # （搜索 + 查配额 + 下载），无间隔连打是最扎眼的模式。
                        # 最后一本不用等。
                        if idx < len(isbns):
                            time.sleep(DOWNLOAD_INTERVAL_SECONDS)
                    print(f"\\n完成：成功 {{ok}} / {{len(isbns)}} 本")
        """)

    # ── 整理 / 补全本地书库 ───────────────────────────────
    elif script_id == "collect_ebooks":
        skip_index_update = params.get("skip_index_update", "false") == "true"
        fill_from_zlibrary = params.get("fill_from_zlibrary", "false") == "true"
        raw_list_dir = params.get("list_dir", "")

        if not use_clipboard and not raw_list_dir:
            await websocket.send_text("错误：请填写书单文件目录，或勾选'粘贴书名运行'！\n")
            await websocket.close()
            return
        if use_clipboard and not clipboard_text.strip():
            await websocket.send_text("错误：已勾选'粘贴书名运行'，但未收到剪贴板内容！请先复制书名文本。\n")
            await websocket.close()
            return

        try:
            search_dir = repr(str(validate_workflow_path(
                params.get("search_dir", str(DEFAULT_LIBRARY_DIR)),
                "本地电子书库",
                must_exist=True,
            )))
            output_dir = repr(str(validate_workflow_path(
                params.get("output_dir", str(DEFAULT_OUTPUT_DIR)),
                "输出目录",
            )))
            list_dir = repr(str(validate_workflow_path(
                raw_list_dir,
                "书单文件目录",
                must_exist=True,
            ))) if not use_clipboard else repr("")
        except ValueError as error:
            await websocket.send_text(f"错误：{error}\n")
            await websocket.close()
            return

        if use_clipboard and clipboard_text:
            # 剪贴板模式：只搜本地，不下载（含放宽《》的解析）
            clipboard_repr = repr(clipboard_text)
            script_code = preamble + dedent(f"""\
                from pathlib import Path
                from collect_local_ebooks import (
                    check_file_list_update, generate_file_list,
                    extract_book_names, clean_dirname, process_book_list,
                )

                search_dir = {search_dir}
                output_dir = Path({output_dir})

                clipboard_text = {clipboard_repr}

                print("开始执行: 本地电子书搜集（剪贴板模式）...")
                try:
                    if not {skip_index_update}:
                        if check_file_list_update(search_dir):
                            generate_file_list(search_dir)
                    else:
                        print("已跳过索引更新（使用历史索引）")

                    book_names = extract_book_names(clipboard_text)
                    if book_names:
                        lines = clipboard_text.splitlines()
                        dir_name = clean_dirname(lines[0].strip()) if lines else "新建书单"
                        print(f"提取到 {{len(book_names)}} 本书，目录名：{{dir_name}}")
                        output_dir.mkdir(parents=True, exist_ok=True)
                        process_book_list(
                            output_dir / "书单", search_dir,
                            from_clipboard=True, output_dir=output_dir,
                            clipboard_content=clipboard_text,
                        )
                    else:
                        print("未能从文本中解析出任何书名")
                except Exception as e:
                    print(f"发生异常: {{e}}")
            """)
        elif fill_from_zlibrary:
            # 目录模式 + 补下：走 process_ebooks（本地 + Z-Library 补漏）
            script_code = preamble + dedent(f"""\
                from collect_ebooks_with_booklists import process_ebooks

                list_dir = {list_dir}
                search_dir = {search_dir}
                output_dir = {output_dir}

                print("开始执行: 本地搜集 + Z-Library 补漏下载...")
                try:
                    process_ebooks(list_dir, search_dir, output_dir,
                                   skip_index_update={skip_index_update})
                except Exception as e:
                    print(f"发生异常: {{e}}")
            """)
        else:
            # 目录模式，只搜本地
            script_code = preamble + dedent(f"""\
                from pathlib import Path
                from collect_local_ebooks import process_book_list_directory, check_file_list_update, generate_file_list

                list_dir = {list_dir}
                search_dir = {search_dir}
                output_dir = Path({output_dir})

                print("开始执行: 本地电子书搜集...")
                try:
                    if not {skip_index_update}:
                        if check_file_list_update(search_dir):
                            generate_file_list(search_dir)
                    else:
                        print("已跳过索引更新（使用历史索引）")
                    process_book_list_directory(list_dir, search_dir, output_dir=output_dir)
                except Exception as e:
                    print(f"发生异常: {{e}}")
            """)
    else:
        await websocket.send_text("未知的脚本运行请求")
        await websocket.close()
        return

    with temp_script.open("w", encoding="utf-8") as f:
        f.write(script_code)

    process = await asyncio.create_subprocess_exec(
        PYTHON_EXECUTABLE, "-u", str(temp_script),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
        cwd=str(Path(__file__).parent)
    )

    try:
        while True:
            line = await process.stdout.readline()
            if not line:
                break
            await websocket.send_text(line.decode("utf-8", errors="replace"))

        await process.wait()
        await websocket.send_text(f"\n[进程结束，退出码：{process.returncode}]")
    except Exception as e:
        await websocket.send_text(f"错误: {str(e)}")
    finally:
        if temp_script.exists():
            try:
                temp_script.unlink()
            except:
                pass
        await websocket.close()

if frontend_dist.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dist), html=True), name="frontend")
