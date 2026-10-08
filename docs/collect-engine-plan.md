# 采集引擎与产出模式落地方案

> 目标:采集层收敛为 **3 个引擎**(不自己造轮子,直接搬现成高可用实现),产出层补齐 **两个模式**(完整文章 / 日报)。
> 确认记录:2026-09-30 Master 确认「新增 `trafilatura` 依赖」与「搬 Horizon + STORM 关键实现并在文件头标注来源」。

---

## 1. 总览

```
采集层(3 引擎) → 标准化/去重 → 富化(翻译·摘要·三维打分) → 素材池 items
                                                              ↓
                                        产出层:① 完整文章 articles  ② 日报 digests
                                                              ↓
                                                        推送口 push_channels(飞书/Webhook)
```

采集层只做「抓取 + 解析成统一 `RawItem`」;去重、翻译、摘要、打分、产出都在流水线后半段,与引擎无关。因此引擎可以很薄,数量也必须少。

---

## 2. 三个引擎(唯一允许的 `engine` 取值)

| 引擎 | 覆盖 | 子类型 `preset` | 实现来源 |
| --- | --- | --- | --- |
| `rss` | 一切标准 Feed | `feed`(RSS/Atom/JSON Feed)、`rsshub`/`rssbridge` 生成的 URL | `feedparser`(已在依赖)+ Horizon `src/scrapers/rss.py`(MIT)的映射与 `content_extractor` 开关 |
| `news` | 资讯 / 新闻 / 论文 | `google_news` / `bing_news`(检索)、`hackernews`、`arxiv` | Horizon `google_news.py` / `hackernews.py`(MIT);`bing_news.py` 自研(Bing News RSS 检索端点);arXiv 现有实现 |
| `github` | 代码与模型资源 | `trending`、`repo`(关键词搜索)、`skill`(topic 搜索)、`model`(HuggingFace) | Horizon `src/scrapers/github.py`(MIT)+ 现有 Trending HTML 解析 + `huggingface_hub` 等价 REST |

约定:
- **新增来源 = 加一条信源配置,不写代码**;新增协议才允许新增引擎(需重新确认)。
- `arxiv` 归 `news`(检索型),`github_trending` 归 `github`(榜单型),`rss` 保持不变。
- 兼容旧值:代码内维护 `channel → (engine, preset)` 映射,老信源(`arxiv` / `github` / `github_trending`)无需改数据即可运行;提供可选的一次性脚本统一为新值(不强制)。

### 2.1 正文抽取

- 依赖 `trafilatura`(Apache-2.0,6.9k★):正文抽取失败时回退到 feed 自带 `summary` / `content`。
- 信源级开关沿用 Horizon 写法:`config.content_extractor = "feed" | "trafilatura"`,默认 `feed`(省流量),资讯类建议 `trafilatura`。

### 2.2 打分口径(按 `object_type` 分套)

| 对象 | 热度 | 时效基准 |
| --- | --- | --- |
| `paper` / `news` / `tech` / `community` | 讨论量、LLM 热度 | `published_at`(缺失回退 `first_seen_at`) |
| `repo` / `skill` / `model` | stars / downloads / likes | `pushed_at` / `last_modified` |

权重按产出模式切换(见 4.2),查询侧只改 `combine_scores` 的权重入参,不改公式。

---

## 3. 许可与代码来源(抄轮子的边界)

| 项目 | 星标 | 许可 | 处置 |
| --- | --- | --- | --- |
| `Thysrael/Horizon` | 9.5k | MIT | **搬实现**(rss / google_news / hackernews / gdelt / github scrapers),文件头标注来源 |
| `stanford-oval/storm` | 32k | MIT | **搬流程设计**(多视角提问 → 大纲 → 逐节写作)用于完整文章模式 |
| `adbar/trafilatura` | 6.9k | Apache-2.0 | 作为依赖引入 |
| `ourongxing/newsnow` | 22k | MIT | 备用:35 个中文热榜源定义(本期不启用) |
| `RSS-Bridge` | 9.2k | Unlicense | 备用:无 feed 站点的桥接逻辑 |
| `sansan0/TrendRadar` | 63k | GPL-3.0 | 仅借鉴设计,**不搬代码** |
| `DIYgod/RSSHub` | 46k | AGPL-3.0 | 仅作为外部 Feed URL 使用,**不搬代码** |
| `PyGithub` | 7.8k | LGPL-3.0 | 不引入,改用 `httpx` 薄封装 |

- 统一在 `THIRD_PARTY_NOTICES.md` 登记来源与许可;搬来的文件头部注释:`Adapted from <repo> (<license>) — <原路径>`。

---

## 4. 产出层

### 4.1 模式一:完整文章 `articles`

- 输入:研究方向(可选)、关键词、回看窗口、素材上限、目标字数(默认 1800)。
- 流程(搬 STORM 的流水线形状,简化版):
  1. 召回:按「相关度 × 热度 × 时效」取 top-K(K ≈ 3× 目标素材数),范围 = 关键词命中 + 时间窗;
  2. 过滤:LLM 逐条判定「是否切题、是否有实质信息」,丢弃公关稿/重复事件,事件归并;
  3. 选题:LLM 给出 1 个主线角度 + 3-5 节大纲;
  4. 写作:逐节生成(每节必须引用 `source_ids`,不得编造事实);
  5. 合成:去掉重复表述,统一术语,补「参考来源」链接列表。
- 落地:新表 `articles`(title / keywords / content_md / source_item_ids / model / status / created_at),前端新增「文章」页(列表 + Markdown 详情 + 复制/导出)。
- 入口:`POST /api/articles/generate`(创建 `kind=article` 任务),`GET /api/articles`。

### 4.2 模式二:日报 `digests`

- 输入:`scope = global | topic`、`keywords`(topic 时必填)、回看窗口、`news_count = 10`、`github_count = 3~5`。
- 召回与排序:
  - `global`(默认,无需方向/关键词):权重 `热度 0.6 + 时效 0.4`,相关度权重置 0 → 「最新最热」;排除 `repo/skill/model`(它们走 GitHub 板块)。
  - `topic`:权重 `相关度 0.5 + 热度 0.3 + 时效 0.2`,相关度低于阈值直接丢弃。
- 版式(固定两节,Markdown):
  ```
  # 研讯日报 · YYYY-MM-DD
  > 60-100 字导读

  ## 今日资讯

  ### 1. 摘要标题
  摘要正文

  - [原始标题](原文链接)

  ...

  ## GitHub 今日推荐

  ### 1. owner/repo
  标签:Python · ★1.2k · 今日 +123

  仓库介绍

  - [owner/repo](仓库地址)
  ```
  - 版式约束:`## 今日资讯` / `## GitHub 今日推荐` 两个二级分节标题固定;资讯块用 `### N. 标题` + 正文 + `- [原始标题](链接)`;GitHub 块用 `### N. owner/repo` + `标签:` 行 + 介绍 + `- [owner/repo](地址)`。
  - 正文长度:资讯 `summary` **250-500 字符**、GitHub `blurb` **100-200 字符**(标点计入、不计空白)。提示词约束 + 生成后 `_fit_lengths` 兜底:超长按句末截断,偏短用 `prompts/digest_repair.md` 依素材补写一次。
- 落地:`digests` 表加 `meta` JSON(scope / counts / 引擎分布),`DigestItem` 记录素材来源;渲染器 `_render_markdown` 拆成「板块化」实现。
- 入口:现有 `POST /api/digests/generate`,参数扩展;推送沿用 `push_channels`(飞书未做,口子已留)。

---

## 5. 分阶段执行与验收

| 阶段 | 内容 | 验收标准 |
| --- | --- | --- |
| P1 引擎层 | 引入 `trafilatura`;引擎注册表(`engine`/`preset` 映射);搬 Horizon 的 `google_news` / `hackernews` / `github(repo/skill)` 实现;补自研 `bing_news`(国内可用检索端点);补充推荐信源 | ✅ 2026-09-30 落地:四类引擎 preset 均实测抓到数据(含 `bing_news` 9 条);关键词「生物科技」全链路采集入库;`pytest` 59 passed + `ruff` 通过 |
| P2 日报版式 | `scope` 双模式、固定 10 + 3-5 版式、链接与 GitHub 板块 | ✅ 2026-09-30 落地:全局与定向各实测一份(真实 LLM 生成),GitHub 板块取到当日 +4758★ 等实时数据 |
| P3 完整文章 | `articles` 表与服务、五步流水线、前端文章页 | ✅ 2026-09-30 落地:两篇真实长文(3087 字 / 2061 字),逐节引用 + 本地参考文献,前端可查看/复制 |
| P4 推送(可选) | 飞书/Webhook 出口接入 | 日报一键推送到指定通道 |

> P2 条数口径:日报正文条数由「LLM 写几条算几条」改为确定性对齐 —— LLM 少写时用排名靠前的未引用素材补齐到 `min(目标条数, 可用素材数)`(`_backfill_items`,补齐条目的正文仍会走长度整形),并把「LLM 输出 / 丢弃 / 补齐」写进任务日志;`digests.meta.news_count` = 正文资讯条数,`meta.news_materials` = 引用素材数(两者此前混用,列表页显示的是素材数,已改为条数)。

> P2/P4 打磨补充(2026-09-30 晚):日报正文长度改为硬要求(资讯 250-500 / GitHub 100-200 字符),生成后过一次 `_fit_lengths`(超长句末截断 + 偏短一次 LLM 补写);中文关键词在采集、日报、完整文章三处都会先 LLM 翻英文再检索;GitHub 检索式改用 `in:name,description,topics` 并剔除中文词(实测 `in:readme` + 中文词会返回完全无关的热门仓库);另外 OR 组**不能套括号** —— `(biotech OR biotechnology) in:...` 只有 2 条,`biotech OR biotechnology in:...` 有 11 条(2026-09-30 实测)。

> P2 落地补充:GitHub 板块取数在 `backend/app/services/github_today.py` —— Trending 日榜(3 次重试)→ 关键词命中不足 3 条时按「近 45 天新锐(星速)」「近 3 天活跃(总星)」检索补位 → 全局兜底用「近 45 天新锐高星」;`digests.meta` 记录 scope / counts / github 明细,老库启动时自动补列(`app/core/db.py` 的 `ADDITIVE_SCHEMA_DDL`)。

每阶段结束跑:`cd backend && ./.venv/bin/python -m pytest -q && ./.venv/bin/ruff check .`;涉及前端时补 `cd frontend && pnpm exec tsc --noEmit && pnpm build`。

---

## 6. 风险与对策

| 风险 | 对策 |
| --- | --- |
| Google News / GDELT 可能限流或地域受限 | 引擎内重试 + 失败隔离(单源失败不影响整体),保留 `raw_documents` |
| 检索端点握手抖动(代理/出口 TLS EOF,`httpx.ConnectError` 常带空 message) | 统一 `collectors.base.get_with_retries`(TransportError 指数退避重试 3 次)+ `describe_error` 补类型名,避免日志只剩 `unknown error` |
| Bing News 检索加了引号会返回 0 条 | `bing_query` 明确不加引号(注释里写了实测结论),词间 OR |
| GitHub 未鉴权 10 次/分 | 支持 `RA_GITHUB_TOKEN`;无 token 时降低检索频率与关键词数 |
| `trafilatura` 抽取失败 | 回退 feed 自带正文;记录抽取失败计数 |
| 长文生成幻觉 | 逐节强制 `source_ids` 引用,渲染时统一附「参考来源」;无来源的事实不落文 |
| 许可证混用 | 仅搬 MIT/Apache/Unlicense,登记 `THIRD_PARTY_NOTICES.md`,GPL/AGPL 只借鉴不搬码 |
