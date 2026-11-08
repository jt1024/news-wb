# 政务新闻聚合平台（广东 + 国家部委 · 一期 2.0）

覆盖 **国家部委 / 国务院机构 27 家（28 个源，其中海关总署 1 源默认禁用）** + 广东省级与 **21 个地市政府官网（27 个源，全省地市全覆盖）** + **广州市 11 个区政府官网（11 个源）**，共 66 个源配置 / 65 个启用；自动抓取政务要闻、三层去重、AI 解读，提供新闻流、政策走向趋势分析、管理后台，以及每轮自动生成的执行报告与飞书推送。

当前为本地单机部署，服务由 launchd 常驻托管，每日 **12:00 / 21:00** 两轮全自动运行。

| 维度 | 现状 |
|---|---|
| 覆盖 | 66 源配置（65 启用）/ 27 家国家部委机构 + 21 地市 + 广州 11 区；梅州 521、部委 412 / EO 挑战均已破解 |
| 库存 | 去重后稳态日增数十至上百篇（按发布日期统计），新文章当轮自动解读、常态待解读为 0 |
| 自动化 | 抓取 → 解读 → 热备 → 执行报告 → 飞书推送（含手机可看的完整报告链接），全程无人值守 |
| 周期性 | 每天 09:00 独立存活心跳；周一推上周周报、每月 1 日推上月月报（含 AI 综述） |
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
.venv/bin/python scripts/run_tests.py         # 100 个单测，0.2 秒
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8300
```

`runtime/python313/` 是项目自带的 CPython 3.13 完整副本，`.venv/` 基于它创建，因此卸载或升级 WorkBuddy、系统 Python 都不影响服务。这两目录不进 GitHub，换机器按上面命令重建即可。

### 页面入口

| 地址 | 用途 |
|---|---|
| http://127.0.0.1:8300/ | 新闻流：按层级/部委/地市/区县/类型/时间筛选、搜索、详情页与单篇手动解读 |
| http://127.0.0.1:8300/trends.html | 政策走向分析：日走势、地市分布、主题热度、上升话题、政策信号串联、同主题地市热力图（ECharts） |
| http://127.0.0.1:8300/admin | 管理后台：手动触发抓取/解读、实时进度、源管理、复核队列、执行报告与周/月报列表 |
| http://127.0.0.1:8300/reports/ | 历史执行报告、周报、月报；`latest.html` 恒为最新一轮（在线固定链接同步它） |

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
| REPORT_PUBLIC_URL | 在线完整报告的固定链接（活页发布后填入）；飞书卡片据此生成「查看完整报告」按钮 |
| LIVEPAGE_PROPOSAL_ID | 该链接对应的活页方案 ID，供定时自动化每轮发新版本；留空则只生成本机 `latest.html` |
| BACKUP_KEEP_DAYS / BACKUP_MIRROR_DIR | 热备保留天数（14）/ 可选异地镜像绝对路径（iCloud、移动硬盘） |

`.env` 权限应为 `600`。服务启动会自检：未配 `AUTH_SECRET` 或口令过弱时写一条 WARNING 日志（不阻断启动）。

## 架构与数据流水线

```
抓取（httpx 异步 + curl 兜底；html / rss / json；创宇盾 WAF 挑战由 quickjs 求解）
  → 列表清洗（同站过滤 / 标题去标签去实体 / 栏目页排除 / .htm 与 JSON 列表兼容）
  → 正文清洗（17+ 类版式噪音 + 前导元数据剥离；URL 与 meta 双重日期兜底）
  → 三层去重（URL 归一化哈希前置 / 标题指纹+difflib 同层级同地域 / SimHash64 同源 60 天）
  → SQLite（无正文或失效链接登记 30 天豁免，避免每轮重复下载）
  → AI 解读（批处理、重试、置信度分级复核、模型分级、402 兜底）
  → JSON API + Web 前端（新闻流 / 趋势分析 / 管理后台）
  → 每轮收尾：数据库热备 → 执行报告 HTML+MD → 覆盖 latest.html → 飞书推送（带在线报告按钮）
每日 09:00（独立进程）：存活自检 → 飞书心跳；周一/月初顺带生成并推送周报 / 月报
每轮 +10 分钟（平台自动化）：把 latest.html 发成活页新版本，固定链接内容自动更新
```

关键机制：

- **三层去重**：URL 判重提前到下载详情页之前，列表里大部分历史文章无需重复下载；同地域标题指纹、同源标题相似度与正文 SimHash 兜底跨 URL 的转载重复。标题指纹的范围是 `(层级, 地市, 区县)`：广州各区转发同一篇通稿不会互相误杀；所有国家级源共享同一命名空间，十几个部委同时转载的中央通稿只保留最先抓到的一条。
- **WAF 通行**：梅州站返回 521 + 混淆 JS 挑战，`app/crawler/waf.py` 用 quickjs 在 Python 内执行挑战脚本算出 `https_ydclearance` cookie，按域名缓存复用、过期自动重解；curl 兜底链路同样携带。其他站点挂同款 WAF 可直接复用。
- **列表噪音治理**：只保留与源站同主机/子域的详情链接，并排除栏目首页；标题统一剥 HTML 标签、实体和尾部日期。所有政务站都在 `.gov.cn` 下，因此同站判定显式拦住 `gov.cn` 这类公共后缀——否则 `samr.gov.cn` 会把中国政府网的通稿当成本部新闻抓进来。人民银行的 `/<14位时间戳>/index.html` 是文章而非栏目首页，按长数字 ID 放行。
- **无正文豁免**：纯图片海报页、视频页、404 失效链接不入库，但登记到 `skipped_urls` 表抑制 30 天，避免每轮重复下载又重复报一条异常；到期自动重试。
- **模型拒答终态化**：AI 返回 422 等确定性 4xx（多为内容审核拒答）时，重试无意义，直接把该篇 `status` 置为 `failed` 并保留原文与错误原因，`run_interpret` 不再反复捞取；执行报告的「待解读」只统计 `fetched`，不会每轮误报积压。需重试时把 `status` 改回 `fetched` 即可。
- **定时**：APScheduler 单 cron 任务多时刻触发，`misfire_grace_time=3600, coalesce=True`（1 小时内可补跑，多次错过只补一次）。手动触发走后台按钮（异步任务 + 实时进度）。
- **源管理**：`app/crawler/sources.py` 种子 + 后台「新增源」表单，加源通常无需改代码。
- **站点特例**：深圳站 TLS 国密握手失败时自动回退 curl；珠海列表为 JS 渲染，改走 `postmeta` JSON 接口；中国政府网要闻列表是 ajax 空壳，改读 400 条的静态 `YAOWENLIEBIAO.json`；工信部/住建部/能源局/医保局的栏目页是 CMS/Vue 空壳，用首页静态文章链接。

## 广州各区新闻（区级维度）

2026-11-08 接入，每个区一个主新闻栏目，共 11 个源，随 12:00 / 21:00 两轮一起抓取：

越秀（越秀快讯）、海珠（海珠要闻）、荔湾（政务要闻）、天河（天河要闻）、白云（政务要闻）、黄埔（政务要闻）、花都（花都新闻）、番禺（番禺新闻）、南沙（南沙要闻）、从化（从化要闻）、增城（增城要闻）。

| 设计点 | 做法 |
|---|---|
| 数据归属 | `sources` / `news` 新增 `region_district`，区级源 `region_city=广州市`、`level=district`；周/月报副标题的源规模从库里现查，不再写死数字 |
| 旧库升级 | `app/main.py::_migrate()` 启动时给两张表 `ALTER TABLE ADD COLUMN`（`create_all` 只建新表、不改旧表），历史文章该字段为空，判重行为不变 |
| 判重 | 标题指纹的地域范围从「同地市」收窄为「同地市 + 同区县」，避免各区转发同一篇市/中央通稿时互相误杀 |
| 前台 | 新闻流新增「全部区县」下拉，选非广州市时自动禁用；列表卡片与详情页显示区名；`/api/news?district=`、`/api/meta.districts` 可直连 |
| 后台 | 源列表新增「区县」列，「新增源站点」表单可填区县 |

逐站踩过的坑（都已沉淀成通用能力）：番禺新闻挂在「政府信息公开目录」静态路径下、首页 `#7523` 是 JS 渲染列表；增城列表 `href` 带前导空格（已在 `_parse_list` 统一 strip）；越秀 `.conNews`、南沙 `#zoomcon`、增城 `.detailCon` 不在通用兜底里，需显式配 `content`；白云的发布日期在标题容器的父级（改为逐层向上找，遇到整块含多条新闻链接即停，防止日期错配）；南沙纯附件页会被页脚判空逻辑正确抑制 30 天。

如需继续扩到各区「部门动态 / 街镇信息」，在 `app/crawler/sources.py` 按同样格式追加源并填好 `region_district` 即可，无需改模型或前端；注意源数与 AI 解读配额、每轮耗时成正比，建议分批加并跑一次全源体检。

## 国家部委新闻（国家级维度）

2026-11-08 接入首批 22 家机构 / 23 个源，11-09 二次攻坚再补 5 家 / 5 源，合计 27 家机构 / 28 个源（海关总署默认禁用），随 12:00 / 21:00 两轮一起抓取：

中国政府网（要闻 + 国务院政策 2 源）、国家发展改革委、工业和信息化部、财政部、教育部、科学技术部、民政部、自然资源部、生态环境部、住房城乡建设部、交通运输部、农业农村部、商务部、应急管理部、中国人民银行、国家税务总局、市场监管总局、中国证监会、国家统计局、国家能源局、国家医保局、国家数据局；二次攻坚补入国家卫生健康委、国家药监局、人力资源社会保障部、金融监管总局、海关总署（默认禁用）。

| 设计点 | 做法 |
|---|---|
| 数据归属 | `sources` / `news` 新增 `region_org`，国家级源 `level=national`、`region_province=全国`、地市/区县留空；旧库启动自动 `ALTER TABLE` 加列 |
| 判重 | 标题指纹加 `level` 维度：与同样 `region_city` 为空的广东省级源隔开；国家级各机构共享一个命名空间，中央通稿跨部委只留一条，省下大量 AI 额度 |
| 日期 | 部委列表页普遍不显示日期，改为「URL 里的发布日期 → 详情页 `meta[PubDate]` → 带发布时间标签的行」三级兜底；临时库实测 169 篇 100% 带日期 |
| 前台 | 新闻流新增「全部层级」与「全部部委」两个下拉，选定部委自动切到国家部委层级；卡片与详情页显示机构名，不再错标「广东省」 |
| 后台 | 源列表新增「部委/机构」列，新增源表单可选 `国家部委` 层级并填机构名 |
| 周/月报 | 副标题的源规模从库里现查并追加「N 部委」；正文新增国家部委新闻篇数，代表文章显示机构名；国家级新闻不混入「活跃地市」榜 |

部委站的通用差异（都已沉淀进 `app/crawler/base.py`）：大量文章 URL 以 `.htm` 而非 `.html` 结尾；人民银行把文章放在 `/<14位时间戳>/index.html`；列表页无日期；标题尾部拼发布日期；正文首行是站点域名。此外 `same_site()` 拦住 `gov.cn` 公共后缀，避免把中国政府网通稿误收进部委源。

### 二次攻坚：WAF 与 JS 接口站点（2026-11-09）

首批接入时被 WAF / 证书 / Vue 接口挡住的 5 家已重新分析并全部实现。`app/crawler/waf.py` 按域名缓存通行 Cookie，`Fetcher.get()` 自动识别三类挑战并求解；求解失败只影响该源本轮，不拖垮其它源。

| 站点 | 障碍 | 解法 |
|---|---|---|
| 国家卫生健康委、国家药监局 | 创宇盾新版 412（`$_ts` 动态 VM + 外链混淆 JS，quickjs 缺 DOM 解不了） | 本机 Chrome headless + CDP 跑完挑战；一个域名一轮只启一个浏览器会话，直接取回渲染后的 HTML，并缓存 cookie 给同域后续请求复用 |
| 人力资源社会保障部 | HTTP 200 但整页只有设置 `EO_Bot_Ssid` 的挑战 JS | quickjs 执行内联脚本取回两个 cookie |
| 金融监管总局 | 列表与详情都是 Vue 空壳，走未公开 JSON 接口 | `url_template` 按 `docId` 拼详情页地址，`detail_api_template` 从 `SelectByDocId` 读 `docClob` 正文；Word 粘贴的 `<span>` 碎片按中文合并、去掉汉字间多余空格 |
| 海关总署 | https 自签证书链且回 504，当前网络策略未放行该域名 | 已加入 `HTTP_ONLY_HOSTS` 走明文；源配置默认 `enabled=False`，网络放行后改成 `True` 即可启用 |

412 预热依赖本机 Chrome（默认 macOS 路径，可用 `CHROME_PATH` 覆盖）与 `websockets` 包；找不到 Chrome 时这两个源本轮失败，其它源不受影响。CDP 请求显式关闭 `trust_env`，避免环境里的 `HTTP_PROXY` 把 127.0.0.1 的调试端口请求转发到代理。临时库实测 4 个启用源共 23 篇全部带发布日期；纯图片稿（人社部偶有）无正文，按既有规则抑制 30 天不重试。

## 执行报告

每轮定时任务（12:00 / 21:00）在抓取、解读、热备全部完成后，自动生成一份执行报告并推送：

- 产出 `data/reports/YYYY-MM-DD_HHMM.html`（独立可分发，内嵌样式）与同名 `.md`（纯文本摘要）
- 六段结构：总览 KPI、本轮新增、异常与处置、源级明细、近 6 轮趋势、库状态与下次执行
- 报告里每条异常都写明影响与「下轮自动重试，无需处理」，避免看到备注误以为系统故障
- 待解读 > 0 / AI 错误 / 源级失败时，报告标题加「【注意】」、飞书卡片转红
- 网页入口：后台「执行报告」卡片列出历史报告，可点开或「立即生成并推送」
- 推送由 `app/notifier.py` 直连 webhook，不依赖 AI 会话；**推送失败只记日志，不影响抓取结果**
- 手动命令：`.venv/bin/python scripts/execution_report.py --notify`（补历史用 `--all`，指定轮次用 `--run "2026-11-07 12:00"`）
- 报告静态文件挂在 `/reports/`；`latest.html` 恒为最新一轮，供在线固定链接同步

### 手机看完整报告

服务只监听 127.0.0.1，因此完整报告通过**活页（LivePage）固定链接**发到手机：飞书卡片里带「查看完整报告」按钮，点开是当前最新一轮的全部内容（含全量源级明细与趋势图），链接不变、每轮自动更新。

链路分两段，互不阻塞：

1. **本机每轮**：`execution_report.py` 生成报告后调用 `app/publisher.py`，把最新报告覆盖为 `data/reports/latest.html`，并写 `latest.meta.json`（轮次、方案 ID、链接）。纯本地操作，不联网，永远能产出。
2. **平台定时自动化**（每天 12:10 / 21:10）：读取 `latest.html` 全文，用活页 `publish_file` 发到同一个 `LIVEPAGE_PROPOSAL_ID`，链接恒定、版本自动切换；失败只影响在线版，本地报告与飞书推送照常。

配置：把活页发布后的默认链接与方案 ID 填进 `.env` 的 `REPORT_PUBLIC_URL` / `LIVEPAGE_PROPOSAL_ID`，飞书卡片即自动加按钮。可见性在活页后台设为口令可看；**口令不要写进仓库**。

### 09:00 存活心跳

`scripts/heartbeat.py` 是**独立于 Web 服务进程**的自检脚本——若只挂在应用内调度器，服务整个挂掉时反而发不出告警。检查项：HTTP 200、数据库可读、近 26 小时内有抓取轮次、最新报告、最新热备、AI 解读积压、磁盘余量；正常推绿色摘要，异常推红色告警并附排障命令。

双调度（同一脚本按「日期+状态」当天去重，不会重复推送）：

- 系统级 `~/Library/LaunchAgents/com.jt.gov-news-heartbeat.plist`，每天 09:00；注册用 `scripts/install_heartbeat.sh`，或在访达双击 `scripts/run_heartbeat_install.command`（IDE 会话内常因 GUI 域权限无法直接 bootstrap，双击可完成）。
- WorkBuddy 定时自动化每天 09:00 兜底，plist 尚未加载时也能告警。

### 周报与月报

`app/period_report.py` + `scripts/period_report.py`：统计上一完整周 / 月的发布量、日均、活跃地市、国家部委新闻量、主题热度、上升信号、代表文章、抓取健康度，调用 AI 生成约 200 字政策走向综述，产出 HTML + Markdown 到 `data/reports/`（后台报告列表自动包含），并推飞书摘要。

- 周一 09:00 随心跳生成上周周报；每月 1 日生成上月月报
- **AI 失败自动降级**：402 / 429 / 超时一律改为纯统计版，报告与推送不中断
- 手动：`.venv/bin/python scripts/period_report.py --period weekly --notify`（`--date 2026-12-01` 可指定计算基准日）

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

国家级新闻的 `region_city` 为空，地市活跃度与热力图都显式排除 `level='national'`，避免被 `city or '广东省'` 归到广东省组挤占榜首；趋势页 KPI 单列「国家部委新闻」，政策信号链里的国家级文章显示机构名。

P2 深化（`app/trends_extra.py`）：

- **政策信号串联**：按标题关键词把文章归入「征求意见 → 正式印发 → 贯彻落实 → 政策解读」四阶段（`STAGE_RULES` 顺序即优先级），再按 AI 主题标签聚成时间线；只展示覆盖 ≥2 阶段的主题，每条链可展开各阶段代表文章。泛词（推进 / 调研 / 部署）被刻意排除，避免把日常动态误判成政策落地信号。
- **同主题地市对比**：Top 8 主题 × Top 10 地市的交叉发文量热力图，直接看出同一议题下谁在密集发声。
- 接口在原有返回里新增 `signals`（`chains` / `stage_totals` / `signal_total`）与 `matrix`（`topics` / `cities` / `cells` / `max`）。

## 测试

```bash
.venv/bin/python scripts/run_tests.py
# 或：.venv/bin/python -m unittest discover -s tests -t . -v
```

标准库 `unittest`，100 个用例、约 0.2 秒，覆盖标题清洗、同站过滤（含 `gov.cn` 公共后缀）、列表解析、JSON 列表与 URL/meta 日期兜底、三类 WAF 挑战识别与 cookie 求解、金融监管总局 JSON 接口与公文正文清洗、三层去重（真实 SQL，含层级隔离）、报告轮次聚合、cron 解析、飞书签名与推送降级、认证密钥隔离、无正文豁免生命周期，以及 P2 的政策阶段识别、政策链与地市矩阵（独立临时库）、周期窗口与 AI 降级、固定链接产出、飞书卡片按钮链接。

**测试库隔离有两层，缺一不可**：`tests/__init__.py` 把 `DATABASE_URL` 强制指向临时库；`app/db.py` 再按进程命令行识别 unittest/pytest，发现仍指向 `news.db` 时自动切到临时库。原因是 `python -m unittest discover -s tests`（不带 `-t .`）不会导入 `tests` 包，包内隔离会失效，测试里的 `delete()` 会清空生产表——务必用 `scripts/run_tests.py` 或带 `-t .` 的 discover 命令。

## 维护脚本

| 命令 | 用途 |
|---|---|
| `scripts/run_tests.py` | 一键跑全部单测 |
| `scripts/backup_db.py` | 手动做一次数据库热备 |
| `scripts/execution_report.py --notify` | 生成最近一轮报告、更新 `latest.html` 并推送 |
| `scripts/period_report.py --period weekly --notify` | 生成上一完整周/月报告并推送（AI 综述，失败自动降级） |
| `scripts/heartbeat.py --dry-run --no-period` | 09:00 存活自检（不推送、不触发周期报告） |
| `scripts/install_heartbeat.sh` | 注册 09:00 心跳 LaunchAgent（配合双击 `run_heartbeat_install.command`） |
| `scripts/interpret_backlog.py 10 2` | 消化待解读积压（批大小、间隔秒） |
| `scripts/discover_sources.py` | 自动探测地市站点列表页 |
| `scripts/audit_sources.py` | 全源体检：存量噪音扫描 + 逐源实时重抓验证 |
| `scripts/crawl_meizhou_once.py` | 一次性补跑梅州两个源（开发期遗留） |
| `scripts/install_launchd.sh` | 注册 launchd 服务（配合双击 `run_launchd_install.command`） |

每次新增源或调整选择器后建议跑一次全源体检；每日两轮的全部源状态可在执行报告里查看。

## 部署到云服务器

1. 代码同步到服务器，按「从零部署」重建 `.venv` 并装依赖
2. **必须先改**：强口令、独立 `AUTH_SECRET`、`.env` 权限 600；服务当前默认只监听 127.0.0.1
3. `DATABASE_URL` 换 PostgreSQL（需 `pip install psycopg2-binary`）
4. systemd 托管 uvicorn 常驻（APScheduler 随进程启动）
5. nginx 反代 + 域名 + HTTPS，并配置报告目录的鉴权
6. 设 `BACKUP_MIRROR_DIR` 做异地备份

## 已知事项与边界

- **定位是「精要闻」**：66 源（65 启用）每站只收一个主新闻栏目（各区未铺开部门动态与街镇信息，各部委未铺开司局/直属单位子站），中央通稿跨源去重后稳态日增数十至上百篇，SQLite 完全够用；需求文档里「日均数千条」的设想对应「全量政务信息」定位，届时需评估 PostgreSQL 与 worker 拆分。源数与 AI 解读配额、每轮耗时成正比，扩源前先跑一次全源体检。
- 飞书卡片是**摘要 + 「查看完整报告」按钮**；按钮指向活页固定链接（口令可看），每轮 12:10 / 21:10 由平台自动化发新版本。若 WorkBuddy 未运行，在线版会停在最后一轮，本机 `latest.html` 与飞书推送仍正常。
- 未配置 AI Key 时新闻照常抓取入库（`status=fetched`），补 Key 后点「立即 AI 解读」或等下一轮自动补。
- `.env`、`.workbuddy/`、`data/`、`.venv*`、`runtime/` 均被 `.gitignore` 排除；`scripts/` 下少数脚本含开发机绝对路径，换机器需改。
- 需求与技术方案见 `docs/需求文档-v1.md`、`docs/技术方案-v1.md`（分期路线以实际实现为准）。
