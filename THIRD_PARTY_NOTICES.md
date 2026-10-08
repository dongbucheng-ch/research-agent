# 第三方代码与许可声明

本项目以 MIT 许可开源,以下第三方项目以「借鉴实现 / 作为依赖」的方式被引用,均保留原许可与版权声明。
参考原则:只搬 **MIT / Apache-2.0 / Unlicense** 的代码;GPL / AGPL 项目仅借鉴设计,不复制源码。

| 项目 | 许可 | 使用方式 | 位置 |
| --- | --- | --- | --- |
| [Thysrael/Horizon](https://github.com/Thysrael/Horizon) | MIT | 搬实现:`src/scrapers/rss.py` / `google_news.py` / `hackernews.py` / `github.py` 的采集与解析做法(源声明、时间窗算子、并发拉详情、限流与失败隔离) | `backend/app/collectors/google_news.py`、`hackernews.py`、`github_search.py`、`__init__.py`(注册表设计) |
| [adbar/trafilatura](https://github.com/adbar/trafilatura) | Apache-2.0 | 作为依赖:网页正文抽取 | `backend/pyproject.toml` |
| news-agent(本地参考项目) | MIT | 借鉴实现:GitHub Trending HTML 解析(`article.Box-row` → 今日新增 star) | `backend/app/collectors/github_trending.py` |
| [stanford-oval/storm](https://github.com/stanford-oval/storm) | MIT | 借鉴流程设计:过滤 → 大纲 → 逐节写作 → 合成(用于「完整文章」模式) | `backend/app/services/article_service.py`、`backend/app/prompts/article_*.md` |
| [ourongxing/newsnow](https://github.com/ourongxing/newsnow) | MIT | 备用:中文热榜聚合源定义(本期未启用) | — |
| [RSS-Bridge/rss-bridge](https://github.com/RSS-Bridge/rss-bridge) | Unlicense | 备用:无 Feed 站点的桥接逻辑(本期未启用) | — |

仅借鉴设计、未复制代码:

| 项目 | 许可 | 说明 |
| --- | --- | --- |
| [sansan0/TrendRadar](https://github.com/sansan0/TrendRadar) | GPL-3.0 | 多平台热榜聚合思路(单一聚合 API 覆盖多平台) |
| [DIYgod/RSSHub](https://github.com/DIYgod/RSSHub) | AGPL-3.0 | 作为外部 Feed URL 使用,不复制源码 |
| [PyGithub](https://github.com/PyGithub/PyGithub) | LGPL-3.0 | 未引入,改用 `httpx` 薄封装调用 GitHub REST |
