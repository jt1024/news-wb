# 政务新闻聚合平台（广东 · 一期 1.5）

覆盖广东省级 + 20 个地市政府官网（25 个源），自动抓取政务新闻、三层去重、AI 解读并支持按地域/类型/时间筛选。仅自用，当前本地部署。

## 快速开始

```bash
cd news-app
python3 -m venv .venv                 # 首次
.venv/bin/pip install -r requirements.txt
cp .env.example .env                  # 编辑：设置 ADMIN_PASSWORD、AI_API_KEY
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8300
```

- 前台：http://127.0.0.1:8300 （新闻流、搜索筛选、详情页单篇手动解读）
- 后台：http://127.0.0.1:8300/admin （手动触发抓取/解读、实时进度、每批条数、源管理、复核队列）
- 默认口令见 .env 的 `ADMIN_PASSWORD`（务必修改）；登录用无状态 HMAC 令牌，重启服务不掉登录

> 服务目前由会话拉起，重启电脑后需手动启动；建议后续加 launchd 开机自启。

## 配置项（.env）

| 项 | 说明 |
|---|---|
| ADMIN_PASSWORD | 访问口令（同时作为 HMAC 签名密钥） |
| AI_PROVIDER | deepseek / minimax / qwen（留空则跳过 AI 解读，新闻照常入库） |
| AI_API_KEY / AI_BASE_URL | OpenAI 兼容接口的 Key 与地址 |
| AI_MODEL | 常规解读模型，当前 `MiniMax-M3.1-Flash` |
| AI_MODEL_STRONG | 政策类新闻自动切换的强模型，当前 `MiniMax-M3`（推理模型，输出带 `<think>` 块，解析时自动剥离；未配则回退常规模型） |
| INTERPRET_BATCH_SIZE | 每批解读条数，可在后台「每批条数」输入框临时覆盖 |
| INTERPRET_RETRIES | 单篇失败重试次数，当前 2；失败原因写入 news.ai_error |
| DATABASE_URL | 默认 SQLite（data/news.db），上云换 postgresql:// |
| CRON_HOURS / CRON_MINUTE | 每天触发的小时列表（逗号分隔），当前 `12,21` / `0`，即 12:00、21:00 两次；旧 `CRON_HOUR` 仍兼容 |
| CRON_HOUR | 单时刻回退值，仅当 CRON_HOURS 为空时生效 |
| NOTIFY_CHANNEL | 执行报告推送渠道：`feishu`（飞书群机器人）/ `wecom`（企业微信群机器人）/ `serverchan` / `pushplus` / `custom` / `off` |
| NOTIFY_WEBHOOK | feishu / wecom / custom 的机器人地址；custom 会收到 `{title, text, markdown, report_html, round}` JSON |
| NOTIFY_TOKEN | serverchan（Server酱 Turbo）/ pushplus 的 token |
| NOTIFY_SECRET | 飞书机器人开启签名校验时填写，留空表示未开启 |

定时任务注册了 `misfire_grace_time=3600, coalesce=True`：进程被短暂节流导致错过触发点时，1 小时内仍会补跑，且多次错过只补一次。

## 执行报告

每轮定时任务（12:00 / 21:00）在抓取与 AI 解读全部完成后，自动生成一份执行报告并推送：

- 产出 `data/reports/YYYY-MM-DD_HHMM.html`（独立可分发，内嵌样式）与同名 `.md`（纯文本摘要）
- 报告含：总览 KPI、本轮新增、异常与处置、源级明细、近几轮趋势、库状态与下次执行
- 网页入口：后台「执行报告」卡片列出历史报告，可点开查看；也有「立即生成并推送」按钮
- 推送由 `app/notifier.py` 直连 webhook，不依赖 AI 会话；**推送失败只记日志，不影响抓取结果**
- 手动命令：`.venv/bin/python scripts/execution_report.py --notify`（补历史用 `--all`，指定轮次用 `--run "2026-11-07 12:00"`）
- 报告静态文件挂在 `/reports/`，仅监听 127.0.0.1，不对外暴露

## 架构

```
抓取（httpx 异步 + curl 兜底；html / rss / json 三种 fetch_type）
  → 正文清洗（17+ 类版式噪音 + 前导元数据剥离）
  → 三层去重（URL 归一化哈希 / 标题指纹+difflib（同地域）/ SimHash64）
  → SQLite → AI 解读（批处理、重试、置信度分级复核、模型分级）
  → JSON API → Web 前端
```

- 定时：APScheduler 单 cron 任务多时刻触发；手动触发：后台按钮（异步任务 + progress_cb 实时进度）
- 源站点存库管理（`app/crawler/sources.py` 种子 + 后台「新增源」表单），加源无需改代码
- 深圳站 TLS 国密握手失败时自动回退 curl；珠海列表为 JS 渲染，改走 `postmeta` JSON 接口
- 二期小程序/公众号直接复用 `/api/*` 接口

## 维护脚本

```bash
.venv/bin/python scripts/discover_sources.py   # 自动探测地市站点列表页
.venv/bin/python scripts/audit_sources.py     # 全源体检：存量噪音扫描 + 逐源实时重抓验证
```

每次新增源或调整选择器后建议跑一次体检。当前结果：25/25 源提取正常，库内 0 条可疑数据。

## 部署到云服务器

1. 代码同步到服务器，安装同 requirements
2. DATABASE_URL 换 PostgreSQL（需 `pip install psycopg2-binary`）
3. systemd 托管 uvicorn 常驻（APScheduler 随进程启动）
4. nginx 反代 + 域名

## 已知事项

- 梅州源站有 WAF JS 挑战且源站返回 521，程序无法接入；站点恢复后可在后台表单补配列表页
- 未配置 AI Key 时新闻仍正常抓取入库，status=fetched，可随时补 Key 后点「立即 AI 解读」
- 数据规模到日增 5000+ 时建议升级 PostgreSQL 并把抓取/解读拆为独立 worker
- 需求与技术方案见 `docs/需求文档-v1.md`、`docs/技术方案-v1.md`（分期路线以实际实现为准）
