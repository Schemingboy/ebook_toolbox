# ebook_toolbox

丢一串书名进去，Z-Library 上有的它就自动给你下回来。

核心是**批量下载**：你手上有一串想读的书名（或者一个 Z-Library 书单页面的链接），工具逐本搜、逐本下，处理 Cloudflare 验证、绕开重复、尊重每日配额。不用你一本一本去站上点。

顺带也能管本地书库——查重、清理文件名、建索引——但那些是辅助。

## 一键装好

Windows + PowerShell（本项目的运行环境）：

```powershell
git clone https://github.com/Schemingboy/ebook_toolbox.git; cd ebook_toolbox; python -m venv .venv; .venv\Scripts\pip install -r requirements.txt; .venv\Scripts\python -m playwright install chromium
```

拉代码，建虚拟环境，装依赖，再装一个 Chromium（Cloudflare 人机验证需要真浏览器跑一遍）。要 Python 3.11+，不用装 Node。

装完还差一步——把 Z-Library 账号填进去。

## 填账号

把 `.env.example` 复制成 `.env`，填这几样：

```dotenv
# 推荐用 remix token（浏览器 cookies 里的 remix_userid 和 remix_userkey）
ZLIBRARY_REMIX_USERID=
ZLIBRARY_REMIX_USERKEY=

# 或者用邮箱密码，二选一
ZLIBRARY_EMAIL=
ZLIBRARY_PASSWORD=

# 留空自动探测可用域名
ZLIBRARY_DOMAIN=

# 国内必填，填你本地代理的端口
ZLIBRARY_PROXY=http://127.0.0.1:7897
```

Remix token 优先。拿法：登录 Z-Library 网页版，打开浏览器开发者工具 → Application → Cookies，找 `remix_userid` 和 `remix_userkey` 两个值。

填好之后跑一次：

```powershell
.venv\Scripts\python refresh_zlibrary_cookies.py
```

这一步用 Playwright 打开真浏览器过 Cloudflare 验证，把 cookies 存到 `zlibrary_cookies.json`。之后所有下载请求复用这份 cookies。过期了（通常几天到几周）重跑一次就行。

## 怎么用

### Web 界面

```powershell
.venv\Scripts\python web_server.py
```

自动弹浏览器，`http://127.0.0.1:8000`。界面上能配账号、测连接（看实时剩余配额）、选脚本填参数一键跑、看实时日志。

下载有两种喂法：

**喂书名**——把含《书名》的文本复制到剪贴板，界面里选「从剪贴板读取书单」启动。文本里没有《》会中止，这是防呆不是 bug。

**喂链接**——把 Z-Library 书单页的 URL 复制到剪贴板，选对应脚本启动，工具会解析页面里的书目逐本下载。

### 命令行

```powershell
# 先搜本地，本地没有的从 Z-Library 补
.venv\Scripts\python collect_ebooks_with_booklists.py

# 直接从 Z-Library 下载（读 处理结果.txt 里「未找到」的书名）
.venv\Scripts\python download_ebooks_from_zlibrary.py

# 解析 Z-Library 书单页面批量下载（URL 放剪贴板）
.venv\Scripts\python download_from_zlibrary_booklist.py
```

所有下载都先查本地索引，已有的跳过，不浪费配额。

## 给 AI Agent

你是 agent 的话，照这个顺序走：

**1. 装环境**——跑上面那条一键安装命令。之后所有 Python 调用**必须用** `.venv\Scripts\python`，系统 `python` 没装依赖会报错。

**2. 填配置**——复制 `.env.example` → `.env`，填 `ZLIBRARY_REMIX_USERID`、`ZLIBRARY_REMIX_USERKEY`、`ZLIBRARY_PROXY`。

**3. 过 Cloudflare**—— `.venv\Scripts\python refresh_zlibrary_cookies.py`。报 503 或 Cloudflare 拦截时重跑这条。

**4. 验证**—— `.venv\Scripts\python -m unittest discover -s tests`，或启动 Web 服务后 `POST /api/settings/test-auth` 确认登录和剩余配额。

**5. Web 服务**—— `.venv\Scripts\python web_server.py` 起在 `127.0.0.1:8000`。脚本执行走 WebSocket `/api/ws/run/{script_id}`，`GET /api/scripts` 拿脚本列表和参数定义。

**别动这些**：
- `.env`、`zlibrary_cookies.json`、`_file_index.sqlite3` 是本机文件，已 gitignore，别提交
- `Zlibrary.py` 的公开接口（`search()`、`downloadBook()` 等）下游依赖，别改签名
- Web 服务仅限本机访问，没有鉴权，不要对外暴露

## 注意事项

**域名**：`z-lib.id` 是钓鱼站，别用。`ZLIBRARY_DOMAIN` 留空会自动按 `z-lib.by → z-library.gy → zh.zlib.li → zh.z-lib.rest` 顺序试。

**配额**：普通账号每天 10 本。Web 界面的「测试连接」显示的剩余数是实时查 API 得到的真实值。配额用完工具会自动停，进度存着，第二天接着跑。

**代理**：国内直连官方域名不通。`.env` 里 `ZLIBRARY_PROXY` 填你本地代理端口，`http://` 或 `socks5://` 都行。

**Cloudflare**：所有官方域名都有浏览器验证，`requests` 直接访问返回 503。必须先跑 `refresh_zlibrary_cookies.py` 导出 cookies。cookies 通常有效几天到几周，过期重跑即可。

**首次索引**：第一次跑本地搜索会全盘扫描建 SQLite 索引，书多的话要等几分钟。之后增量更新，快很多。

**书名要带《》**：书单文本里的书名必须用《》包住，剪贴板模式尤其严格。

## 全部脚本

| 脚本 | 干什么 |
| --- | --- |
| `collect_ebooks_with_booklists.py` | 先搜本地，缺的从 Z-Library 补下 |
| `download_ebooks_from_zlibrary.py` | 读「处理结果」里未找到的书，去 Z-Library 下 |
| `download_from_zlibrary_booklist.py` | 解析 Z-Library 书单页面，批量下载 |
| `refresh_zlibrary_cookies.py` | 用真浏览器过 Cloudflare，导出 cookies |
| `collect_local_ebooks.py` | 在本地书库里按书名搜索、复制、归档 |
| `find_duplicated_files.py` | 找重复文件，导出 Markdown 报告 |
| `remove_duplicates_on_report.py` | 按报告删重复（丢回收站，不直接删） |
| `clean_booknames.py` | 清理文件名里的 `(Z-Library)`、编号尾缀 |
| `rename_epub_with_catalog.py` | 给 EPUB 合集文件名补上一级目录信息 |
| `doc2md.py` | 把一个目录里的 .doc/.docx 合并成 Markdown |
| `pull_md_images_to_local.py` | 把 Markdown 里的远程图片下到本地 |
| `web_server.py` | 启动 Web 控制台 |

## 测试

```powershell
.venv\Scripts\python -m unittest discover -s tests
```

## 来源

在 [famotime/ebook_toolbox](https://github.com/famotime/ebook_toolbox) 基础上改的。加了 Web 控制台、Cloudflare 绕过、真实配额查询、中文文件名乱码修复等。

仅供个人合法用途。请遵守当地版权法和 Z-Library 使用条款。
