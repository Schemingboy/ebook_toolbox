# 项目结构

## 概览

`zlibrary-batch-download` 当前按“启动/自检层 + 入口脚本 + 共享工作流模块 + 测试”组织，主线能力集中在本地书单整理、Z-Library 下载、重复文件查找和若干独立小工具。

用户侧只接触启动器：双击 `start.cmd` 后由 `bootstrap.py` 备好环境、`doctor.py` 自检并自愈、`cookie_manager.py` 保证 Cloudflare cookies 有效，再拉起 Web 控制台。下面三层是这条链路的内部分工。

## 启动与自检层

| 文件 | 作用 |
| --- | --- |
| `start.cmd` / `start.ps1` / `start.sh` | 一键启动器薄壳（纯 ASCII，避免 PowerShell 5.1 读 UTF-8 中文乱码），只负责找 Python 并转交 `bootstrap.py` |
| `bootstrap.py` | 启动实际逻辑：校验 Python 版本、建 `.venv`、按 `requirements.txt` 指纹增量装依赖、装 Playwright Chromium、必要时构建前端、拉起服务 |
| `doctor.py` | 环境自检与自愈：依赖/浏览器/`.env`/凭据/代理/cookies/配额七项；`--fix` 自动修可修项，`preflight()` 供跑任务前调用 |
| `cookie_manager.py` | Cookies 生命周期：状态查询、自动刷新（headless 失败退回有头）、`/eapi/user/profile` 真实探针校验、邮箱密码换 remix token、写 `.env` |

## 入口脚本

| 文件 | 作用 |
| --- | --- |
| `collect_local_ebooks.py` | 本地书单整理主入口，支持批量书单与剪贴板监控 |
| `collect_ebooks_with_booklists.py` | 组合入口，先搜本地再补 Z-Library 下载 |
| `download_ebooks_from_zlibrary.py` | 针对 `处理结果.txt` 中未找到图书的批量下载入口；含按书名与按 ISBN 两种下载路径 |
| `download_from_zlibrary_booklist.py` | 解析 Z-Library 书单页面并批量下载 |
| `find_duplicated_files.py` | 重复文件索引、查找与 Markdown 报告导出入口 |
| `remove_duplicates_on_report.py` | 根据重复文件 Markdown 报告把选中项移入回收站 |
| `clean_booknames.py` | 清理电子书文件名中的 Z-Library/数字尾缀等冗余信息 |
| `pull_md_images_to_local.py` | 下载 Markdown 中的远程图片并改写为本地路径 |
| `rename_epub_with_catalog.py` | 为 EPUB 合集文件名补充目录信息 |
| `web_server.py` | Web UI 启动入口（uvicorn + FastAPI） |
| `web_api.py` | FastAPI 路由：设置读写、脚本列表、偏好读写（`/api/preferences`）、WebSocket 执行流、凭据测试 |
| `refresh_zlibrary_cookies.py` | Playwright 浏览器导出 Cloudflare cookies（绕过验证） |

## 共享模块

| 文件 | 作用 |
| --- | --- |
| `env_config.py` | 读取项目根目录 `.env` 中的 Z-Library 配置（含 `domain`/`proxy`/`fallback_domains`） |
| `library_index.py` | 统一 SQLite 文件索引、书名标准化、内容 quick/full hash 计算与查询 |
| `zlibrary_runtime.py` | 统一 Z-Library 认证加载、客户端创建、待处理结果文件发现 |
| `zlibrary_booklist_workflow.py` | 书单 HTML 解析、标准化本地索引命中判断、下载目标路径拼装 |
| `local_ebooks_workflow.py` | 本地书单输出目录决策、已复制条目解析、批量跳过分类 |
| `duplicate_finder_workflow.py` | 重复文件保留规则、Markdown 报告渲染与解析 |
| `book_ranking.py` | 版本优先级引擎：按格式→语言→年份→体积→评分对搜索结果排序选最优（`pick_best`）；偏好读写 `preferences.json` |
| `isbn_utils.py` | ISBN-10/13 识别（含校验位）、规整、多行批量提取 |
| `cookie_manager.py` | Cookies 生命周期：`cookies_status` 查健康度（纯本地）、`refresh_cookies` 真浏览器过 Cloudflare 并用 `/eapi/user/profile` 探针验证、`ensure_fresh_cookies` 过期才刷、`login_and_capture_token` 邮箱密码换 remix token、`setup_from_credentials` 向导后端 |
| `Zlibrary.py` | 同步客户端：以 HTML 页面抓取为主，多域名自动探测、RPC/表单登录、SOCKS5 代理；用户资料与下载配额走 `/eapi/user/profile` JSON 接口（`downloads_today`/`downloads_limit`），配额每次实时刷新不缓存 |
| `zlibrary_adapter.py` | 基于 `zlibrary` PyPI 包的同步适配器，支持代理链和 Tor/Onion 路由 |

## 测试

| 文件 | 覆盖范围 |
| --- | --- |
| `tests/test_env_config.py` | `.env` 账号字段读取 |
| `tests/test_local_ebooks_workflow.py` | 本地书单解析、输出目录决策、SQLite 索引搜索、同内容文件跳过 |
| `tests/test_zlibrary_booklist_workflow.py` | Z-Library 书单 HTML 解析、标准化本地索引匹配、已下载跳过 |
| `tests/test_zlibrary_runtime.py` | 共享认证加载、客户端创建、待处理结果文件筛选 |
| `tests/test_duplicate_finder_workflow.py` | 重复文件选择策略、报告渲染与改名同内容文件识别 |
| `tests/test_small_tool_entrypoints.py` | 小工具 CLI 入口参数与默认路径解析 |
| `tests/test_web_api.py` | Web API 路径校验 |
| `tests/test_book_ranking.py` | 版本优先级排序、偏好读写、体积/年份/评分解析 |
| `tests/test_isbn_utils.py` | ISBN-10/13 校验、规整、多行提取 |
| `tests/test_cookie_manager.py` | Cookies 状态判定（缺失/无登录态/超龄）、`ensure_fresh_cookies` 该刷才刷、`write_env` 保留既有行 |
| `tests/test_doctor.py` | 各项检查的等级判定、过期 cookies 自动修复、代理端口探测、报告 `needs_setup` 语义 |

## 非核心目录

| 路径 | 说明 |
| --- | --- |
| `assets/` | README 配图资源 |
| `library/` | 默认本地电子书库（只搜不改），首次运行自动创建 |
| `output/` | 下载与整理产物、重复文件报告、索引输出 |
| `frontend/` | React 前端源码；`frontend/dist` 是构建产物且**必须入库**（缺了 Web 界面是空白页） |
| `docs/archive/` | 已完成计划的归档，不反映当前结构 |

## 当前建议

1. 继续把索引、哈希、标准化等横切逻辑收敛到 `library_index.py`，避免入口脚本再各自维护一套规则。
2. 新增行为优先补到 `tests/`，再改对应入口脚本。
3. 把 `output/` 视为运行产物目录，不要当成核心模块的一部分。
4. 环境相关的判断（依赖、浏览器、凭据、代理、cookies、配额）统一进 `doctor.py`，不要在各入口脚本里各写一套前置检查。
