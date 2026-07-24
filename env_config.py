from pathlib import Path


ENV_FILE = Path(__file__).resolve().parent / ".env"

# 默认支持的 Z-Library 域名列表（按优先级排序）
DEFAULT_DOMAINS = [
    "z-lib.by",
    "z-library.gy",
    "zh.zlib.li",
    "zh.z-lib.rest",
]


def _parse_env_line(line: str):
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None, None

    if stripped.startswith("export "):
        stripped = stripped[7:].strip()

    if "=" not in stripped:
        return None, None

    key, value = stripped.split("=", 1)
    key = key.strip()
    value = value.strip()

    if value and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]

    return key, value


def load_zlibrary_env(env_path: Path | None = None) -> dict[str, str]:
    """Load Z-Library configuration from a project-local .env file."""
    env_path = env_path or ENV_FILE
    config = {
        "email": "",
        "password": "",
        "remix_userid": "",
        "remix_userkey": "",
        "domain": "",              # 自定义 API 域名，为空则自动探测
        "proxy": "",               # HTTP/SOCKS5 代理，如 socks5://127.0.0.1:1080
        "fallback_domains": "",    # 额外备用域名（逗号分隔），覆盖默认列表
    }

    if not env_path.exists():
        return config

    with env_path.open("r", encoding="utf-8") as env_file:
        for line in env_file:
            key, value = _parse_env_line(line)
            if not key:
                continue

            if key == "ZLIBRARY_EMAIL":
                config["email"] = value
            elif key == "ZLIBRARY_PASSWORD":
                config["password"] = value
            elif key == "ZLIBRARY_REMIX_USERID":
                config["remix_userid"] = value
            elif key == "ZLIBRARY_REMIX_USERKEY":
                config["remix_userkey"] = value
            elif key == "ZLIBRARY_DOMAIN":
                config["domain"] = value
            elif key == "ZLIBRARY_PROXY":
                config["proxy"] = value
            elif key == "ZLIBRARY_FALLBACK_DOMAINS":
                config["fallback_domains"] = value

    return config


def get_domain_list(config: dict[str, str]) -> list[str]:
    """获取按优先级排列的域名列表（自定义域名为首选）。"""
    domains = []
    if config.get("domain"):
        domains.append(config["domain"])
    if config.get("fallback_domains"):
        domains.extend([d.strip() for d in config["fallback_domains"].split(",") if d.strip()])
    if not domains:
        domains = DEFAULT_DOMAINS.copy()
    return domains
