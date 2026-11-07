# 政务新闻聚合平台（广东 · 一期 1.5）

覆盖广东省级 + **21 个地市政府官网（27 个源，全省地市全覆盖）**，自动抓取政务要闻、三层去重、AI 解读，提供新闻流、政策走向趋势分析、管理后台，以及每轮自动生成的执行报告与飞书推送。

当前为本地单机部署，服务由 launchd 常驻托管，每日 **12:00 / 21:00** 两轮全自动运行。

| 维度 | 现状 |
|---|---|
| 覆盖 | 27 源 / 21 地市（含梅州，WAF JS 挑战已破解） |
| 库存 | 稳态日增约 20–50 篇（按发布日期统计），新文章当轮自动解读、常态待解读为 0 |
| 自动化 | 抓取 → 解读 → 热备 → 执行报告 → 飞书推送，全程无人值守 |
| 运行环境 | 项目自带 Python 3.13 解释器与依赖，不依赖系统 Python 或 WorkBuddy |
| 版本控制 | GitHub `jt1024/news-wb`，密钥与运行数据由 `.gitignore` 排除 |

## 快速开始

### 本机已部署（日常使用）

服务由 `~/Library/LaunchAgents/com.jt.gov-news.plist` 托管，开机自启、崩溃约 10 秒内自动拉起，**无需手动启动**。

```bash
curl http://127.0.0.1:8300/                 # 探活
launchctl kickstart -k "gui/$(id -u)/com.jt.gov-news"   # 平滑重启
tail -f news-app/data/launchd.err.log      # 看运行日志
```

首次注册（新机器或卸载过）：在访达里**双击** `news-app/scripts/run_launchd_install.command`，脚本会在 Aqua GUI 会话中安装 plist 并交接进程。注意脚本内含开发机绝对路径，换机器需同步修改。

### 从零部署

```bash
cd news-app
runtime/python313/bin/python3 -m venv .venv   # 用项目自带解释器，或系统 python3 -m venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env                          # 必填：ADMIN_PASSWORD、AUTH_SECRET、AI_API_KEY、NOTIFY_*
chmod 600 .env
.venv/bin/python scripts/run_tests.py         # 45 个单测，0.1 秒
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8300
```

`runtime/python313/` 是项目自带的 CPython 3.13 完整副本，`.venv/` 基于它创建，因此卸载或升级 WorkBuddy、系统 Python 都不影响服务。这两目录不进 GitHub，换机器按上面命令重建即可。

### 页面入口

| 地址 | 用途 |
|---|---|
| http://127.0.0.1:8300/ | 新闻流：按地域/类型/时间筛选、搜索、详情页与单篇手动解读 |
| http://127.0.0.1:8300/trends.html | 政策走向分析：日走势、地市分布、主题热度、上升话题（ECharts） |
| http://127.0.0.1:8300/admin | 管理后台：手动触发抓取/解读、实时进度、源管理、复核队列、执行报告列表 |
| http://127.0.0.1:8300/reports/ | 历史执行报告（独立 HTML，手机访问需另做公网发布） |

登录用 `.env` 的 `ADMIN_PASSWORD`。登录态是无状态 HMAC 令牌，由**独立的** `AUTH_SECRET` 签发，服务重启不掉登录；更换 `AUTH_SECRET` 会使所有已登录会话失效。

## 配置项（.env）

| 项 | 说明 |
|---|---|
| ADMIN_PASSWORD | 后台登录口令 |
| AUTH_SECRET | token HMAC 签名密钥，务必用 `python3 -c "import secrets; print(secrets.token_urlsafe(40))"` 生成；留空则回退用口令（不推荐） |
| AUTH_TOKEN_EXPIRE_HOURS | 登录有效期小时数，当前 72 |
| AI_PROVIDER | deepseek / minimax / qwen（留空则跳过 AI 解读，新闻照常入库） |
| AI_API_KEY | OpenAI 兼容接口的 Key |
| AI_MODEL / AI_MODEL_STRONG | 常规解读模型 / 政策类精读强模型（推理模型的 `<think>` 块会自动剥离） |
| AI_FALLBACK_PROVIDER / AI_FALLBACK_API_KEY / AI_FALLBACK_MODEL | 主通道 402 时自动切换的备用模型，留空则不启用 |
| INTERPRET_BATCH_SIZE / INTERPRET_RETRIES | 每批解读条数（后台可临时覆盖）/ 单篇失败重试次数 |
| DATABASE_URL | 默认 SQLite（`data/news.db`），上云可换 `postgresql://` |
| CRON_HOURS / CRON_MINUTE | 每天触发的小时列表，当前 `12,21` / `0`；旧 `CRON_HOUR` 仍兼容 |
| FETCH_CONCURRENCY / FETCH_DELAY_SECONDS | 源内详情抓取并发与礼貌间隔 |
| TITLE_SIMILARITY_THRESHOLD / SIMHASH_DISTANCE_THRESHOLD | 去重第二、三层的阈值 |
| NOTIFY_CHANNEL | `feishu` / `wecom` / `serverchan` / `pushplus` / `custom` / `off`，当前 feishu |
| NOTIFY_WEBHOOK | feishu / wecom / custom 的机器人地址；custom 收到 `{title, text, markdown, report_html, report_md, round}` JSON |
| NOTIFY_TOKEN | serverchan（Server酱 Turbo）/ pushplus 的 token |
| NOTIFY_SECRET | 飞书机器人开启签名校验时填写，留空表示未开启 |
| BACKUP_KEEP_DAYS / BACKUP_MIRROR_DIR | 热备保留天数（14）/ 可选异地镜像绝对路径（iCloud、移动硬盘） |

`.env` 权限应为 `600`。服务启动会自检：未配 `AUTH_SECRET` 或口令过弱时写一条 WARNING 日志（不阻断启动）。

## 架构与数据流水线

```
抓取（httpx 异步 + curl 兜底；html / rss / json；创宇盾 WAF 挑战由 quickjs 求解）
  → 列表清洗（同站过滤 / 标题去标签去实体 / 栏目页排除）
  → 正文清洗（17+ 类版式噪音 + 前导元数据剥离）
  → 三层去重（URL 归一化哈希前置 / 标题指纹+difflib 同地域 / SimHash64 同源 60 天）
  → SQLite（无正文或失效链接登记 30 天豁免，避免每轮重复下载）
  → AI 解读（批处理、重试、置信度分级复核、模型分级、402 兜底）
  → JSON API + Web 前端（新闻流 / 趋势分析 / 管理后台）
  → 每轮收尾：数据库热备 → 执行报告 HTML+MD → 飞书推送
```

关键机制：

- **三层去重**：URL 判重提前到下载详情页之前，列表里大部分历史文章无需重复下载；同地域标题指纹、同源标题相似度与正文 SimHash 兜底跨 URL 的转载重复。
- **WAF 通行**：梅州站返回 521 + 混淆 JS 挑战，`app/crawler/waf.py` 用 quickjs 在 Python 内执行挑战脚本算出 `https_ydclearance` cookie，按域名缓存复用、过期自动重解；curl 兜底链路同样携带。其他站点挂同款 WAF 可直接复用。
- **列表噪音治理**：只保留与源站同主机/子域的详情链接（历史入库文章全部与源站同主机，过滤安全），并排除栏目首页；标题统一剥 HTML 标签与实体。
- **无正文豁免**：纯图片海报页、视频页、404 失效链接不入库，但登记到 `skipped_urls` 表抑制 30 天，避免每轮重复下载又重复报一条异常；到期自动重试。
- **定时**：APScheduler 单 cron 任务多时刻触发，`misfire_grace_time=3600, coalesce=True`（1 小时内可补跑，多次错过只补一次）。手动触发走后台按钮（异步任务 + 实时进度）。
- **源管理**：`app/crawler/sources.py` 种子 + 后台「新增源」表单，加源通常无需改代码。
- **站点特例**：深圳站 TLS 国密握手失败时自动回退 curl；珠海列表为 JS 渲染，改走 `postmeta` JSON 接口。

## 执行报告

每轮定时任务（12:00 / 21:00）在抓取、解读、热备全部完成后，自动生成一份执行报告并推送：

- 产出 `data/reports/YYYY-MM-DD_HHMM.html`（独立可分发，内嵌样式）与同名 `.md`（纯文本摘要）
- 六段结构：总览 KPI、本轮新增、异常与处置、源级明细、近 6 轮趋势、库状态与下次执行
- 报告里每条异常都写明影响与「下轮自动重试，无需处理」，避免看到备注误以为系统故障
- 待解读 > 0 / AI 错误 / 源级失败时，报告标题加「【注意】」、飞书卡片转红
- 网页入口：后台「执行报告」卡片列出历史报告，可点开或「立即生成并推送」
- 推送由 `app/notifier.py` 直连 webhook，不依赖 AI 会话；**推送失败只记日志，不影响抓取结果**
- 手动命令：`.venv/bin/python scripts/execution_report.py --notify`（补历史用 `--all`，指定轮次用 `--run "2026-11-07 12:00"`）
- 报告静态文件挂在 `/reports/`，服务仅监听 127.0.0.1，手机上看完整报告需另接活页或发布上线

## 数据库备份与额度兜底

**热备**：每轮定时任务生成当天快照 `data/backups/news-YYYYMMDD.db`，同一天覆盖为最新。先写临时文件、校验 `news` 表行数后原子替换；使用 SQLite 官方 `backup()` API（WAL 模式下直接复制文件会漏数据）。默认保留 14 天。

- 手动执行：`.venv/bin/python scripts/backup_db.py`
- 恢复：停服务 → 把快照复制回 `data/news.db` → 重启
- 异地镜像：设 `BACKUP_MIRROR_DIR=/绝对路径`，目录不存在会静默跳过，不影响主流程
- 备份目录已被 `.gitignore` 排除；**GitHub 只存代码，不能替代数据备份**

**AI 额度兜底**：主通道返回 402（额度耗尽）时——

1. 配了备用通道 → 自动切换继续解读，实际模型名写入 `news.ai_model`；
2. 未配置 → 立即中止本轮解读并推送一条红色告警；新闻仍正常入库（保持 `fetched`，不会丢）；
3. 两种情况都照常生成并推送执行报告，说明额度恢复后下一轮自动补解读。

解读、备份、报告三段在定时任务里各自异常隔离，任何一段失败都不会阻断后续步骤。

## 政策走向分析

`GET /api/trends?days=7|30|90` 与 `web/trends.html`：每日新增走势、地市分布、内容类型分布、主题热度 Top（带时间序列）、上升话题（环比增量在 Python 侧计算，避免 SQLite 别名排序坑）。前端用 ECharts，双 CDN 兜底，复用 `web/ui.css` 的政务红设计令牌。

## 测试

```bash
.venv/bin/python scripts/run_tests.py
# 或：.venv/bin/python -m unittest discover -s tests -t . -v
```

标准库 `unittest`，45 个用例、约 0.1 秒，覆盖标题清洗、同站过滤、列表解析、三层去重（真实 SQL）、报告轮次聚合、cron 解析、飞书签名与推送降级、认证密钥隔离、无正文豁免生命周期。

`tests/__init__.py` 会把 `DATABASE_URL` 强制指向临时库，**单测绝不连接或修改生产库**。

## 维护脚本

| 命令 | 用途 |
|---|---|
| `scripts/run_tests.py` | 一键跑全部单测 |
| `scripts/backup_db.py` | 手动做一次数据库热备 |
| `scripts/execution_report.py --notify` | 生成最近一轮报告并推送 |
| `scripts/interpret_backlog.py 10 2` | 消化待解读积压（批大小、间隔秒） |
| `scripts/discover_sources.py` | 自动探测地市站点列表页 |
| `scripts/audit_sources.py` | 全源体检：存量噪音扫描 + 逐源实时重抓验证 |
| `scripts/crawl_meizhou_once.py` | 一次性补跑梅州两个源（开发期遗留） |
| `scripts/install_launchd.sh` | 注册 launchd 服务（配合双击 `run_launchd_install.command`） |

每次新增源或调整选择器后建议跑一次全源体检；每日两轮的 27 源状态可在执行报告里查看。

## 部署到云服务器

1. 代码同步到服务器，按「从零部署」重建 `.venv` 并装依赖
2. **必须先改**：强口令、独立 `AUTH_SECRET`、`.env` 权限 600；服务当前默认只监听 127.0.0.1
3. `DATABASE_URL` 换 PostgreSQL（需 `pip install psycopg2-binary`）
4. systemd 托管 uvicorn 常驻（APScheduler 随进程启动）
5. nginx 反代 + 域名 + HTTPS，并配置报告目录的鉴权
6. 设 `BACKUP_MIRROR_DIR` 做异地备份

## 已知事项与边界

- **定位是「精要闻」**：27 源只收各市政务要闻栏目，去重后稳态日增数十篇，SQLite 完全够用；需求文档里「日均数千条」的设想对应「全量政务信息」定位，需另扩区县/部门/公示公告类源，届时再评估 PostgreSQL 与 worker 拆分。
- 飞书里是**摘要**，完整 HTML 报告存本机 `data/reports/`，手机点不开；需要移动端看全文可接活页发链接或发布上线。
- 未配置 AI Key 时新闻照常抓取入库（`status=fetched`），补 Key 后点「立即 AI 解读」或等下一轮自动补。
- `.env`、`.workbuddy/`、`data/`、`.venv*`、`runtime/` 均被 `.gitignore` 排除；`scripts/` 下少数脚本含开发机绝对路径，换机器需改。
- 需求与技术方案见 `docs/需求文档-v1.md`、`docs/技术方案-v1.md`（分期路线以实际实现为准）。
