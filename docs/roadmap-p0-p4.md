# research-agent 执行路线图(P0–P4)

> 确认记录(2026-09-30,Master 确认):
> 1. 补量阈值「单次新入库 < 5 条时自动补量 1 轮」接受;
> 2. 「素材 → 产出」引用溯源本期做(P3-3);
> 3. 定时采集本期做,采用「收藏配置」方案(P4);
> 4. 完整文章与日报一样需要推送(P3-4)。
>
> 执行协议:每完成一步,先把结果与验证证据写入本文档「执行记录」,再进行下一步。
> 验证命令:后端 `cd backend && ./.venv/bin/python -m pytest -q && ./.venv/bin/ruff check .`;
> 前端 `cd frontend && pnpm exec tsc --noEmit && pnpm build`;真机采集统一用关键词「生物科技」。

---

## 0. 现状基线(已完成,不在本路线图范围)

- 三引擎采集:`rss` / `news`(arxiv、google_news、bing_news、hackernews)/ `github`(trending、repo、skill、model)。
- 中文关键词 LLM 翻译后参与采集与打分;统一重试与错误描述。
- 素材流水线:标准化 → 去重(URL/simhash/标题指纹)→ LLM 富化(翻译、摘要、分类)→ 三维打分 → 入库门槛。
- 产出:日报(10 条资讯 + 3-5 条 GitHub,正文 250-500 字符 / GitHub 100-200 字符)、完整文章(五步流水线)。
- 推送:仅 API 层能力(`push_channels` webhook/export + `push_logs`),前端未接入,日报与文章均未接。
- 任务中心:仅原始 log + result JSON;采集页阶段进度靠日志正则猜测。

---

## 1. 优先级总览

| 级别 | 事项 | 价值 | 工作量 |
| --- | --- | --- | --- |
| P0 | 可观测性:阶段耗时 + 实时进度 + 结果区 | 让"太快/看不到过程"可解释,后续所有页面的数据基础 | M |
| P1 | 采集可控:范围区分 + GitHub 兜底 + 不足补量 | 让采集"按需可控",解决素材不足 | M |
| P2 | 任务中心增强 + 日志规范 | 采集配置透明、日志可读 | M |
| P3 | 素材池信息架构 + 溯源 + 产出物推送 | 统一入口、输入/输出分离、可推送 | L |
| P4 | 收藏配置 + 定时采集 | 从手动采集到定时运转 | M |

---

## P0 可观测性(让"快"可解释)

### P0-1 后端阶段追踪
- 新增 `backend/app/services/stage_tracker.py`:`StageTracker` 按顺序预置阶段,记录 `status / started_at / ended_at / seconds / message / counters`;支持 `start / update / finish / skip / fail / skip_rest / note / add_source`。
- `fetch_service.run_fetch` 打点 8 阶段:配置(含关键词翻译)/ 信源 / 采集 / 标准化 / 去重 / 富化 / 评分 / 入库。
- 每个信源产出 `sources_detail[]`:`source_id、name、engine、preset、kind、seconds、fetched、filtered、duplicates、low_score、ingested、error`。
- `result` 新增:`stages`、`sources_detail`、`spec`、`progress`、`elapsed_seconds`(复用 JSONB,不加数据库列)。
- 验收:`pytest` 通过;任一采集任务 `result.stages` 每项含真实 `seconds`。

### P0-2 实时进度回写
- `jobs.py` 新增节流写入器(独立 session,0.4s 合并 + 1s 节流):运行中持续更新 `job.log` 与 `job.result.progress`;富化阶段心跳 `富化 12/69`。
- 验收:任务运行中 2s 内 `GET /api/jobs/{id}` 能看到 `progress.stage` 前进与阶段耗时。

### P0-3 采集页数据驱动
- `CollectPage` 阶段状态改为读取 `progress/stages`,删除日志正则猜测(旧任务保留兜底);每张阶段卡显示真实耗时与计数。
- 0 新素材时给出明确解释:「候选 N 条全部已在库(去重),本次未调用 LLM」。

### P0-4 结果区改版
- 统计卡(新入库 / 去重 / 过滤 / 低于门槛 / 失败源 / 总耗时)+ 信源明细表 + 入库条目表。

---

## P1 采集可控(范围 / 兜底 / 补量)

### P1-1 采集范围与 GitHub 双通道
- `FetchTriggerIn` 新增:`scopes`(资讯·论文 / GitHub)、`github_keywords`(留空沿用主词)、`github_mode`(默认 `trending_fallback`)。
- GitHub 分两通道:关键词检索(repo/skill/model)+ 热榜(trending);热榜通道豁免"关键词命中"过滤并在素材上打标,避免热榜素材被规则全部丢弃。

### P1-2 素材不足 → 自动补量 1 轮(阈值已确认:< 5 条)
- LLM 生成 4-6 个辐射词(标 `origin=expanded`、权重 0.55),仅补量轮使用,**不递归**;结果中列明扩词与实际命中。
- `backfill=auto|off` 可关;前端保留「一键再采」手动入口。

### P1-3 产出素材不足提示
- 日报/文章:`meta.shortfall`(要求 N 条 / 实际 M 条),prompt 明确禁止编造,前端显示提示。

---

## P2 任务中心 + 日志规范

### P2-1 任务中心增强
- 列表新增「配置摘要」列(方向 · 关键词 · 类型 · 窗口 · 门槛 · 产出);展开为四 Tab:概览(阶段耗时)/ 配置 / 结果(信源明细 + 入库条目)/ 日志;失败任务支持「按同样配置重跑」。

### P2-2 日志协议
- 统一 `[阶段] 消息` 格式(如 `[采集] arXiv 抓取 50 条 (1.2s)`);新增 `JobLogViewer` 组件按阶段分组着色,采集页与任务中心共用;旧日志兼容。

---

## P3 素材池信息架构

### P3-1 单入口二级结构
- 「素材池」= Tab1 素材 + Tab2 产出物(内部 Segmented:日报 / 完整文章);`/feed`、`/digests`、`/articles` 保留重定向;侧边菜单收敛为:采集工作台 / 素材池 / 信源池 / 任务中心 / 设置。

### P3-2 素材筛选增强
- `items` API 增加按引擎/来源筛选;素材 Tab 保留类型、评分、时间窗、关键词筛选。

### P3-3 引用溯源(本期做)
- 素材详情显示「被哪些日报/文章引用」;数据来自 `digests.source_item_ids` / `articles.source_item_ids` 反向索引;同时给产出物显示其素材来源。

### P3-4 产出物推送统一(完整文章也要推送)
- 泛化推送目标:`push_logs` 增加 `target_kind('digest'|'article')` 与 `target_id`,保留 `digest_id` 兼容(通过启动增量 DDL 幂等补列)。
- 新增通用接口 `POST /jobs/push`(target_kind + target_id + channel_id);日报与完整文章在素材池内均可「推送」,并展示推送记录。

---

## P4 收藏配置 + 定时采集(本期做)

### P4-1 采集配置收藏
- 仅在用户显式点击「保存为定时任务」时落库,存储于 `settings` 表(`key=collection_schedules`,JSONB),不新增表、不改变"即输即用"默认体验。
- 每条收藏包含:name、keywords、exclude_keywords、scopes、github_keywords、github_mode、lookback_hours、min_score、interval_minutes、enabled、last_run_at、last_job_id、next_run_at。

### P4-2 定时调度器
- 进程内 asyncio 调度器(lifespan 启动,60s tick):到点且无同类 fetch 任务运行中时提交采集;跳过时记录原因;服务重启后按 `next_run_at` 恢复。

### P4-3 界面
- 采集配置弹窗增加「定时」区块(保存/间隔/启停);任务中心展示定时任务列表(下次运行、立即执行、启停、最近任务)。

---

## 5. 后续(本期不做)

- 数据保留策略(素材过期清理 / 产出长期归档)。
- 更多推送渠道(飞书、企业微信、邮件等)——当前只保留 webhook/export 口子。
- 统计看板与素材质量报表。

---

# 执行记录

> 每完成一步在此追加:日期、步骤、改动、验证证据、结论。

## 2026-09-30 · 路线图文档落盘
- 改动:新增 `docs/roadmap-p0-p4.md`(本文件),记录确认项(补量阈值 <5、溯源本期、定时本期、文章推送)与执行协议。
- 验证:无代码改动。
- 结论:待执行 P0-1。

## 2026-09-30 · P0-1 / P0-2 后端阶段追踪与实时进度(完成)
- 改动:
  - 新增 `backend/app/services/stage_tracker.py`(StageTracker:8 阶段计划、状态/耗时/消息/计数、节流上报、`skip_rest`、`attach` 合并进任务结果)。
  - `backend/app/services/fetch_service.py`:打点 `配置 / 信源 / 采集 / 标准化 / 去重 / 富化 / 评分 / 入库`;每个信源产出 `sources_detail`;`result` 新增 `stages / sources_detail / spec / progress / elapsed_seconds`;评分日志加 `[评分]`、入库日志加 `[入库]` 前缀;富化阶段上报心跳 `富化 N/M 条`。
  - `backend/app/services/jobs.py`:新增 `ProgressFlusher`(独立 session、0.4s 合并),运行中持续回写 `job.log` 与 `job.result.progress`;失败任务标记出错阶段。
- 验证证据:
  - `cd backend && ./.venv/bin/python -m pytest -q` → **83 passed**(新增 `tests/test_stage_tracker.py` 6 例);`ruff check .` → All checks passed。
  - 真机采集(关键词「生物科技」,168h 窗口,独立端口 8018 运行新代码):
    - 阶段耗时:`setup 1.63s / sources 0.02s / collect 15.55s / normalize 0.08s / dedup 0.03s / enrich 104.54s / score 0.02s / store 0.04s`,总耗时 121.93s。
    - 实时进度:轮询 `GET /api/jobs/{id}` 看到 `setup → collect → enrich → store` 逐段推进,单次运行产生 45 次进度快照(此前运行中日志为空,前端只能等结束)。
    - 信源明细 11 条,含各自耗时/抓取/过滤/去重/低分/入库。
  - API 契约回归(8017 读同一 job):`result.stages` 8 条、`result.sources_detail` 11 条、`result.progress` 存在、`result.spec` 含翻译后的关键词。
- 结论:P0-1、P0-2 完成。副产物证据:本轮 `GitHub Trending` 抓取 14 条、过滤 14 条(全程未进入富化),直接印证 P1-1「GitHub 需要独立通道与热榜豁免」的必要性。

## 2026-09-30 · P0-3 / P0-4 采集页数据驱动与结果区(完成)
- 改动:`frontend/src/pages/CollectPage.tsx`
  - 阶段状态改为读取 `result.progress.stages`(运行中)或 `result.stages`(结束后),旧任务保留日志正则兜底;5 张卡片映射到后端 8 阶段。
  - 每张卡片显示真实环节耗时(如「信源 0.0s · 采集 15.6s」);运行中显示当前环节与实时消息。
  - 新增「环节耗时与信源明细」表(阶段状态/耗时/说明 + 每信源耗时与计数)。
  - 0 新素材时给出原因提示:去重跳过 N 条(未触发 LLM)/低于门槛 N 条 / 粗筛过滤 N 条 / 无候选。
  - 入库日志解析兼容新旧两种格式(`[入库] type …` 与 `入库[type] …`)。
- 验证证据:`pnpm exec tsc --noEmit` 通过;`pnpm build` 通过(✓ built in 3.89s);页面数据契约与 8017 返回的真实 job JSON 对齐(`stages` 8 条 / `sources_detail` 11 条 / `progress` 存在)。
- 未验证项(如实说明):沙箱内浏览器自动化不可用,未截图验证渲染效果;需 Master 重启后端后在浏览器确认。
- 结论:P0 完成,进入 P1-1。

## 2026-09-30 · P1-1 采集范围与 GitHub 双通道(后端完成)
- 改动:
  - `backend/app/schemas/content.py`:`FetchTriggerIn` 新增 `scopes`(info/github)、`github_keywords`、`github_mode`(strict/trending_fallback,默认兜底)、`backfill`(auto/off,默认 auto)。
  - `backend/app/services/fetch_service.py`:`CollectionSpec` 携带范围字段;`include_words` 只含主关键词,`github_include_words` 取 GitHub 专属词(未配置则沿用主词);`_in_scope` 按引擎过滤信源(info=rss/news,github=github);`_keywords_for` 让 GitHub 源使用专属词;`_is_hot_channel` 让 `GitHub Trending` 在兜底模式下豁免关键词命中过滤(未命中时相关度按 50 中性计),入库打 `热榜` 标签并在日志注明放行条数;`_load_sources` 显式单源触发不受范围限制。
  - `backend/app/services/keyword_translate.py`:`alias_keyword_entries` 支持 `channel="github"`,GitHub 专属中文词也会翻译后再检索。
- 验证证据:
  - 单测:`pytest` **88 passed**;`ruff` 通过。新增用例覆盖 scopes 解析/过滤、GitHub 专属词回退、热榜通道判定。
  - 真机(GitHub 单范围,关键词「生物科技」,backfill=off):
    - 信源只剩 `GitHub Trending`(1 个,info 源全部排除);抓取 14 条、**过滤 0 条**(改造前 14/14 被关键词过滤掉)、去重后新 10 条、入库 7 条,标签含 `热榜`。
    - `result.spec` 回显 `scopes/github_mode/backfill`,任务中心可直接展示。
- 结论:P1-1 后端完成;前端采集弹窗字段(范围/GitHub 词/兜底模式/补量开关)与素材不足提示待做(见下条后续计划)。

## 2026-09-30 · P1-2 素材不足 → 自动补量 1 轮(后端完成)
- 改动:
  - 新增 `backend/app/services/keyword_expand.py` + `backend/app/prompts/keyword_expand.md`:LLM 生成 4-6 个辐射词(带进程内缓存,结果不足则放弃补量)。
  - `fetch_service._maybe_backfill`:新入库 < 5 条且 `backfill=auto` 时,生成辐射词并用其**补采一轮**(不递归);辐射词按权重 0.55、`origin=expanded` 参与打分;补采使用独立子阶段追踪,信源明细带 `round="backfill"`;结果写入 `result.backfill`;低于期望时写入 `result.shortfall = {expected, actual}`。
  - 保护:补量已关闭 / 素材充足 / LLM 未配置 / 信源全部失败 四种情况均跳过并在阶段上写明原因;补采轮自身 `backfill=off`(结构上不可能递归)。
  - 阶段扩展为 10 个:`expand 扩词`、`backfill 补量`;`stage_tracker.py` 增加中文标签。
- 验证证据:
  - 单测:`pytest` **88 passed**(新增 `tests/test_keyword_expand.py`:解析去重/上限、缓存命中、结果不足降级);`ruff` 通过。
  - 真机(关键词「生物科技」,GitHub 单范围,backfill=auto):首轮信源抖动失败 → 触发补量;`expand` 7.88s 生成 6 个辐射词(bioinformatics / genomics / synthetic biology / protein engineering / drug discovery / CRISPR);`backfill` 41.15s 抓取 14 条、补采新增 0 条;结果含 `backfill.keywords`、子阶段耗时与 `shortfall {expected:5, actual:0}`。
- 未完成(下一步):P1-3(日报/文章 `meta.shortfall` + prompt 禁止编造)与 P1 前端(采集弹窗、素材不足提示、任务结果展示 backfill/shortfall)。

## 2026-09-30 · P1-3 产出素材不足提示 + P1 前端(完成,但需重启后端复验渲染)
- 改动:
  - `backend/app/services/digest_service.py`:新增纯函数 `compute_shortfall(news/limit/github)`;生成后把 `meta.shortfall = {news:{expected,actual}, github:{...}}` 落库并打印提示;prompt 增加「素材充足度提示」段(`$material_note`),素材或 GitHub 候选不足时明确要求「按实际数量输出、不得编造」。
  - `backend/app/services/article_service.py`:`meta.shortfall` 覆盖两种情况——可用素材 < min(6, max_sources)、正文 < 目标字数 60%;同时保留原有日志提示。
  - `frontend/src/pages/CollectPage.tsx`:采集弹窗新增「采集类型(资讯·论文 / GitHub)」「GitHub 关键词」「GitHub 采集策略(兜底 / 严格)」「素材不足时(自动补量 / 仅提示)」;结果区新增「已自动补量 / 未补量原因」「素材不足:期望 N 条,实际 M 条」提示;信源明细表对补量轮打「补量」标签。
- 验证证据:
  - `pytest` **89 passed**(新增 `test_compute_shortfall_reports_news_and_github_gaps`);`ruff` 通过;`pnpm exec tsc --noEmit` 与 `pnpm build` 通过(✓ built in 3.77s)。
  - 端到端(不调用 LLM、走降级模板,验证 meta 落库链路):生成日报 #19,`meta.shortfall = {"github": {"expected": 3, "actual": 0}}`;验证后已删除该降级日报(HTTP 204),库内现存 #16–#18 为真机 LLM 日报(news=10 / github=5)。
- 未验证项:浏览器渲染需 Master 重启 8017 后确认(沙箱无浏览器自动化权限)。
- 结论:P1 全部完成,进入 P2(任务中心增强 + 日志规范)。

## 2026-09-30 · P2 任务中心增强 + 日志规范(完成,待浏览器复验)
- 后端日志协议(统一 `[阶段] 消息`):
  - `fetch_service`:`[系统] / [配置] / [采集] / [标准化] / [去重] / [富化] / [评分] / [入库] / [扩词] / [补量] / [提示] / [完成]`;
  - `digest_service`:`[配置] / [召回] / [生成] / [提示] / [推送] / [完成]`;`article_service`:`[召回] / [过滤] / [大纲] / [写作] / [合成] / [提示] / [完成]`;
  - `keyword_translate`/`keyword_expand` 分别归入 `[配置]`/`[扩词]`;`jobs.py` 任务开始/完成/失败改为 `[系统]`。
- 前端:
  - 新增 `components/StageTable.tsx`(阶段表 + 状态元信息 + `readStagesFromJob`,`CollectPage` 改为复用)与 `components/JobLogViewer.tsx`(按 `[阶段]` 着色 + 标签过滤 + 行数统计)。
  - 新增 `components/JobDetail.tsx`:展开即「概览 / 配置 / 结果 / 日志」四 Tab;概览含阶段耗时、统计卡、素材不足与补量提示;配置含「任务参数 + 实际生效配置(含关键词翻译)」;结果含信源明细表与入库条目表,并保留原始 JSON。
  - `JobsPage.tsx` 重写:新增「采集配置」摘要列(方向 · 词数 · 类型 · 窗口 · 门槛 / 日报与文章参数)、类型与状态筛选、每行「重跑」(按同样参数重新提交)、仅在有运行中任务时轮询。
- 验证证据:`pytest` **89 passed**、`ruff` 全过、`tsc --noEmit` 通过、`pnpm build` 通过(✓ 3.91s);真机日志抽样:
  `[配置] 关键词翻译:生物科技 → biotech/biotechnology` → `[系统] 开始采集「生物科技-github」` → `[采集] GitHub Trending·repo 抓取 14 条 (0.88s)` → `[采集] GitHub Trending 热榜兜底: 14 条未命中关键词,按热榜通道放行` → `[去重] 候选 14 条, 待富化 3 条` → `[评分] 低于门槛(60)跳过: …` → `[完成] 新入库 0 条, 去重 11 条, …`。
- 未验证项:浏览器渲染与四 Tab 交互需重启后端后人工确认。
- 结论:P2 完成,进入 P3(素材池信息架构 + 溯源 + 产出物推送)。

## 2026-09-30 · P3 素材池 + 溯源 + 产出物推送(完成,待浏览器复验)
- 后端改动:
  - `app/api/routes/items.py`:列表新增 `engine`(rss/news/github,渠道映射取自 `CHANNEL_ROUTES`,单一事实来源)与 `source_id` 筛选;新增 `GET /items/lookup?ids=`(最多 50,保持入参顺序,产出物展示素材来源用);`GET /items/{id}` 新增 `references[]`(日报经 `digest_items`、文章经 `articles.source_item_ids` JSONB 包含反查,各取 20 条)。
  - `app/api/routes/digests.py`:新增 `GET /digests/{id}/items`(按 `DigestItem.position` 返回素材)。
  - `app/services/push/__init__.py`:推送目标泛化为 `send_target(target_kind=digest|article)`,`send_digest` 保留为兼容包装;article 载荷用 `topic` 作 lead、`keywords` 作 highlights。
  - `app/models/output_models.py` + `app/core/db.py`:`push_logs` 增量列 `target_kind` / `target_id` + 索引(走 `ADDITIVE_SCHEMA_DDL` 幂等 DDL,已对现库执行)。
  - `app/services/jobs.py`:`_run_push` 支持 `target_kind/target_id`,兼容旧 `digest_id`;`run_article` 透传 `push_channel_id`。
  - `app/schemas/content.py`:`PushTriggerIn`(target_kind/target_id,digest_id 兼容)、`PushLogOut` 补 target 字段、`ArticleGenerateIn.push_channel_id`、`ItemRefOut`、`ItemDetailOut.references`。
  - `app/api/routes/settings.py`:新增 `GET /settings/push-logs`(按 target_kind/target_id/channel_id 过滤,limit≤100)。
  - 新增 `tests/test_push_target.py`(引擎→渠道映射、推送参数兼容与校验、article 载荷)。
- 前端改动:
  - 新增 `pages/PoolPage.tsx`(素材池:Tabs 素材/产出物,URL 同步 `?tab=&kind=&id=`)与 `components/pool/{MaterialTab,OutputsTab,DigestPanel,ArticlePanel}.tsx`、`components/PushSection.tsx`(渠道选择 + 推送 + 推送记录)。
  - `MaterialTab`:引擎 Segmented(RSS / 资讯·论文 / GitHub)+ 内容类型 + 具体信源 + 分数 + 排序 + 搜索。
  - `DigestPanel` / `ArticlePanel`:产出物 markdown + 「素材来源(N 条)」可点开素材抽屉 + 推送区;文章生成弹窗新增「生成后推送(可选)」。
  - `ItemDetailDrawer`:新增「被引用」区(日报/文章,点击跳转素材池对应产出物)。
  - `App.tsx`:`/pool` 生效,`/feed`、`/digests`、`/articles` 重定向;`AppLayout.tsx` 菜单收敛为 5 项;旧三个页面文件改为兼容导出(未删除,待确认清理)。
  - `JobDetail.tsx` 增加 `target_kind/target_id` 参数中文标签。
- 验证证据:
  - 后端 `pytest` **94 passed**、`ruff` 全过;前端 `pnpm exec tsc --noEmit` 与 `pnpm build` 通过(✓ 4.18s)。
  - 新代码实例(8018)真机接口:engine 筛选 `news=232 / github=11`;`/items/lookup?ids=154,3,99999` 返回 2 条且含 source_name;`/items/154` references 返回 6 条日报;`/digests/18/items` 返回 10 条素材;`/items/120` references 出现 `article#3`。
  - 推送真机:临时 export 渠道 → `POST /jobs/push {target_kind: article, target_id: 3}` → `push_logs` 记录 `(article,3,success)`;旧参数 `{digest_id: 18}` → 记录 `(digest,18,success)`;验证后已清理临时渠道与测试日志(库内仅剩 1 条历史遗留日志,`target_kind=null` 为旧数据)。
- 未验证项:浏览器渲染(沙箱无浏览器自动化);**8017 进程仍运行旧代码,P3 新接口在 8017 返回 404,需重启后端**(沙箱内 kill 被拒):
  `lsof -nP -iTCP:8017 -sTCP:LISTEN -t | xargs kill; cd backend && ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8017`
- 结论:P3 完成(待 Master 重启 8017 后浏览器复验),进入 P4。

## 2026-09-30 · P4 收藏配置 + 定时采集(完成,待浏览器复验)
- 后端改动:
  - 新增 `app/services/schedules.py`:配置存 `settings[key=collection_schedules] = {"schedules":[...]}`,不新增表;字段 `name/keywords/exclude_keywords/source_ids/scopes/github_keywords/github_mode/backfill/lookback_hours/min_score/interval_minutes(5min–7天)/enabled + created_at/last_run_at/last_job_id/next_run_at/last_skip`;`next_run_at = last_run_at + interval`(未跑过则 now + interval)。
  - `CollectionScheduler`(进程内 asyncio,60s tick):到期且无同类 fetch 运行中 → 提交采集并推进 next_run_at;有同类任务运行中 → 记录 `last_skip{at,reason}` 且不推进(下个 tick 重试)。lifespan 启动,关闭时 cancel。
  - 新增 `app/api/routes/schedules.py`:`GET/POST /schedules`、`PUT/DELETE /schedules/{id}`、`POST /schedules/{id}/run`(立即执行,409=已有同类任务);新增 `app/schemas/schedule.py`。
  - 修复一个真实缺陷:`session_scope()` **不自动提交**,tick 曾因缺少显式 `commit()` 导致 next_run_at 不推进、同一配置会被反复触发;已修复并补了两个回归测试(提交成功路径必须 commit / 忙碌跳过路径必须写 last_skip 并 commit)。
- 前端改动:
  - 新增 `components/SchedulesCard.tsx`:任务中心顶部「定时采集」表(名称 + 关键词、采集配置、间隔、启停 Switch、下次运行(含上次跳过原因)、最近任务(点击展开对应任务)、立即执行、删除)。
  - `JobsPage.tsx`:接入 SchedulesCard,任务行展开改为受控 `expandedRowKeys`,推送任务摘要显示 `文章/日报 #id`。
  - `CollectPage.tsx`:采集弹窗新增「保存为定时任务」勾选 + 任务名称 + 采集间隔(1h/3h/6h/12h/天/周);勾选后本次仍立即采集,并把返回的 job.id 回填为该配置的 `last_job_id`。
- 验证证据:
  - 后端 `pytest` **102 passed**(新增 `tests/test_schedules.py` 8 例:时间计算/参数白名单/tick 提交与提交回滚回归/忙碌跳过);`ruff` 全过;前端 `tsc --noEmit` 与 `pnpm build` 通过(✓ 4.71s)。
  - 真机(8018 新代码实例):
    - CRUD:创建「探针-定时」(interval 5→10、disable→enable 均正确重算 next_run_at);未知 id 返回 404。
    - 调度器端到端:把 next_run_at 置为过去 → 60s tick 内自动提交真实采集任务 `6016af11`(name=探针-定时, status=succeeded, 83.08s, 新入库 0 条符合预期),并回写 `last_run_at=07:19:34 / next_run_at=07:29:34(+10min)`;验证后已删除探针配置与探针任务行,库内无残留。
  - 副作用说明(如实记录):验证用的 8018 实例启动时执行了 `recover_stale`,曾把你 8017 中一个进行中的采集任务(AI视频, `7553a976`)标记为 failed;该任务此后未再写回状态,现状为 failed。后续验证不再启动新实例。
- 未验证项:浏览器渲染与交互(沙箱无浏览器自动化),需重启 8017 后人工确认。
- 结论:P0–P4 全部完成(代码 + 验证),待 Master 重启后端做浏览器验收。

## 2026-09-30 · 反馈修复(4 项,完成待复验)
1. 采集页「执行中」提示过大 → 改为紧凑单行(小 Spin + 阶段 Tag + 一行实时消息),不再占用整块 Alert;流水线卡片仍是主进度展示。
2. 素材池新增「采集来源」标签 → 后端 `fetch_service.collect_meta()` 在入库时把 `collect_name`(研究方向)/`collect_keywords`(关键词)/`origin`(main|backfill)/`expanded_keywords`(辐射词)写入 `item_scores.detail`;`ItemOut` 暴露 `collect_name / collect_keywords / keyword_hits / origin`;素材卡与详情抽屉显示「采集来源:研究方向 Tag + 关键词 Tag + (命中词) + (辐射词补采)」。旧素材无方向信息,回退显示 `keyword_hits`(历史数据本就记录)。
3. 辐射词可见性 → 采集结果区新增「实际检索词」块:蓝色=用户输入词、默认=LLM 翻译词、金色=辐射词;并把补量结论(已补量 / 未补量原因 + 抓取与新增条数)压成一行文字,替代原补量 Alert。
4. 设置页 LLM「启用 / 翻译摘要」两个下拉异常 → 根因是 `Form.Item valuePropName="checked"` 配 `<Select>`(Select 绑定的是 `value` 不是 `checked`,值根本没有回填/展示),已改为 `<Switch checkedChildren/unCheckedChildren>` + tooltip。
- 验证证据:
  - 后端 `pytest` **104 passed**(新增 `collect_meta` 主轮/补量轮 2 例)、`ruff` 全过;前端 `tsc --noEmit` + `pnpm build` 通过。
  - 真机(8019,`--lifespan off` 只读实例,不触发启动钩子):`/api/items` 返回新字段(旧素材 `collect_name=null`、`keyword_hits=["AI"]` 正常兜底);随后以「来源标记验证 + RAG + GitHub 单范围 + min_score 40」真实采集,入库 3 条素材均带 `collect_name=来源标记验证 / collect_keywords=[RAG] / origin=main`,确认写入链路生效;验证后已删除这 3 条探针素材与关联行,素材池无残留。
  - 验证后已停止 8019 实例,当前无额外后端进程。
- 未验证项:浏览器渲染(需重启 8017 后人工确认)。

## 2026-09-30 · 信源扩充:高质量信源库 + 分类筛选 + 产量统计(完成,待重启 8017 后复验)
- 背景:Master 反馈「信源太少了,怎么增加高质量的信源」。策略=内置一份经过实测的推荐信源库(免维护、一键导入)+ 类别筛选批量导入 + 「近 30 天产量」列用于淘汰低产源。
- 后端改动:
  - `resources/recommended_sources.json`:**28 → 63 条**,新增 `category` 字段(`paper/lab/blog/news/cn/bio/community` 7 类);新增 arXiv 子领域(cs.CV 视觉 / cs.MA 智能体 / cs.CL 自然语言 / q-bio 生物 / stat.ML)、实验室博客(Microsoft/Apple/NVIDIA/AWS/Qwen/Google AI)、个人博客(Lilian Weng / Sebastian Raschka / Eugene Yan / Interconnects / The Gradient / Chip Huyen)、科技新闻(IEEE Spectrum / Techmeme / Wired / CNBC / Ars)、中文源(Solidot / 爱范儿 / 钛媒体 / 开源中国 / 虎嗅)、生物科技(bioRxiv / Nature Biotech / STAT / GEN)、社区(Lobsters)、GitHub 专项(近 30 天高星新库 / topic agents)。已在 description 标注「已实测可用」。
  - `app/api/routes/sources.py`:新增 `GET /sources/stats?days=30`(每源近 N 天:候选量/入库量/均分/最近入库时间)。
  - `app/schemas/config.py`:`RecommendedSource.category`;新增 `SourceStatOut(source_id, candidates, ingested, avg_score, last_item_at)`——**candidates = raw_documents 条数(含被去重),不是抓取数**,避免与「抓取」混淆。
  - 新增 `tests/test_recommended_sources.py`:key 唯一、URL 非空、tier 合法、渠道经 `route_of` 注册、类别覆盖。
- 前端改动:
  - `pages/SourcesPage.tsx`:推荐信源库弹窗新增类别筛选、「全选本类」「仅选本类 A 级」「清空」(按钮显示已选数)、已导入行禁选并标「已导入」;主表新增「近 30 天」列(候选/入库/均分,低产自动 tag)。
- 验证证据(本轮新鲜复跑):
  - 后端 `pytest` **107 passed**、`ruff` 全过;前端 `pnpm exec tsc --noEmit` 通过、`pnpm build` 通过(✓ 3.75s,产物已被 8017 静态托管:index-c05ogb6-.js)。
  - 真机(8019,`--lifespan off` 只读实例):`/api/sources/stats?days=30` 返回真实统计且含 `candidates` 字段;`/api/sources/recommended` 返回 63 条且带 category;验后已停止实例,8019 端口已释放。
  - **信源池实扩:11 → 34 条**。按推荐库已实测清单直接导入 23 条(arXiv×5、实验室×2、博客×2、新闻×4、中文×4、生物×4、社区×1、GitHub 新库×1),按 name 去重、脚本可重复执行。
  - 新导入源抽测(直连采集器,走代理):Solidot ✅ 3 条、bioRxiv ✅ 3 条、GitHub 高星新库 ✅ 25 条、Techmeme ✅ 3 条、arXiv cs.CV ✅(首次 ConnectError,重试第 2 次成功返回 2 条;代理抖动属已知现象)。
- 未验证项:8017 仍运行旧代码(沙箱内 kill 外部进程被拒),`/sources/stats` 在 8017 返回 404,「近 30 天」列需重启后端后才显示数据;重启命令:
  `lsof -nP -iTCP:8017 -sTCP:LISTEN -t | xargs kill; cd backend && ./.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8017`
- 结论:信源库扩充完成并已落库;后续可在「信源池 → 推荐信源库」按类别继续批量导入(63 条里剩余多为未实测,建议先「测试」再启用)。

## 2026-10-08 · 方案 A 实测:GitHub 清单发现信源 → 探测 → 推荐库 63 → 104
- 网络前置(影响采集,如实记录):Clash「节点选择」原为 🇯🇵Japan 04,该节点当时全超时(google/techcrunch/github 均不可达);经 Clash API 切到 🇭🇰Hong Kong 04(GUI 可一键改回)。另发现直连可通 GitHub/jsDelivr/部分 CDN,但多数海外站点需代理。验证用的探测均走 HK04。
- 实测数据(两轮,全部实探):
  - 第 1 轮 `plenaryapp/awesome-rss-feeds`(8 个分类 OPML):163 条唯一 → 161 条新候选 → **探测 OK 130 条(81%)**。
  - 第 2 轮 `fuxiaoai/tidings-rss`(588★,自附 live_check/catalog 报告)+ `vishalshar/awesome_ML_AI_RSS_feed` + `SuYxh/ai-news-aggregator`:651 条 → 去重后 635 条 → **探测 OK 586 条(92%)**;分项:AI 包 51/57、research 23/25、top200 164/174、中文 436/467、英文 128/137。
  - 失败原因分布:no entries 13、ConnectError 11、HTTP 404 8、HTTP 403 5、ConnectTimeout 4、429 3、502 2(均为源侧问题,非探测缺陷)。
  - 结论:维护型清单(tidings 有 live_check 自检)通过率(92%)显著高于宽泛老清单(plenaryapp 81% 且含大量非 AI 通用源)——**优先抄维护中的清单**。
- 产出:精选 **41 条**实测通过信源加入推荐库(`recommended_sources.json` 63 → 104,key 唯一/类别合法),分四类:
  - T1 论文·研究(11):Nature、PLOS One、eLife、MIT News AI、BAIR、Amazon Science、Quanta、Scientific American、ScienceDaily AI/全站、Phys.org。
  - T2 前沿资讯(13):Wired Science、NYT Science、BBC Science、Guardian Space、NASA、Slashdot、Engadget、CNET、The Register、Popular Science、Google Cloud Blog、Engineering at Meta、AWS News Blog。
  - T3 中文(11):新智元、集智俱乐部、我爱计算机视觉、腾讯技术工程、字节跳动技术团队、美团技术团队、哔哩哔哩技术、千问AI平台、MIT 科技评论中文热榜、差评X.PIN、小众软件(其中 9 条依赖 wechat2rss/RSSHub 第三方实例,已在 description 标注)。
  - T4 GitHub 发布 + 社区(6):openai/codex、anthropics/claude-code、google-gemini/gemini-cli、langchain-ai/langchain 的 releases.atom;HN 「AI」「LLM」关键词实时流(hnrss)。
- 验证证据:后端 `pytest` **107 passed**(含推荐库约束 3 例:key 唯一/URL 合法/渠道注册/类别覆盖)、`ruff` 全过;推荐库现 104 条,类别:paper 10 / lab 16 / news 25 / cn 20 / community 19 / blog 10 / bio 4。
- 8017 重启完成:1425 沙箱放开后 kill 生效,旧进程已停;新后端以 daemonize(双 fork+setsid)方式脱离会话运行(PID 50724),`/sources/stats` 返回 200、「近 30 天」列可用,`/sources/recommended` 返回 104 条(含新批次 category/tier),首页 200。若需手动管理:`lsof -nP -iTCP:8017 -sTCP:LISTEN -t | xargs kill` 后按原命令重启。
- 批量导入完成(Master 确认后执行):41 条经 `POST /api/sources/import-recommended` 写入信源池,**信源池 34 → 75 条**;抽测 4 条经服务端真实抓取全部通过——Nature(5 条)、新智元(5 条)、OpenAI Codex Releases(5 条)、Engineering at Meta(1 条),证明后端进程网络路径(代理/HK04)可用。
- 未做:586 条全量未导入(存于 /tmp/ra_scan/candidates2_ok.json,含 300+ 中文博客/工程号,可出第二批精选)。脚本与数据:`/tmp/ra_scan/{scan.py, scan2.py, candidates_ok.json, candidates2_ok.json, curated_batch.json}`。
- 下一步建议(供选择):① 跑一次全量采集,用「近 30 天」列验证新源产量并淘汰零产源;② 方案 B(把发现器做成产品功能:输入 GitHub 仓库/OPML → 探测 → 候选表 → 一键导入);③ 第二批精选(中文博客/工程号/AI 公司);④ 论文垂类 API 源(OpenReview/Semantic Scholar/HF Daily Papers/PubMed,需新 collector 适配)。
- Master 反馈「信源池看不到新增 41 条」:根因=表无分页但按 tier+id 排序,新源混排在 A 级中段与 B 级尾部,无任何"新增"标识;数据本身已全部入库(75 条)。已改 `SourcesPage.tsx`:① 顶部新增搜索框(名称/URL/渠道);② 名称列对 7 天内创建的源加绿色「新增」Tag;`tsc`+`pnpm build` 通过,dist 已更新(8017 直接托管 index-SjZ5F9y_.js)。刷新页面即可看到。
- 全量采集已触发:任务 `4a3d6536`「全量信源体检」(关键词 人工智能+AI、lookback 72h、min_score 60、backfill off、全信源),用于验证 75 条源的实际产量;跑完后用「近 30 天」列出体检结论。
- 全量采集阶段性快照(本地 09:48,任务仍在运行):`setup 3.5s` → `sources 0.01s(75 源)` → `collect 65.3s(抓取 906 条,4 个信源失败)` → `normalize 1.0s(候选 664,窗口外过滤 234)` → `dedup 0.03s(新增 664,重复 8)` → **`enrich 进行中 345/664`(约 6.8 条/分钟,预计总耗时 ~85 分钟)** → `score/store/expand/backfill` 待跑。
- 本轮暴露的问题(建议下期优化):① **富化是最慢环节**(单条 1 次 LLM 调用,deepseek-v4-flash 并发 3,~26s/条)——优化方向:批量富化(5-10 条/次请求)、富化前增加廉价预过滤(关键词/向量粗筛),或提高 max_concurrency;② 4 个信源抓取失败(以 arXiv 429 限流为主,多 arXiv 源并发触发);③ 36氪/腾讯技术工程/字节跳动技术团队/美团技术团队/哔哩哔哩技术 抓取 0 条——均为低频源(最近发文 9-21~9-24,超出 72h 窗口),非故障,后续体检建议 lookback 用 7 天。
- 已知缺口的下一步(方案 B/后续批):OpenReview、Semantic Scholar、PubMed/Europe PMC、HuggingFace Daily Papers、Papers with Code、Science/Cell、中文的智源社区/雷峰网等,不在本批清单覆盖范围内,需定向补。

## 2026-10-08 · 全量体检收官 + 富化批量提速 + 信源发现器(方案 B)+ 第二批精选 68 + HF Daily Papers
- ① 全量信源体检收官(任务 `4a3d6536`,75 源、关键词 人工智能+AI、72h、min_score 60):`collect 65.3s(抓 906 条,4 源失败)` → `normalize 1.0s(候选 664)` → `dedup 0.03s` → **`enrich 2921s / 48.7min(664 条,LLM 失败 1)`** → `score 0.03s(达标 468)` → `store 3.3s(入库 468)`。体检结论 → `docs/source-health-2026-10-08.md`:有产出 56 源 / 零产出 19 源 / 抓取失败 4 源(全为 arXiv API 429 限流)。
- ② 富化批量提速(痛点 664 条 × ~26s/条 = 48.7min):
  - 新增 `app/prompts/enrich_batch.md`:单次请求富化 6 条,输出 `{"items":[{index,...}]}`。
  - `app/pipeline/enrich.py` 新增 `EnrichInput` / `enrich_batch()` / `enrich_many()`:分块 batch_size=6、并发 3、缺项单条重试、单条也失败则整块不逐条打网络(直接降级)、进度回调、保持原始顺序;`enrich_item` 重构复用。
  - `fetch_service` 富化段改用 `enrich_many`;批大小可配(`RA_ENRICH_BATCH_SIZE` / `settings.general.enrich_batch_size`,默认 6)。
  - 新增 `tests/test_enrich_batch.py` 5 例(索引映射、缺项重试、批量失败转单条、整块降级、分块+进度);首跑真机捕获并修复 `fresh_rows` 解包 bug(`too many values to unpack`)。
- ③ 信源发现器(方案 B 产品化):
  - 后端 `app/services/discovery.py`:GitHub 仓库(API 找 `*.opml`/feeds.json/sources.json + README 链接)→ OPML/RSS 直判 → 网页 `<link rel=alternate>`/锚点抽取;`normalize_url/dedupe_candidates` 去重;`probe_candidates` 并发 12 探测(HTTP 200 且 ≥1 条目为可达)。
  - API:`POST /sources/discover`(候选 + 探测结果 + `already_exists` 对照信源池与推荐库)、`POST /sources/import-candidates`(URL 去重、同名自动加序号后缀)。
  - 前端:信源池新增「信源发现」按钮 → 弹窗(URL 输入 → 探测 → 表格勾选 → 批量导入;Tier 可选;不可达/已存在禁选;渠道固定 rss)。
  - GitHub Token:`backend/.env` 增加 `RA_GITHUB_TOKEN`(取自 news-agent 项目 token;`settings.github_token` + `github_token()` 兜底解析),解决匿名 API 60/h 限流。
  - 实测:OPML/Feed 直链探测通过;`github.com/plenaryapp/awesome-rss-feeds` → 40 候选 → 18 条可达(39s,含探测)。
- ④ 第二批精选 68 条(`/tmp/ra_scan/curated_batch2.json`;候选 586 → 实测可达且 60 天内活跃 460 → 精选 68):
  - arXiv 官方 RSS ×5(cs.AI/CL/LG/CV/stat.ML,`object_type=paper`,绕开 API 429)、英文 AI 实验室 ×7(DeepMind/Anthropic/NVIDIA/AWS/Google/Azure/Databricks)、中文 AI 厂商与研究院 ×9(DeepSeek/智谱/Kimi/阶跃/混元/大模型智能/机器之心SOTA/腾讯研究院/阿里研究院)、X 推文 ×20(xgo.ing:OpenAI/OpenAIDevs/Anthropic/DeepMind/MSR/HF/NVIDIA/DeepSeek/Qwen/xAI/Cursor/LangChain/Ollama/宝玉/歸藏/小互/向阳乔木/李继刚/JimFan/Tw93,`object_type=community`)、科技媒体 ×6(TechCrunch/The Verge/NYT Tech/IT之家/虎嗅/少数派)、工程团队 ×6(含 GitHub Copilot Changelog/Netflix/Cloudflare/Airbnb/Stripe/Spotify)、中文技术博客 ×12、周刊 ×3(AIGC Weekly/Last Week in AI/潮流周刊)。
  - 推荐库 105 → **173**(新增类别 `social`(X·推文)/`engineering`(工程团队),前端筛选与测试白名单同步);信源池 76 → **144**。
- ⑤ HF Daily Papers 采集器:`app/collectors/hf_papers.py`(upvotes/comments 进热度、githubRepo/organization 进 extra、`object_type=paper`);推荐库 `hf-daily-papers` 已导入信源池(id=76)。
- 验证证据:
  - 后端 `pytest` **122 passed**(新增 discovery 7 例、enrich_batch 5 例、hf_papers 3 例);`ruff check .` 全过;前端 `tsc --noEmit` + `pnpm build` 通过。
  - 真机:8017 已重启(daemonize,含新接口与新富化);`生物科技` run `b2c87d12` 全流程 118.77s(collect 96.33s → enrich 21s/2 条 → 入库 1);`AI-72h` run `026c7a98`(144 源:collect 62.53s/抓 1672 条、候选 1269、新增 834)在 enrich 90/834 时被主动中断(见下节:Master 要求控制富化条数,token 浪费场景实证)。

- 观察与下一步:144 源下 collect 明显变慢(并发 8 + 多源 20s 超时),建议后续调大 `RA_FETCH_MAX_CONCURRENCY`(12-16)并为 RSS 单独设更短超时;19 个零产源待第二轮(7 天窗口)复测后再决定清理。

## 2026-10-08 · 追加:富化条数上限 + LLM Token 可见(完成并实测)
- 背景(Master 反馈):富化/打分的资源消耗需要可见;单轮 500+ 条富化浪费资源。
- 结论:**三维打分不消耗 token**(纯算法);消耗 token 的是四处 —— 关键词翻译(setup)、富化(enrich)、辐射词(expand)、补量时二次采集的富化。
- Token 统计:
  - `app/services/llm.py`:新增 `LLMUsage`(calls / prompt / completion / total,来自 OpenAI 兼容响应 `usage` 字段)与 `usage_delta()` 阶段差值;`LLMClient` 自动累计每次调用。
  - `fetch_service`:setup / enrich / expand 三个阶段各记差值到阶段 counters(`tokens`),运行日志追加 `[Token] LLM 调用 N 次, 输入 x / 输出 y = 共 z tokens`;任务结果 `result.llm_usage` 全量快照;日报/文章任务结果同样带 `llm_usage`。
- 富化上限(默认 150,可配置):
  - `enrich_max_items`(env `RA_ENRICH_MAX_ITEMS` / 通用设置页「单轮富化上限(0 = 不限)」);`enrich_batch_size` 也开放到设置页。
  - 超限时按 **(关键词命中数 → 信源等级 S/A/B/C → 发布时间)** 预排序,仅 Top-N 走 LLM;其余走 `fallback_enrich` 零成本降级(仍参与三维打分与入库,数量统计在 `result.llm_degraded`,UI 与日志均标注「降级」)。
  - 选择理由:降级条目保留在素材池(避免被 dedup 永久跳过),token 成本与产出质量解耦,后续按需再富化。
- 前端可观测:
  - 采集工作台富化卡片:`富化条数 / Token(入出明细在报告) / 均分`,note 附「降级 n 条(超上限,未用 LLM) · Token x」。
  - 任务中心任务详情:新增「LLM Token(入/出)」与「富化降级」两项;采集报告 Markdown 增加 `富化降级` 与 `LLM Token` 行。
- 测试:新增 `tests/test_llm_usage.py`(3 例)、`tests/test_enrich_limit.py`(4 例:排序优先级/未超限全量/0=不限/Top-N 拆分);`pytest` **129 passed**,`ruff check .` 全过;前端 `tsc` + `pnpm build` 通过。
- 真机验证:重启后按默认上限 150 重跑 `人工智能+AI` 72h(144 源)【待填:任务号/各阶段耗时/Token 消耗/降级条数】。

## 2026-10-08 · 追加:采集流水线配置表单硬约束(回看 ≤48h / 门槛 ≥75 / 富化 ≤500)
- 需求(Master):采集流水线配置表单——回看窗口最长 48 小时;入库门槛最低 75 分;候选/富化最多 100 条(可在配置调整,上限 500)。
- 后端约束(单点收敛,历史存量值同样受约束):
  - `app/schemas/content.py` `FetchTriggerIn`:`lookback_hours` 1–48(默认 24)、`min_score` 75–100(默认 75)。
  - `app/schemas/schedule.py` `ScheduleIn` / `ScheduleUpdate`:同上(定时采集与临时采集同规则)。
  - `app/schemas/config.py` 通用设置:`fetch_lookback_hours` 1–48、`enrich_max_items` 1–500(原「0 = 不限」取消)。
  - `app/services/app_settings.py`:`get_general_config` 读取时收敛到边界;历史 `enrich_max_items=0` 按默认 100 处理、`>500` 收敛为 500。
  - `app/services/fetch_service.py`:`spec_from_params` 对回看/门槛做同边界收敛;`max_enrich` 默认 100、硬上限 500;`CollectionSpec.min_score` 默认 75。
- 前端:`/collect` 表单回看窗口 `max=48`、入库门槛 `min=75`(默认 75,空结果提示同步);`/settings` 默认回看窗口 `max=48`、「候选/富化上限(条)」`min=1 max=500`,tooltip 说明默认 100。
- 测试:新增 `tests/test_pipeline_limits.py`(schema 边界 + 存量值收敛)、`test_fetch_spec.py` 增补收敛用例;`pytest` **134 passed**,`ruff check .` 全过;前端 `tsc` + `pnpm build` 通过。

## 2026-10-08 · 追加:素材抽屉重排 + 产出物拆分(日报批次 / 三模式查看器)
- 背景(Master 评审):素材详情弹窗信息层级失焦;产出物需拆分日报/文章并按「日期+批次」区分同日多期;文章/日报需要源码与 JSON 出口。
- 素材抽屉(`ItemDetailDrawer.tsx`)重排:标题(2 行截断 + 原文标题副行)+ 信源/时间行 → 分数条(总分大字 + 相关/热度/时效进度条,权重 0.45/0.35/0.20)→ 摘要 → 深挖卡片 2×2 网格(未生成时为虚线 CTA 卡)→ 正文 Tabs(译文/原文)→ 被引用(最多 3 条 + 查看全部;0 条降级为一行灰字)→ 底部链接与采集方向。动作分层:唯一主按钮「生成/重新生成深挖卡片」+ 原文外链图标按钮 + `⋯` 菜单(隐藏)。
- 二轮修正(Master 评审):卡片语义从「背景 / 方法 / 结果 / 启示」(论文向,非论文常写空话)改为 **`what` / `why` / `how`(是什么 / 为什么重要 / 怎么用)**,`enrich.md` 与 `enrich_batch.md` 提示词同步;旧卡片由前端按键回退渲染。正文 Tabs 移除:流水线从不写 `translated_text`(译文 Tab 一直是空的),`raw_text` 多为摘要片段——正文收进 `⋯` → 「查看抓取正文」弹窗,深读走原文外链;抽屉主视图只留 摘要 + 速读卡片 + 被引用。
- 产出物 tab 扁平化:`PoolPage` 顶层改为「素材 / 日报 / 文章」,删除 `OutputsTab.tsx`;旧深链 `?tab=outputs&kind=digest|article&id=N` 读时映射到新 tab,`ItemDetailDrawer` 引用链接同步为 `?tab=digest|article&id=N`。
- 日报批次:生成时写入 `meta.batch = {"date", "index"}`(`digest_service.batch_window/next_batch`,本地时区自然日,当日已生成数 +1);列表以 `2026-10-08 · 第 N 批` 为主索引、LLM 标题为副行;历史数据无 `meta.batch` 时前端按同日顺序回推。
- 三模式查看器(`pool/OutputViewer.tsx`,共享给日报与文章):预览(ReactMarkdown + 780px 行宽)/ 源码(`content_md` 深色代码块 + 字符数)/ JSON(客户端 pretty-print 结构化信封;文章 `sources[].ref` 对应正文 `[n]`);选择记忆到 `localStorage`。
- 验证:`pytest` **136 passed**(新增批次窗口/计数 2 例)、`ruff check .` 全过;前端 `tsc --noEmit` + `pnpm build` 通过;真机 8017 走查素材抽屉、日报批次列表、预览/源码/JSON 三模式与旧深链映射(控制台无报错);`next_batch` 对真库实测 `2026-10-08 → 第 2 批`(当日已有 1 期)。

## 2026-10-08 · 追加:速读卡片存量旧卡修复(为何仍显示「背景 / 方法 / 结果 / 启示」)
- 现象(Master):抽屉里的速读卡片仍是「背景 / 方法 / 结果 / 启示」。根因分两层:
  - 数据层:真库 `item_contents.card` 非空 **1453 条**,其中 **796 条为旧结构**(含 `background` 等键),新结构 **0 条**——截图所见是提示词切换前入库的存量旧卡,前端按设计对旧卡回退渲染旧字段。
  - 进程层:8017 在提示词修改前启动,`app/prompts/__init__.py` 原为按名 `lru_cache`,文件改了进程内仍是旧文本,所以「重新生成」也只会继续产出旧字段。
- 修复:
  - 提示词热加载:`load_prompt` 改为按 `(mtime, size)` 缓存,编辑 `.md` 后无需重启即生效;新增 `tests/test_prompts.py`(2 例:缓存失效、占位符渲染)。
  - 单条重生成抽成 `app/services/item_enrich.py::regenerate_card`(API 路由与脚本共用,逻辑与旧路由一致:保留 keyword 信号与平台 metrics,重算三维分);新增 `is_legacy_card` 旧卡判据。
  - 新增 `scripts/refresh_legacy_cards.py`:`--limit`(默认 20,控 token)、`--ids`、`--force`、`--sleep`(默认 0.5s);单条失败回滚续跑,结尾输出成功/失败/跳过统计。
  - 前端 `ItemDetailDrawer`:旧卡在「速读卡片」标题旁显示金色「旧版」标识 + 升级提示(点「重新生成速读卡片」升级为「是什么 / 为什么重要 / 怎么用」)。
- 验证:`pytest` **138 passed**、`ruff check .` 全过;前端 `tsc --noEmit` + `pnpm build` 通过;真库复核 796 条旧卡 / 0 条新卡(JSONB `null` 657 条不计入)。存量旧卡需重启 8017(装载新提示词缓存实现)后按需重刷:先起 1-2 条冒烟,再按 `--limit` 分批。
- 真机冒烟(item 1217):脚本 → LLM 链路打通,但 **LLM 额度已用尽**(403 `insufficient_user_quota`,剩余 ¥-0.040698),单条重刷被拒;充值前「重新生成」同样会返回 502。冒烟同时暴露并修复脚本 bug:rollback 后访问过期 ORM 对象触发 `MissingGreenlet`(改为按 id 逐条 `session.get`),失败分支现在单行报错 + 汇总统计,有失败时退出码 1;条目数据未被改动(卡片与分数保持原值)。

## 2026-10-08 · 追加:深数社区推送 + 推送内容可定制(标题/作者/来源/标签)
- 配置:渠道 `#4「深数社区」`(webhook)指向 `https://club.sribd.cn/api/integrations/ai-news`,Token 取 `sribd-forum/backend/.env` 的 `SRIBD_INTEGRATIONS__AI_NEWS__TOKEN`(生产已验证可用);当日日报 `#21` 推送成功(`created: true`),重复推送 `created: false` 同条目更新;社区侧 `GET /api/feed/feed_ai_4cd12b7d5f8f0ed66f0710e2ce1a9a47` 与页面渲染均已核对。
- 需求(Master):推送时可替换标题;作者、来源可自定义;标签按日报生成时使用的素材确定。
- 后端:`PushTriggerIn` 新增可选 `title/source/author/tags`(向后兼容);新增 `app/services/push/payload.py`(`compose_payload` 优先级 override > 渠道配置 > 产出物默认;`rank_tags` 素材标签按频次汇总取 Top 6;`normalize_tags` 去空/去重/≤9 个/单标签 ≤64 字);日报标签取 `digest_items → items.tags` 频次、文章取 `keywords`;payload 新增 `tags/source/author`,模板占位符可用 `$tags/$source/$author`;`push_logs.request` 记录最终标题/来源/作者/标签。
- 前端:`PushSection` 增加「推送设置」弹窗(标题/来源/作者/标签,全部选填;标题圈占位显示当前标题,来源/作者占位显示渠道默认);`JobDetail` 参数标签补齐。
- 契约说明:深数社区集成接口只有 `source`(来源)字段、无「作者」——`author` 会随 payload 发出但社区侧暂不展示;若要社区显示作者,需另开 sribd-forum 接口扩展任务。`sourceId` 仍取 `$title`,推送时改标题等于换一条社区条目,不改标题重复推送则更新同一条。
- 验证:`tests/test_push_payload.py` 6 例 + `test_push_target.py` 适配 `_target_fields`,后端 **144 passed**(1 例本地 socket 单测因沙箱禁网跳过)、`ruff` 全过;前端 `tsc --noEmit` + `pnpm build` 通过。渠道模板需按下述 curl 更新为 `$tags/$source` 占位符(沙箱网络受限,未在真机执行)。

## 2026-10-08 · 复测:社区条目 source 仍是 research-agent、tags 只有三个
- 现象(Master):日报二次推送后,社区条目 `feed_ai_0a59a4c0a08a643c3370ce25047216ca` 的 `source` 仍是 `research-agent`,标签仍只有「AI 资讯 / AI / research-agent」。
- 根因(两层,缺一不可):
  - 数据层:渠道 `#4` 的 `payload_template` 还是旧版字面量(`"source": "research-agent"`、`"tags": ["AI","research-agent"]`),模板没引用 `$source/$tags`,自定义的来源与素材标签根本没进 payload。
  - 代码层:`WebhookPushProvider.send` 渲染模板时只用 `{title, lead, content, highlights}` 四个键作占位符上下文,`$tags/$source/$author` 一律渲染成空串(source 空 → 社区兜底为「AI 资讯采集」;tags 空串不是数组 → 社区 JSON 绑定 400)。
- 修复:`send` 改为用产出物全量字段(+`$id/$content_md` 别名)作渲染上下文;新增 `tests/test_push_webhook.py` 3 例(全字段渲染 / 字面量与缺失字段 / 无模板默认 payload)。
- 验证:`ruff` 全过;后端 **147 passed**(1 例 socket 单测因沙箱禁网报 `PermissionError`,与本改动无关)。
- 真机复测(2026-10-08 14:26,已通过):重启 8017(装载修复后代码)→ PUT 渠道 `#4` 模板改为 `{"sourceId":"$title","source":"$source","title":"$title","summary":"$lead","content":"$content","tags":"$tags"}`,config 增加 `source=sribd_forum_ai`、`author=研讯编辑部` → 复推日报 `#21`(push_logs #7,`created:false`)。
- 社区复核:条目 `feed_ai_0a59a4c0a08a643c3370ce25047216ca` 原地更新,`source=sribd_forum_ai`,标签 =「AI 资讯 / OpenAI / Claude Haiku 5.5 / Anthropic / GPT-6 / ChatGPT / Intelligent UI」(素材 Top 6),正文与 `content_md` 一致(7970 vs 7971 仅尾换行);`GET /api/feed/<code>` 200。
- 遗留:旧短标题条目 `feed_ai_4cd12b7d5f8f0ed66f0710e2ce1a9a47`(source 仍为 `research-agent`)与当前条目同题重复,需在社区后台删除;`author` 字段社区接口不接收,只记录在 `push_logs.request`。

## 2026-10-08 · 设置页 UI 迭代(脏值保存 / 渠道控制台 / 数值字段专业化)
- 需求(Master):设置页评审后按优先级落地——保存收敛到卡片右上角、测试连接移到 API Key 之后;渠道表升级为可操作、可概览的控制台;数值字段带单位与范围提示。
- 布局:LLM 配置与通用设置的「保存」移入卡片 header 右上角(脏值驱动,未改动时禁用),`测试连接` 紧跟 API Key;通用设置四字段补 `addonAfter` 单位(小时 / 条 / 条·次)、范围与推荐值常显、`恢复默认` 链接。
- 推送渠道表:启用列改 `Switch`(即改即存 PUT `{enabled}`);新增「编辑」抽屉(名称 / 类型 / URL / Token 留空保留 / 默认来源 source / 默认作者 author / 启用 / `payload_template` JSON 编辑器,含实时 JSON 校验);删除加 `Popconfirm`(配置不可恢复、日志保留);名称下方副文本展示 `host · source` 与最近一次推送时间+状态(取 `/settings/push-logs?limit=100` 按渠道取最新);空态用 `Empty + 新建渠道`。
- 顺带:API Key 的已存掩码从 label 移到字段下方 `extra`(`已保存 sk-*** · 留空则保留`);`LLMSettings` 未改动,新增前端 `PushLog` 复用已有类型(见 `frontend/src/api/types.ts`)。
- 验证:真机走查(8017)——改值出现「未保存修改」金标→保存 PUT 200 回「已同步」(LLM 配置与 api_key 未被误改);编辑抽屉 JSON 非法时拦截保存并提示,合法保存 PUT 200 且 token 保留;启用开关两次 PUT 后状态还原;删除二次确认取消后渠道仍在;`pnpm typecheck` + `pnpm build` 通过(dist 已更新)。
- 未做(评审中的 2 的剩余部分与 5):API Key 两态「更换 Key」控件、宽屏两列栅格与右栏辅助信息、关于收敛为页脚。
