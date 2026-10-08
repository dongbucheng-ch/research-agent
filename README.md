# research-agent

<p>
  <a href="https://github.com/dongbucheng-ch/research-agent/actions/workflows/ci.yml"><img src="https://github.com/dongbucheng-ch/research-agent/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/Python-3.12%2B-3776AB.svg" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/Node-20%2B-339933.svg" alt="Node 20+">
  <img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs welcome">
</p>

**关键词驱动的研究与资讯采集平台。** 按研究方向抓取论文、技术、产业与社区动态,经去重、翻译、摘要与「相关度 / 热度 / 时效」三维打分后入库,沉淀为资讯流与研讯素材池,并生成 **日报 / 深度文章**,通过可插拔的 Provider 推送到外部平台。

## 特性

- **全链路可视**:采集 → 标准化 → LLM 富化 → 三维打分 → 入库产出,采集工作台用流水线看板实时显示每个阶段的状态与计数,任务中心保留完整日志。
- **多引擎采集**:内置 `rss` / `news` / `github` 三类引擎,覆盖 RSS、arXiv、Hacker News、Google News、Bing News、GitHub Trending & Search、Hugging Face Papers 等采集器,正文抽取与失败隔离内置。
- **可解释打分**:相关度 / 热度 / 时效三维加权(定向模式 `0.5 / 0.3 / 0.2`,全局模式 `0.6 热度 + 0.4 时效`),低于入库门槛的候选会在报告中列为「低于门槛跳过」。
- **诚实的降级**:未配置 LLM 时全流程照常运行——不翻译、不做 LLM 摘要,只保留关键词相关度打分;配置后逐级增强,任务日志会标注降级模式。
- **两类产出物**:日报(固定版式:资讯摘要 + GitHub 今日推荐,按「日期 · 第 N 批」管理同一天多次生成)与深度文章(召回 → 过滤去重 → 大纲 → 逐节写作 → 合成,正文带 `[n]` 引用)。
- **三模式查看器**:预览 / Markdown 源码 / 结构化 JSON,选择记忆在本地。
- **可定制推送**:推送出口是 Provider 注册表(`webhook` / `export`…),渠道配置支持 `payload_template` 占位符(`$title`、`$lead`、`$content`、`$tags`、`$source`、`$author`),推送时可临时覆盖标题 / 来源 / 作者 / 标签,标签默认按素材自动汇总。
- **定时采集**:采集工作台内置「定时采集」卡片,最小间隔 5 分钟、最长 7 天,到点自动提交任务,冲突时跳过并记录原因。

## 架构

```text
collectors(8+ 信源)  →  pipeline/text(去重·清洗)  →  pipeline/enrich(LLM 富化,含降级)
                                                              │
                                                              ▼
            资讯流 / 素材池  ←  日报 · 文章  ←  pipeline/scoring(相关/热度/时效)
                                      │
                                      ▼
                            services/push(Provider 注册表)
```

- **后端**:FastAPI · SQLAlchemy 2(async)· PostgreSQL · APScheduler(进程内 60s tick 定时任务)
- **前端**:React 18 · TypeScript · Vite · Ant Design 5(构建产物由后端静态托管,单端口访问)
- **LLM**:任意 OpenAI 兼容接口(`/v1/chat/completions`),在设置页配置 base_url / model / api_key

## 快速开始

### 依赖

| 组件 | 版本 |
| --- | --- |
| Python | ≥ 3.12([uv](https://docs.astral.sh/uv/) 管理) |
| Node.js | ≥ 20(pnpm) |
| PostgreSQL | ≥ 14(本地 Docker 即可) |

### 1. 启动数据库

```bash
docker run -d --name research-agent-pg -p 25432:5432 \
  -e POSTGRES_USER=agent -e POSTGRES_PASSWORD=agent -e POSTGRES_DB=research_agent \
  postgres:16-alpine
```

### 2. 启动后端

```bash
cd backend
cp .env.example .env          # 按需修改数据库连接
uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8017
```

`RA_AUTO_CREATE_TABLES=true` 时启动会自动建表(当前用 `Base.metadata.create_all` 代替迁移)。

### 3. 构建前端

```bash
cd frontend
pnpm install
pnpm build                    # 产物 frontend/dist,由后端托管
```

打开 <http://127.0.0.1:8017/> 即为完整应用。

前端开发模式(热更新)使用 `pnpm dev`,端口 `5174`,已把 `/api` 代理到 `127.0.0.1:8017`。

## 配置

### 环境变量(`backend/.env`,前缀 `RA_`)

| 变量 | 说明 |
| --- | --- |
| `RA_DB_HOST` / `RA_DB_PORT` / `RA_DB_USER` / `RA_DB_PASSWORD` / `RA_DB_NAME` | 分字段填写数据库连接,避免密码含 `@` `!` 时的 DSN 转义问题 |
| `RA_DATABASE_URL` | 可选,完整 DSN(`postgresql+asyncpg://…`),与上者二选一 |
| `RA_AUTO_CREATE_TABLES` | 启动时自动建表,默认 `true` |
| `RA_API_TOKEN` | 可选,开启后所有 `/api/*` 需要 `Authorization: Bearer <token>` |
| `RA_GITHUB_TOKEN` | 可选,提高 GitHub Trending / Search 的 API 限额 |
| `RA_LLM_BASE_URL` / `RA_LLM_MODEL` / `RA_LLM_API_KEY` | 可选,环境变量优先于界面配置 |
| `RA_LOG_LEVEL` | 日志级别,默认 `INFO` |

### 界面设置(`/settings`)

- **LLM 配置**:base_url / model / api_key / 超时 / 并发 / 启用与翻译开关,附「测试连接」(回显上游响应片段便于排查)。
- **通用设置**:信源抓取并发、默认回看窗口(≤ 48 小时)、候选/富化上限(默认 100,上限 500)、批量富化条数。
- **推送渠道**:新建 / 编辑 / 启用停用 / 测试 / 删除,支持 JSON `payload_template` 与默认来源、作者。

## 使用

1. **设置**:配置 LLM 与通用参数(未配置 LLM 也可先跑通采集)。
2. **采集工作台**(默认页 `/collect`):填写研究方向与关键词即可采集(无需预设);中文关键词先由 LLM 扩展为英文检索词,再用于采集与打分。
   - 表单硬约束:回看窗口 ≤ 48 小时,入库门槛 ≥ 75 分,候选/富化上限默认 100 条(可在设置调整,上限 500)。
   - 顶部流水线看板实时显示五个阶段;完成后输出 Markdown 采集报告(统计 + 入库明细 + 原文链接)。
3. **信源池**(`/sources`):从推荐信源库导入或手工新增,支持连通性测试;采集默认使用全部启用信源。
4. **素材池**(`/pool`):素材 / 日报 / 文章三个 tab;素材抽屉按「先结论后元数据」组织,速读卡片固定为 **是什么 / 为什么重要 / 怎么用**。
5. **日报 / 文章**:日报列表以「`日期 · 第 N 批`」为主索引;文章支持查看 / 复制 / 删除,生成过程见任务日志。
6. **任务中心**(`/jobs`):采集 / 日报 / 文章 / 推送任务的状态、参数与日志。
7. **推送**:产出物详情里打开「推送设置」,可覆盖标题 / 来源 / 作者 / 标签(留空走默认:标题取产出物标题、来源与作者取渠道配置、标签按日报入选素材汇总)。

## 项目结构

```text
backend/
  app/
    api/routes/     sources / items / digests / articles / jobs / schedules / settings / stats
    collectors/     rss · arxiv · google_news · bing_news · hackernews · github_trending
                    · github_search · hf_papers + 正文抽取(registry 按引擎注册)
    pipeline/       text(去重清洗) · enrich(LLM 富化 + 降级) · scoring(三维打分)
    services/       llm · app_settings · fetch_service · digest_service · article_service
                    · jobs · schedules · push(Provider 注册表)
    models/ schemas/ prompts/ core/
  scripts/          维护脚本(旧卡片刷新等)
  tests/            pytest(默认不依赖数据库)
frontend/
  src/pages/        CollectPage / PoolPage / SourcesPage / FeedPage / JobsPage
                    / ArticlesPage / DigestsPage / SettingsPage
  src/components/   抽屉、看板、查看器等
docs/               设计文档与路线图
```

## 开发与测试

```bash
cd backend && uv run ruff check . && uv run pytest -q
cd frontend && pnpm typecheck && pnpm build
```

CI(GitHub Actions)对每个 PR 执行同样两组命令,见 `.github/workflows/ci.yml`。

提交信息格式为 `<type>(<YYYYMMDD>): <summary>`,详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 文档

| 文档 | 内容 |
| --- | --- |
| [docs/mvp-plan.md](docs/mvp-plan.md) | 分类体系、数据模型、流水线、打分公式与里程碑 |
| [docs/collect-engine-plan.md](docs/collect-engine-plan.md) | 采集引擎(3 类)与产出模式(文章 / 日报)的落地方案 |
| [docs/roadmap-p0-p4.md](docs/roadmap-p0-p4.md) | 迭代路线图与逐次变更记录 |
| [docs/source-health-2026-10-08.md](docs/source-health-2026-10-08.md) | 各信源可用性巡检记录 |

## 贡献

欢迎 Issue 与 PR:新增采集源只需在 `backend/app/collectors/` 实现并在注册表登记;新增推送渠道只需在 `backend/app/services/push/` 实现一个 `PushProvider`。详见 [CONTRIBUTING.md](CONTRIBUTING.md)。

## 许可与致谢

本项目以 [MIT License](LICENSE) 开源。设计或实现上参考了若干开源项目(实现借鉴、依赖引用与致谢清单见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)),其中 GPL / AGPL 项目仅借鉴设计、不复制源码。

> 采集行为请遵守目标站点的 robots.txt 与使用条款;推送到的第三方平台请自行确认其接口与内容规范。
