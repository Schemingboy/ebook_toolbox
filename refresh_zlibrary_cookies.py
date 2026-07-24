"""
用 Playwright 登录 Z-Library，导出 cookies 供 Zlibrary.py 使用。
运行一次后，Zlibrary.py 可以复用 cookies 来绕过 Cloudflare 验证。

用法:
    .venv\Scripts\python refresh_zlibrary_cookies.py

当报 Cloudflare 拦截错误时，重新运行本脚本。
脚本会用已有的 Remix Token 自动登录，无需手动操作。
"""
import json, sys
from pathlib import Path
from playwright.sync_api import sync_playwright

# 配置 — 从 .env 读取
try:
    from env_config import load_zlibrary_env
    env = load_zlibrary_env()
    DOMAIN = env.get("domain") or "z-lib.by"
    PROXY = env.get("proxy") or ""
    REMIX_UID = env.get("remix_userid", "")
    REMIX_KEY = env.get("remix_userkey", "")
except Exception:
    DOMAIN = "z-lib.by"
    PROXY = ""
    REMIX_UID = ""
    REMIX_KEY = ""

COOKIES_FILE = Path(__file__).resolve().parent / "zlibrary_cookies.json"


def refresh_cookies():
    """用 Playwright 打开 Z-Library，用 Remix Token 设置登录态，导出 cookies。"""
    base_url = f"https://{DOMAIN}"
    proxy_cfg = {"server": PROXY} if PROXY else None

    with sync_playwright() as p:
        # 先创建无痕上下文
        browser = p.chromium.launch(
            headless=True,  # 静默运行，无需显示窗口
            proxy=proxy_cfg,
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        )

        # 如果已有 Remix Token，预先设置 cookies 实现静默登录
        context.add_cookies([
            {"name": "remix_userid", "value": REMIX_UID, "domain": DOMAIN, "path": "/"},
            {"name": "remix_userkey", "value": REMIX_KEY, "domain": DOMAIN, "path": "/"},
        ])

        page = context.new_page()

        print(f"🌐 正在打开 {base_url}（静默模式）...")
        page.goto(base_url, timeout=60000)
        page.wait_for_load_state("networkidle", timeout=30000)
        print(f"📄 页面标题: {page.title()}")

        # 等待 Cloudflare 验证完成 + 页面渲染
        page.wait_for_timeout(3000)

        # 导出全部 cookies
        cookies = context.cookies()
        cookies_data = [
            {"name": c["name"], "value": c["value"], "domain": c["domain"].lstrip(".")}
            for c in cookies
        ]

        # 保存到文件
        COOKIES_FILE.write_text(
            json.dumps(cookies_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # 显示关键 cookie
        key_names = {"remix_userid", "remix_userkey", "bsrv", "c_token"}
        has_login = False
        print(f"\n🍪 已保存 {len(cookies_data)} 个 cookies:")
        for c in cookies_data:
            if c["name"] in key_names:
                val = c["value"][:25] + "..." if len(c["value"]) > 25 else c["value"]
                print(f"  {c['name']}: {val}")
                if c["name"] == "remix_userid":
                    has_login = True

        browser.close()

        if has_login:
            print(f"\n✅ Cookie 导出成功！可以正常使用搜索和下载了。")
        else:
            print(f"\n⚠️  未检测到 remix_userid cookie。可能 Remix Token 已过期。")
            print(f"   请运行 temp_get_remix_token.py 重新获取 Token。")

        return cookies_data


if __name__ == "__main__":
    refresh_cookies()
