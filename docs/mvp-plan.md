# research-agent MVP 方案

> 采集引擎与两个产出模式(完整文章 / 日报)的落地方案见 [`docs/collect-engine-plan.md`](collect-engine-plan.md),本文件保留 MVP 的原始设计。

> 定位:内部使用的「AI Agent 采集工具」——按研究方向关键词库定时抓取论文期刊、AI 前沿进展与产业落地信息,经去重 / 翻译 / 摘要 / 三维打分后入库,形成社区资讯流与研讯素材池,并预留推送出口。
> 技术栈:Python 3.12 + FastAPI + SQLAlchemy(async)+ PostgreSQL(pgvector 实例)+ APScheduler;React 18 + TypeScript + Vite + Ant Design 5。

---

## 1. 分类体系:用两个正交维度替代单选分类

原始分类「论文期刊 / 新闻 / 科技资讯 / 推文 / GitHub 热榜」互相重叠(科技资讯≈新闻,GitHub 热榜是渠道不是内容类型,推文是渠道也不是内容类型),按单选分类会导致同一篇文章归属不定、筛选维度缺失。MVP 改为**两个正交维度**:

### 1.1 内容类型 `content_type`(回答「这是什么内容」)

| 值 | 中文 | 判定方式 | 时效 τ |
| --- | --- | --- | --- |
| `paper` | 论文 | arXiv 渠道默认;其他渠道由 LLM 判定 | 168h |
| `tech` | 技术 | RSS/博客/GitHub 默认;LLM 判定 | 72h |
| `industry` | 产业 | LLM 判定(融资、发布、商业化、政策) | 48h |
| `community` | 社区 | HN 等社区渠道默认;LLM 判定 | 24h |

判定优先级:`采集器 hint` → `渠道默认值` → `LLM 判定`。

### 1.2 渠道 `channel`(回答「从哪来、怎么采」)

| 渠道 | 采集方式 | 备注 |
| --- | --- | --- |
| `rss` | RSS/Atom 全文流 | 官方博客、媒体、个人博客 |
| `arxiv` | API 关键词检索 | 论文主源 |
| `github` | 榜单页 HTML 解析 | Trending,带 stars 指标 |
| 预留 | `twitter` / `x` / `weibo` / `bilibili` / `manual` | 新增一个 collector 文件即可 |

- 这样「GitHub 热榜」= 渠道 `github` + 内容类型 `tech`,`推文` = 渠道 `twitter` + 内容类型 `tech|industry`,`新闻` 与 「科技资讯」不再需要二选一。
- 前端资讯流按 `content_type` 分段筛选(全部 / 论文 / 技术 / 产业 / 社区),后续可再加渠道筛选。

### 1.3 采集模式(回答「怎么采」)——与上面两维正交

| 模式 | 说明 | 实现 |
| --- | --- | --- |
| 流式采集 | RSS 列表逐条入库 | `collector_kind=stream` |
| 检索采集 | 按主题关键词检索(arXiv) | `collector_kind=search` |
| 榜单采集 | 抓热榜并按关键词过滤 | `collector_kind=trend` |
| 单篇长文深挖 | 对单条内容抽取正文 + LLM 深挖卡片(背景 / 方法 / 结论 / 启示) | `resources` 全文抽取 + `POST /api/items/{id}/enrich` |
| 多篇概括总结 | 按方向/时间窗召回高分素材,聚合为日报/素材池 | `POST /api/digests/generate` |

---

## 2. 来源池(信源池)

- `sources` 表:名称、渠道、采集类型、URL、Tier(A/B/C)、抓取频率、启停、`config`(JSON)、最近成功时间、连续失败次数。
- `topic_sources` 绑定:主题 ↔ 信源多对多;主题不绑定时使用「全部启用信源」,绑定后只采该子集。
- 内置**推荐信源库**(22 条,`GET /api/sources/recommended`),覆盖:arXiv、GitHub Trending、OpenAI/DeepMind/Meta/HF/Google Research/Anthropic 官方、HN、Simon Willison、Latent Space、The Batch、Import AI、机器之心、量子位、36氪、InfoQ 等,支持勾选后一键导入并绑定主题。
- 单源「测试」按钮:立即抓取并在前端展示前 5 条标题/URL/时间,用于验证配置与网络可达性。

---

## 3. 数据模型(15 张表)

| 分组 | 表 | 说明 |
| --- | --- | --- |
| 配置 | `sources` | 来源池(采集时按需勾选,不选则全部启用) |
| | `settings` | 键值配置(LLM、通用参数) |
| 内容 | `raw_documents` | 原始抓取记录(审计 + 失败重试) |
| | `items` | 规范化条目:canonical_url、title_fingerprint、simhash、channel、content_type、lang、metrics |
| | `item_contents` | 正文/摘要/翻译/深挖卡片(JSONB) |
| | `item_scores` | 三维分数 + 明细(关键词命中、LLM 分、权重) |
| 产出 | `digests` / `digest_items` | 日报(素材池):Markdown、要点、模型、关联条目 |
| 推送 | `push_channels` / `push_logs` | 渠道配置与推送日志 |
| 任务 | `job_runs` | 采集 / 日报 / 推送任务的状态、日志、统计 |

> 已移除(2026-09-30):`topics` / `keywords` / `topic_sources` / `item_topics` 四张表与 `digests.topic_id` 列已从数据库删除,对应 ORM、schema、`/api/topics` 路由、APScheduler 调度器一并从代码中移除。

---

## 4. 流水线

```
手动采集(采集工作台,关键词即输即用;无预设、无定时调度)
  → ① 配置:手动输入研究方向关键词 / 排除词 / 信源 / 回看窗口 / 入库门槛(即输即用,不保存预设)
  → ② 采集:并发抓取信源(collectors: rss / arxiv / github_trending,并发可配)
  → ③ 标准化:URL 归一化去 utm、标题指纹、SimHash 近似去重、关键词过滤(exclude 命中即丢)
  → ④ 富化打分:LLM 翻译 + 摘要 + 标签 + 内容类型 + 相关度/热度;未配置时降级 → 三维打分
  → ⑤ 入库产出:入库(items / item_contents / item_scores),资讯流与日报素材池
```

- **采集工作台(默认首页 `/collect`)**:
  - 关键词/排除词/信源/回看窗口/门槛均为采集时输入,一次采集 = 一组手动输入的关键词。产品上已彻底移除「预设/主题」概念:管理页面、菜单、资讯流筛选、来源绑定、日报主题选择、调度器与数据表全部删除。
  - 顶部流水线看板(`PipelineBoard`)对应上表五个阶段:五列等宽,圆点连线 + 阶段卡片,卡片内为「执行结果」三格统计(配置:关键词/回看窗口/入库门槛;采集:抓取/信源/失败源;标准化:去重/过滤/候选;富化打分:打分/LLM 错误/均分;入库产出:本次入库/低分跳过/资讯流累计)+ 彩色执行按钮 + 时间戳,节点状态随任务日志实时推进(待执行 / 进行中 / 成功 / 失败);窄屏按 3 / 2 / 1 列换行。
  - **配置走弹窗(第一环)**:配置卡的按钮打开 `Modal` 填表,只有 4 个字段——研究方向、关键词(命中任一即收录,回车分隔)、回看窗口(小时)、入库门槛(tooltip 说明权重);弹窗底部「开始采集」即提交,任务创建成功后自动关闭,有任务时按钮文案变为「修改配置 / 重新采集」。表单用 `forceRender` 常驻挂载,卡片三格统计随输入实时联动;排除词与信源勾选暂时从界面下线(后端 `exclude_keywords` / `source_ids` 仍完整支持,默认全部启用信源),来源池仍在 `/sources` 独立维护。
  - 每个环节一个动作:配置→配置采集(弹窗,弹窗内「开始采集」提交) / 采集→查看日志 / 标准化→查看报告 / 富化打分→生成日报 / 入库产出→查看资讯流。
  - 阶段推进依据任务日志标记:`开始采集` → ①,`抓取 N 条` → ②,`标准化完成` / `候选均已存在` → ③,`入库[...]` / `完成: 新入库` → ④,任务终态 → ⑤ 全部置为成功或失败;失败任务回到出错环节(关键词缺失 → 配置、无可用信源 → 采集)。
  - 采集报告由 `job.result` 结构化数据生成(旧任务回退解析日志),Markdown 渲染:标题、关键词、信源、结果统计表、入库明细(完整标题 + 三维分数 + 原文链接),支持一键复制。
- **入库门槛生效**:三维总分 `< spec.min_score` 的条目直接跳过(不落库),计入 `result.low_score`,日志逐条打印「低于门槛(N)跳过: 标题(相关/热度/时效 → 总分)」;全部被拦时提示可下调门槛。实测 `min_score=70`:抓取 52 → 过滤 21 → 去重 7 → 低于门槛 14 → 入库 10(入库项总分均 ≥70)。
- **无定时调度**:APScheduler 与 `RA_SCHEDULER_ENABLED` 已移除,采集只能由人工在工作台触发;库中 4 张预设相关表与 `digests.topic_id` 已删除。
- **去重**:URL 归一化哈希 + 标题指纹 + SimHash 三路;实测第二轮采集 61 条全部判重,`new_items=0`。
- **降级**:LLM 未配置或调用失败时,使用规则模板(截断摘要、原标题、渠道默认类型),流程不中断,任务日志标注「降级模式」。
- **失败隔离**:单信源失败不影响其他信源,计入 `failed_sources` 并保留 `raw_documents` 便于重试。

---

## 5. 打分公式

```
relevance = 0.6 × keyword_rel + 0.4 × llm_rel      (无 LLM 时 relevance = keyword_rel)
heat      = metric_heat  →  llm_heat  →  45(缺省)
freshness = 100 × exp(-age_hours / τ(content_type))
total     = 0.45 × relevance + 0.35 × heat + 0.20 × freshness
```

- `keyword_rel`:命中关键词权重和 / min(总权重, 6),上限 100;保证长尾关键词不被稀释。
- `metric_heat`:GitHub `stars_total`(log 归一)+ `stars_today`,HN `points`(log 归一)。
- `τ`:paper 168h / tech 72h / industry 48h / community 24h——论文衰减慢,社区帖子衰减快。
- 权重可在采集时的 `score_weights` 参数覆写,并写入 `item_scores.detail.weights`。
- 门槛:采集时输入的 `min_score` 控制入库(低于即跳过,计入 `result.low_score`),日报召回默认 60 分。

> 实测提示:LLM 未配置时论文类 `relevance` 上限约为 50(仅关键词命中),总分多在 45–57,会低于默认门槛 60;配置 LLM 后 LLM 相关度补足 40% 权重,分数整体抬升。若暂时不配 LLM,建议把主题门槛临时降到 40–45,或仅在日报召回时放宽。

---

## 6. 日报 / 素材池

- `POST /api/digests/generate`:`period_hours` 默认 24,`max_items` 默认 12。
- 召回:时间窗内 `total >= min_score` 的条目按分数排序取前 N。
- 生成:LLM 按 `prompts/digest.md` 输出「标题 + 导语 + 今日要点 + 逐条摘要 + 来源链接」;未配置 LLM 时走降级模板,同样产出 Markdown 与来源链接。
- 存储:`digests.content_md` 即素材池正文,前端直接渲染并支持导出/复制。

---

## 7. 推送出口(暂不对接飞书)

- `PushProvider` 注册表:`kind → provider`,当前内置 `webhook`(通用 JSON POST,支持 headers / token / payload 模板)与 `export`(导出)。
- 新增平台(飞书 / 钉钉 / 企业微信 / Discord / 邮件)只需在 `app/services/push/` 增加一个 provider 文件并注册,核心流程零改动。
- 每次推送写 `push_logs`(请求摘要、响应、错误),任务中心可查。
- 已验证:本地 webhook 收到 880 字节 payload(标题 / 导语 / Markdown 正文 / 要点),任务 `push` 状态 `succeeded`,`push_log_id=1`。

---

## 8. API 一览

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET/POST | `/api/sources` | 信源列表 / 新建 |
| GET | `/api/sources/recommended` | 推荐信源库 |
| POST | `/api/sources/import-recommended` | 一键导入推荐信源 |
| POST | `/api/sources/{id}/test` | 单源试抓 |
| GET | `/api/items` | 资讯流(类型 / 分数 / 排序 / 搜索 / 分页) |
| GET | `/api/items/{id}` | 详情(正文、分数明细) |
| POST | `/api/items/{id}/enrich` | 生成深挖卡片 |
| GET/POST | `/api/digests`、`/api/digests/generate` | 日报列表 / 生成 |
| DELETE | `/api/digests/{id}` | 删除日报 |
| GET | `/api/jobs`、`/api/jobs/{id}` | 任务列表 / 详情(含日志) |
| POST | `/api/jobs/fetch` | 手动触发采集:`name/keywords/exclude_keywords/source_ids/lookback_hours/min_score/score_weights` |
| POST | `/api/jobs/push` | 推送日报到指定渠道 |
| GET/PUT | `/api/settings/llm`、`/api/settings/general`、`/api/settings/push-channels` | 配置 |
| GET | `/api/stats/overview` | 顶部统计 |

---

## 9. 前端页面

| 路由 | 页面 | 要点 |
| --- | --- | --- |
| `/collect` | 采集工作台(默认首页) | 流水线看板 + 关键词即输即用采集、实时日志、Markdown 采集报告(统计 + 入库明细 + 原文链接) |
| `/feed` | 资讯流 | 统计条、类型 / 分数 / 排序 / 搜索筛选、三维分数标签、详情抽屉(正文、深挖卡片、原文) |
| `/digests` | 日报 / 素材池 | 日报列表 + Markdown 渲染、生成日报、删除 |
| ~~`/topics`~~ | 已下线 | 预设概念取消,路由与菜单已移除,访问任意未知路径重定向到 `/collect` |
| `/sources` | 信源池 | 列表、推荐源库导入、单源测试、编辑、启停 |
| `/jobs` | 任务中心 | 任务列表与日志、跳转采集工作台、生成日报、复制任务 ID |
| `/settings` | 设置 | LLM(base_url / model / api_key / 超时 / 并发 / 启停 / 用途)、通用参数、推送渠道 |

---

## 10. 验收记录(MVP)

| 项 | 结果 |
| --- | --- |
| 端到端采集 | 4 信源抓 80 条 → 过滤 19 → 入库 61 条,三维打分正常 |
| 二次采集去重 | 61 条全部判重,`new_items=0 / duplicates=61` |
| 日报生成 | 无 LLM 时降级模板产出 Markdown + 来源链接;UI 生成「综合 研讯简报」成功 |
| 推送出口 | 本地 webhook 收到 payload,`push_logs` 记录成功 |
| 推荐源导入 | 导入 OpenAI News 成功,单源测试抓到 5 条真实数据 |
| ~~主题配置~~ | 已废弃:预设概念整体移除 |
| LLM 配置 | 真实网关(OpenAI 兼容)连接测试通过(base_url 自动补 `/v1`) |
| LLM 采集全链路 | 采集「具身智能」关键词新入库 42 条,`llm_errors=0`:中文译名、中文摘要、LLM 相关度/热度全部生效,总分 51–84 |
| 采集工作台(临时采集) | 关键词 `multimodal` + 仅 arXiv:抓取 50 → 去重 2 → 新入库 48,`llm_errors=0`;验证关键词即输即用、不写任何预设表 |
| 流水线看板 | 四阶段(采集/标准化/富化打分/入库产出)状态随日志推进:运行中显示「进行中」,完成后四格均显示「成功」并给出真实统计(38 抓取 / 2 去重 / 34 过滤 / 2 入库 / 0 失败) |
| Markdown 采集报告 | 由 `job.result.items` 生成:完整标题 + 三维分数 + 原文链接,可一键复制;`result.items` 为新增结构化字段(最多 200 条) |
| 入库门槛生效 | `min_score=70`:「门槛验证」抓取 52 → 过滤 21 → 去重 7 → **低于门槛 14** → 入库 10,入库项总分均 ≥70;日志逐条可查 |
| 去预设化(代码) | 菜单/路由/资讯流筛选/信源绑定/日报主题选择全部移除主题入口;`/api/topics` 路由、`Topic`/`Keyword`/`TopicSource`/`ItemTopic` 模型、APScheduler 调度器与 `apscheduler` 依赖一并删除 |
| 去预设化(数据) | `topics` / `keywords` / `topic_sources` / `item_topics` 四张表与 `digests.topic_id` 列已 `DROP`;库中仅剩 11 张表(items=163、digests=2 未受影响) |
| 测试 / 静态检查 | `pytest` 27 passed(含 `spec_from_params` 4 条新增用例);`ruff check .` 通过;前端 `tsc` + `vite build` 通过 |

### MVP 期间修复的问题

1. `PUT /api/topics/{id}` 返回 500:更新主题时关键词先 INSERT 后 DELETE,触发 `uq_keyword_topic_word_kind` 唯一约束 → 改为先清空并 flush,再插入。
2. 「新建主题 / 新建信源」表单残留上次编辑值 → 补齐创建态的默认字段(name/url/description/cron)。
3. 任务中心「生成日报」请求 `/api/jobs/digest`(不存在,405)→ 改指 `/api/digests/generate`。
4. **LLM「测试连接」返回 Internal Server Error**:网关对错误路径回 200 + HTML(SPA 首页),`resp.json()` 抛 `JSONDecodeError` 且路由只捕获 `LLMError` → 三处修复:
   - `normalize_base_url()`:自动补 `/v1`(仅当 URL 无路径时)、剥离误粘的 `/chat/completions`;
   - 非 JSON 响应转成可读的 `LLMError`(含响应片段与提示),不再 500;
   - 测试接口兜底 `except Exception`,任何异常都以 `ok=false` 返回。
5. **深挖卡片重打分丢失热度/时效**:`enrich` 重算分数时传 `metric_heat_score(None)` 且只看 `published_at` → 改为读取该条目 `raw_documents.payload.metrics`(GitHub stars / HN points),时效回退 `first_seen_at`,并复用入库时记录的权重与关键词命中(`item_scores.detail`)。
6. **服务重启后任务永久卡住**:进程崩溃/重启会在 `job_runs` 留下 `pending`/`running` 孤儿任务,导致同类任务永远返回 409 → 启动时 `JobExecutor.recover_stale()` 统一标记为「服务重启,任务被中断」。

---

## 11. 后续迭代建议

| 优先级 | 事项 |
| --- | --- |
| P0 | 存量条目回填:已有 61 条(LLM 配置前入库)没有译名/摘要/LLM 分数,建议加一个「批量重新富化」任务或在重采集前清理旧数据 |
| P0 | LLM 到位后回归:日报质量、深挖卡片、内容类型判定(industry 依赖 LLM) |
| P1 | 推送 provider:飞书 / 钉钉 / 企业微信 / 邮件(仅新增 provider 文件) |
| P1 | 采集门槛:已改为「入库即过滤低分」;可继续支持按内容类型分阈(论文/技术/产业/社区不同阈值) |
| P2 | 定时采集:如后续需要「无人值守」,可新增独立的调度配置(不恢复预设表) |
| P1 | 采集工作台支持任务取消 / 并发排队(当前同类任务同一时刻只允许一个) |
| P1 | 资讯流与报告导出(CSV / Markdown 文件下载)、按时间窗回看导出 |
| P1 | 渠道扩展:Twitter/X、微博、Reddit、Hugging Face Papers、Semantic Scholar |
| P2 | 向量检索:pgvector 已在实例中,可加 `item_embeddings` 做语义检索 / 相似推荐 |
| P2 | 认证:`RA_API_TOKEN` 已支持 Bearer,可在反代层启用 |
| P2 | 前端拆包(当前单 chunk 1.3MB)、日报导出 PDF/Word |
