# zlibrary-batch-download

丢一串书名进去，Z-Library 上有的它就自动给你下回来。

核心是**批量下载**：你手上有一串想读的书名、一串 ISBN、或者一个 Z-Library 书单页面的链接，工具逐本搜、逐本下，处理 Cloudflare 验证、绕开重复、尊重每日配额。不用你一本一本去站上点。同一本书搜到多个版本时，按你在界面里定的**版本优先级**（格式 / 语言 / 年份 / 体积 / 评分）自动挑最合适的那一版。

顺带也能管本地书库——查重、清理文件名、建索引——但那些是辅助。

## 开箱即用

拉下代码，**双击 `start.cmd`**（macOS / Linux 跑 `./start.sh`），就完事了。

```powershell
git clone https://github.com/Schemingboy/zlibrary-batch-download.git
cd zlibrary-batch-download
.\start.cmd
```

启动器自己会把该做的做完：找 Python（要 3.11+）→ 建虚拟环境 → 装依赖 → 下载 Chromium（Cloudflare 人机验证需要真浏览器跑一遍）→ 起服务 → 弹浏览器。首次约 1-3 分钟，之后每次启动几秒就好——依赖没变就跳过重装。

不用装 Node，Web 界面的构建产物已经在仓库里。

第一次打开浏览器会看到配置向导：**填 Z-Library 的邮箱和密码，点「连接并开始使用」**。登录凭证（remix token）和 Cloudflare cookies 都是后台自动拿的，你不需要打开开发者工具翻 cookies。国内用户如果开着代理，向导会自动检测端口并预填。

至此可以开始下书。下面的内容按需再看。

## 日常使用

服务起来后界面上有四块：

- **环境状态条**——依赖 / 浏览器 / 配置 / 账号 / 代理 / 配额一目了然，另有「刷新 Cookies」兜底按钮
- **任务入口**——填参数一键跑，实时看日志
- **账号设置**——改邮箱密码、代理、域名，可测连接看实时剩余配额
- **版本优先级**——同一本书有多个版本时按什么规则挑

**cookies 过期不用你管。** 每次跑任务前会自动自检，过期就自动刷新，日志里会打出来：

```
[自检] Cookies 已过期（更新于 48.0 小时前），正在自动刷新（约 10-30 秒）…
cookies 已刷新：5 个 → zlibrary_cookies.json
[自检] 已自动修复: cookies
```

跑到一半撞上 Cloudflare 也会自动刷新并重试一次，不需要你去终端敲命令。

想单独体检一次环境：

```powershell
.venv\Scripts\python doctor.py --fix
```

### 三种下载入口

**喂书名**——把书名文本复制到剪贴板，用「整理 / 补全本地书库」入口。书名可用《》包裹，也可每行一个或用顿号/逗号/分号分隔，工具自动识别。剪贴板模式只搜本地；勾「本地缺失的从 Z-Library 补下」才消耗配额补下（仅目录模式生效）。

**喂 ISBN**——用「按 ISBN 批量下载」入口，粘贴 ISBN（一行一个，10 或 13 位，带不带连字符都行），逐个搜索下载。

**喂链接**——把 Z-Library 书单页的 URL 复制到剪贴板，跑命令行 `download_from_zlibrary_booklist.py`，解析页面书目逐本下载。

**版本优先级**：搜索类下载（书名 / ISBN）搜到多个版本时，按「格式 → 语言 → 年份 → 体积 → 评分」自动选最优，默认格式优先（epub>pdf>mobi>azw3）不管语言。在设置页的版本优先级面板可调，存 `preferences.json`。书单页面下载不走搜索，不受此影响。

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

**1. 装环境**——`python bootstrap.py --check`（等价于启动器但不起服务）。之后所有 Python 调用**必须用** `.venv\Scripts\python`，系统 `python` 没装依赖会报错。

**2. 填配置**——两条路：写 `.env`（`ZLIBRARY_REMIX_USERID` / `ZLIBRARY_REMIX_USERKEY` / `ZLIBRARY_PROXY`），或调 `POST /api/setup` 传邮箱密码让后端自动换 token。

**3. 自检**—— `.venv\Scripts\python doctor.py --fix`。cookies 过期会自动刷新，**不需要**再手动跑 `refresh_zlibrary_cookies.py`。

**4. 验证**—— `.venv\Scripts\python -m unittest discover -s tests`，或启动 Web 服务后 `POST /api/settings/test-auth` 确认登录和剩余配额。

**5. Web 服务**—— `.venv\Scripts\python web_server.py` 起在 `127.0.0.1:8000`。脚本执行走 WebSocket `/api/ws/run/{script_id}`（跑之前会自动 preflight 自愈），`GET /api/scripts` 拿脚本列表和参数定义。

其它端点：`GET /api/doctor?fix=true` 自检+自愈、`GET /api/cookies/status`、`POST /api/cookies/refresh`、`POST /api/setup` 首次配置、`GET /api/proxy/detect` 探测本机代理、`GET/POST /api/preferences` 版本优先级。

**别动这些**：
- `.env`、`zlibrary_cookies.json`、`_file_index.sqlite3` 是本机文件，已 gitignore，别提交
- `Zlibrary.py` 的公开接口（`search()`、`downloadBook()` 等）下游依赖，别改签名
- Web 服务仅限本机访问，没有鉴权，不要对外暴露

## 注意事项

**域名**：`z-lib.id` 是钓鱼站，别用。`ZLIBRARY_DOMAIN` 留空会自动按 `z-lib.by → z-library.gy → zh.zlib.li → zh.z-lib.rest` 顺序试。

**配额**：普通账号每天 10 本。Web 界面的「测试连接」显示的剩余数是实时查 API 得到的真实值。配额用完工具会自动停，进度存着，第二天接着跑。

**额度不够怎么办**：官方给了一条合法的加倍路子——[Z-Library 的 Telegram bot](https://z-lib.by/faq) 有**独立于网站的**每日额度。按官方 FAQ 原文，网站 10 本用完后还能通过 bot 再下 10 本，一天总共 20 本。同一个账号，不违反条款。想要更高上限就捐赠升 Premium。

⚠️ **不要用多账号轮换来凑额度**。Z-Library [服务条款第 15 节 MULTI-ACCOUNT POLICY](https://z-lib.by/tos) 明确规定一人一号、禁止用不同邮箱注册多个账号，违反的后果写的是 **account suspension or termination**（封号）。第 7 节还单独点名禁止绕过额度限制（circumvent... features that enforce limitations on the use of the Services）。同一 IP、同一批 cookies 上交替出现多个账号是最容易被关联识别的模式，真做了很可能几个号一起封。本工具因此**不提供**多账号功能，这是有意的设计决定。

**请求节流**：两条下载路径（书名 / ISBN）每本之间都留 2 秒间隔，常量是 `download_ebooks_from_zlibrary.py` 里的 `DOWNLOAD_INTERVAL_SECONDS`。每本书至少要打 3 个请求（搜索 + 查配额 + 下载），无间隔连打是最扎眼的模式。想调慢些可以改大，不建议改小。

**代理**：国内直连官方域名不通。`.env` 里 `ZLIBRARY_PROXY` 填你本地代理端口，`http://` 或 `socks5://` 都行。

**Cloudflare**：所有官方域名都有浏览器验证，`requests` 直接访问返回 503。工具用 Playwright 真浏览器过验证并复用 cookies——这一步**全自动**：跑任务前自检会刷过期 cookies，中途撞墙也会自动刷新重试一次。默认超过 12 小时视为过期（可用环境变量 `ZLIBRARY_COOKIES_MAX_AGE_HOURS` 调）。想手动刷就点界面上的「刷新 Cookies」，或跑 `.venv\Scripts\python refresh_zlibrary_cookies.py`。

**首次索引**：第一次跑本地搜索会全盘扫描建 SQLite 索引，书多的话要等几分钟。之后增量更新，快很多。

**书名格式**：书名可用《》包裹（最稳），也可每行一个或用顿号/逗号/分号分隔。有《》时只取书名号内内容，避免误拆正文。

## 全部脚本

| 脚本 | 干什么 |
| --- | --- |
| `collect_ebooks_with_booklists.py` | 先搜本地，缺的从 Z-Library 补下 |
| `download_ebooks_from_zlibrary.py` | 读「处理结果」里未找到的书，去 Z-Library 下 |
| `download_from_zlibrary_booklist.py` | 解析 Z-Library 书单页面，批量下载 |
| `start.cmd` / `start.ps1` / `start.sh` | 一键启动器：装环境 + 起服务，双击即可 |
| `bootstrap.py` | 启动器的实际逻辑（探测 Python / 建 venv / 装依赖 / 装浏览器） |
| `doctor.py` | 环境自检与自愈，`--fix` 会自动修好能修的 |
| `cookie_manager.py` | Cookies 生命周期：查状态 / 自动刷新 / 邮箱密码换 token |
| `refresh_zlibrary_cookies.py` | 手动刷 cookies 的命令行入口（平时不需要） |
| `collect_local_ebooks.py` | 在本地书库里按书名搜索、复制、归档 |
| `find_duplicated_files.py` | 找重复文件，导出 Markdown 报告 |
| `remove_duplicates_on_report.py` | 按报告删重复（丢回收站，不直接删） |
| `clean_booknames.py` | 清理文件名里的 `(Z-Library)`、编号尾缀 |
| `rename_epub_with_catalog.py` | 给 EPUB 合集文件名补上一级目录信息 |
| `pull_md_images_to_local.py` | 把 Markdown 里的远程图片下到本地 |
| `web_server.py` | 启动 Web 控制台 |

## 测试

```powershell
.venv\Scripts\python -m unittest discover -s tests
```

## 来源

在 [famotime/ebook_toolbox](https://github.com/famotime/ebook_toolbox) 基础上改的。加了 Web 控制台、Cloudflare 绕过、真实配额查询、中文文件名乱码修复等。

仅供个人合法用途。请遵守当地版权法和 Z-Library 使用条款。
