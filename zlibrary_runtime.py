from dataclasses import dataclass
from pathlib import Path

from Zlibrary import Zlibrary
from env_config import load_zlibrary_env

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_COOKIES_FILE = str(PROJECT_DIR / "zlibrary_cookies.json")


@dataclass
class ZLibraryAuth:
    remix_userid: str = ""
    remix_userkey: str = ""
    domain: str = ""       # 自定义域名
    proxy: str = ""        # 代理


def load_zlibrary_auth(
    env_path: Path | None = None,
    client_factory=Zlibrary,
) -> ZLibraryAuth:
    env_path = env_path or Path(__file__).resolve().parent / ".env"
    zlibrary_account = load_zlibrary_env(env_path)

    # 优先使用已配置的 Remix Token（无需网络请求）
    if zlibrary_account.get("remix_userid") and zlibrary_account.get("remix_userkey"):
        return ZLibraryAuth(
            remix_userid=zlibrary_account["remix_userid"],
            remix_userkey=zlibrary_account["remix_userkey"],
            domain=zlibrary_account.get("domain", ""),
            proxy=zlibrary_account.get("proxy", ""),
        )

    # 无 Token 但有邮箱密码 → 尝试登录提取 Token
    if zlibrary_account.get("email") and zlibrary_account.get("password"):
        try:
            temp_client = client_factory(
                email=zlibrary_account["email"],
                password=zlibrary_account["password"],
                domain=zlibrary_account.get("domain", ""),
                proxy=zlibrary_account.get("proxy", ""),
            )
            profile = temp_client.getProfile()
            if profile.get("success"):
                user = profile["user"]
                return ZLibraryAuth(
                    remix_userid=str(user["id"]),
                    remix_userkey=user["remix_userkey"],
                    domain=zlibrary_account.get("domain", ""),
                    proxy=zlibrary_account.get("proxy", ""),
                )
        except Exception as e:
            # 登录失败（含 Cloudflare 拦截），返回空的 auth 让下游报错
            pass

    return ZLibraryAuth(
        remix_userid=zlibrary_account.get("remix_userid", ""),
        remix_userkey=zlibrary_account.get("remix_userkey", ""),
        domain=zlibrary_account.get("domain", ""),
        proxy=zlibrary_account.get("proxy", ""),
    )


def _default_refresh_hook() -> bool:
    """撞到 Cloudflare 时自动刷新 cookies。

    延迟 import cookie_manager：它依赖 playwright，而部分只读脚本（跑测试、
    解析本地书单）不该因为缺浏览器就 import 失败。
    """
    try:
        from cookie_manager import refresh_cookies
    except Exception as exc:
        print(f"[cookies] 无法加载自动刷新模块: {exc}")
        return False
    try:
        refresh_cookies()
        return True
    except Exception as exc:
        print(f"[cookies] 自动刷新失败: {exc}")
        return False


def create_zlibrary_client(
    auth: ZLibraryAuth,
    client_factory=Zlibrary,
    auto_refresh: bool = True,
):
    """创建客户端。auto_refresh=True 时挂上 cookies 自动刷新（默认）。

    所有下游下载脚本走这个工厂，因此自动刷新是一次性继承的——撞到 Cloudflare
    时客户端自己刷 cookies 重试，不需要用户去终端跑命令。
    """
    if not auth.remix_userid or not auth.remix_userkey:
        raise ValueError("缺少必要的认证信息：remix_userid 和 remix_userkey")

    kwargs = dict(
        remix_userid=auth.remix_userid,
        remix_userkey=auth.remix_userkey,
        domain=auth.domain,
        proxy=auth.proxy,
        cookies_file=DEFAULT_COOKIES_FILE,
    )
    if auto_refresh:
        kwargs["auto_refresh_hook"] = _default_refresh_hook
    try:
        return client_factory(**kwargs)
    except TypeError:
        # 测试里的假 factory 可能不接受 auto_refresh_hook，降级重试
        kwargs.pop("auto_refresh_hook", None)
        return client_factory(**kwargs)


def find_pending_result_files(root_dir: Path | str, processed_files: set[str] | list[str] | None = None) -> list[Path]:
    root_dir = Path(root_dir)
    processed_files = set(processed_files or [])
    result_files = sorted(root_dir.rglob("处理结果.txt"))
    return [result_file for result_file in result_files if str(result_file) not in processed_files]
