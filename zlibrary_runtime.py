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


def create_zlibrary_client(auth: ZLibraryAuth, client_factory=Zlibrary):
    if not auth.remix_userid or not auth.remix_userkey:
        raise ValueError("缺少必要的认证信息：remix_userid 和 remix_userkey")

    return client_factory(
        remix_userid=auth.remix_userid,
        remix_userkey=auth.remix_userkey,
        domain=auth.domain,
        proxy=auth.proxy,
        cookies_file=DEFAULT_COOKIES_FILE,
    )


def find_pending_result_files(root_dir: Path | str, processed_files: set[str] | list[str] | None = None) -> list[Path]:
    root_dir = Path(root_dir)
    processed_files = set(processed_files or [])
    result_files = sorted(root_dir.rglob("处理结果.txt"))
    return [result_file for result_file in result_files if str(result_file) not in processed_files]
