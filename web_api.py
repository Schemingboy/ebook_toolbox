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

@app.get("/api/scripts")
def get_scripts():
    return [
        {
            "id": "collect_local_ebooks",
            "name": "按书名整理本地电子书",
            "description": "粘贴《书名》后搜索本地书库：已有文件复制到 output，未找到的书写入处理结果。",
            "params": [
                {"key": "list_dir", "label": "书单文件目录（可选）", "default": "", "tooltip": "关闭剪贴板模式后使用：填写包含TXT或MD书单的目录。"},
                {"key": "clipboard_content", "label": "粘贴《书名》运行", "type": "checkbox", "default": "true", "tooltip": "默认开启。读取含《》书名的剪贴板文本，不需要准备书单文件。"},
                {"key": "search_dir", "label": "本地电子书库", "default": str(DEFAULT_LIBRARY_DIR), "tooltip": "把已有的 EPUB、PDF、TXT、MOBI 或 AZW3 文件放在这里；程序只搜索，不下载。"},
                {"key": "skip_index_update", "label": "不更新索引", "type": "checkbox", "default": "false", "tooltip": "勾选后跳过文件索引的刷新检查，直接使用已有索引。适用于索引已是最新的情况，可节省等待时间。"},
                {"key": "output_dir", "label": "整理结果目录", "default": str(DEFAULT_OUTPUT_DIR), "tooltip": "找到的电子书和处理结果统一保存在这里。"},
            ]
        },
        {
            "id": "collect_ebooks_with_booklists",
            "name": "批量书单目录处理（高级）",
            "description": "读取本地 TXT/MD 书单目录并运行现有批处理；单本书名请使用上方入口。",
            "params": [
                {"key": "list_dir", "label": "书单文件目录", "default": "", "tooltip": "包含待搜集书单文件的目录，必须确保内容已被《》包围。必填。"},
                {"key": "search_dir", "label": "本地搜索基目录", "default": str(DEFAULT_LIBRARY_DIR), "tooltip": "本地搜索的扫描起点目录。"},
                {"key": "skip_index_update", "label": "不更新索引", "type": "checkbox", "default": "false", "tooltip": "勾选后跳过文件索引的刷新检查，直接使用已有索引。适用于索引已是最新的情况，可节省等待时间。"},
                {"key": "output_dir", "label": "输出目录", "default": str(DEFAULT_OUTPUT_DIR), "tooltip": "最终电子书的保存和合并输出位置。"},
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

    skip_index_update = params.get("skip_index_update", "false") == "true"
    use_clipboard = params.get("clipboard_content", "false") == "true"
    clipboard_text = params.get("clipboard_text", "") if use_clipboard else ""

    # 验证：剪贴板模式下不要求 list_dir
    raw_list_dir = params.get("list_dir", "")
    if not use_clipboard and not raw_list_dir:
        await websocket.send_text("错误：请填写书单文件目录(list_dir)或勾选'从剪贴板读取书单'！\n")
        await websocket.close()
        return

    if use_clipboard and not clipboard_text:
        await websocket.send_text("错误：已勾选'从剪贴板读取书单'，但未收到剪贴板内容！请先点击'读取剪贴板'或手动粘贴书单文本。\n")
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

    temp_script = Path(__file__).parent / f"temp_run_{script_id}.py"

    # 通用前导代码
    # line_buffering=True：子进程 stdout 是管道（非终端），默认块缓冲会让 print
    # 攒在缓冲区里，父进程 readline() 收不到换行 → GUI 卡在"正在启动"。按行刷新解决。
    preamble = (
        "import sys\n"
        "import io\n"
        "sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', line_buffering=True)\n"
        "sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', line_buffering=True)\n"
    )

    if script_id == "collect_local_ebooks":
        if use_clipboard and clipboard_text:
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
                        print(f"从剪贴板提取到 {{len(book_names)}} 本书，目录名：{{dir_name}}")
                        output_dir.mkdir(parents=True, exist_ok=True)
                        process_book_list(
                            output_dir / "书单", search_dir,
                            from_clipboard=True, output_dir=output_dir,
                            clipboard_content=clipboard_text,
                        )
                    else:
                        print("剪贴板中未找到《》标记的书名")
                except Exception as e:
                    print(f"发生异常: {{e}}")
            """)
        else:
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

    elif script_id == "collect_ebooks_with_booklists":
        if use_clipboard:
            clipboard_repr = repr(clipboard_text)
            script_code = preamble + dedent(f"""\
                from collect_ebooks_with_booklists import process_ebooks

                search_dir = {search_dir}
                output_dir = {output_dir}
                clipboard_text = {clipboard_repr}

                print("开始执行: 批量查缺补漏与下载流程（剪贴板模式）...")
                try:
                    process_ebooks("", search_dir, output_dir,
                                   skip_index_update={skip_index_update},
                                   clipboard_content=clipboard_text)
                except Exception as e:
                    print(f"发生异常: {{e}}")
            """)
        else:
            script_code = preamble + dedent(f"""\
                from collect_ebooks_with_booklists import process_ebooks

                list_dir = {list_dir}
                search_dir = {search_dir}
                output_dir = {output_dir}

                print("开始执行: 批量查缺补漏与下载流程...")
                try:
                    process_ebooks(list_dir, search_dir, output_dir,
                                   skip_index_update={skip_index_update})
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
