# ebook_toolbox — 电子书处理工具箱

## 项目概览

面向个人电子书库整理的脚本集合：本地书单检索 → Z-Library 补全下载 → 重复文件清理。

启动 Web UI：`python web_server.py` → 访问 http://127.0.0.1:8000

## 核心约定

### 认证配置（`.env`）

```dotenv
ZLIBRARY_EMAIL=xxx
ZLIBRARY_PASSWORD=xxx
# 或（推荐）：
ZLIBRARY_REMIX_USERID=
ZLIBRARY_REMIX_USERKEY=
# 自定义域名（留空自动探测）
ZLIBRARY_DOMAIN=
# 代理（国内用户必需下载才需要）
ZLIBRARY_PROXY=
```

- **优先使用 Remix Token**（从浏览器 cookies 获取），而非明文密码
- ⚠️ `z-lib.id` 已被确认为**钓鱼站**，域名列表中已移除。见 [Awesome-Zlibrary](https://github.com/dongyubin/Awesome-Zlibrary)
- 域名自动探测顺序：`z-lib.by` → `z-library.gy` → `zh.zlib.li` → `zh.z-lib.rest`
- 从中国大陆访问官方域名需要**代理** + **Cloudflare cookies**（见下方）

### 认证/API 层

- `Zlibrary.py` — 同步客户端，基于 **HTML 页面抓取**（废弃旧 JSON API `/eapi/*`）
- 登录策略：先尝试 RPC (`/rpc.php`)，失败则表单登录（CSRF）
- `zlibrary_adapter.py` — 基于 `zlibrary` PyPI 包的同步适配器，支持代理链/Tor
- `zlibrary_runtime.py` — 统一的认证加载 + 客户端创建工厂

### Cloudflare 绕过

所有 Z-Library 官方域名（`z-lib.by` 等）都有 Cloudflare 浏览器验证保护，`requests` 直接访问返回 503。

**解决方案：** Playwright（真实浏览器）导出 cookies → `requests` 复用

1. 运行 `refresh_zlibrary_cookies.py` — 用 Playwright 打开浏览器，设置 Remix Token cookies，等待 Cloudflare 验证通过，导出 cookies 到 `zlibrary_cookies.json`
2. `Zlibrary.py` 的 `__init__` 加载 `cookies_file` 参数到 session
3. cookies 有效期内，`requests` 可正常访问（Cookie 持久化见 `_load_cookies_file()` / `save_cookies_file()`）
4. cookies 过期后重新运行 `refresh_zlibrary_cookies.py`（通常数天到数周有效）

**依赖：** `playwright`（首次需 `playwright install chromium`）

### 测试

```bash
python -m unittest discover -s tests
```

- `tests/test_zlibrary_runtime.py` — 认证/客户端工厂
- `tests/test_env_config.py` — `.env` 读取

### 代码红线

- **不要改 `Zlibrary.py` 的公开接口**（`search()`, `downloadBook()` 等）— 下游脚本依赖它
- 新增镜像站兼容 → 加域名到 `DOMAIN_BLACKLIST`，改 `_parse_search_results` 选择器
- 不改 `.env` 的 key 命名（`ZLIBRARY_*` 前缀）
