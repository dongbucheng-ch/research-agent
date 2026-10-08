# AGENTS.md — research-agent
|Stack:backend=Python3.12+FastAPI+SQLAlchemy2(async)+APScheduler|frontend=React18+TS+Vite+AntD5(构建产物由后端托管)|db=PostgreSQL。
|Run Backend:`cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8017`|前端开发:`cd frontend && pnpm dev`(代理 /api → 8017)|生产形态:访问 `http://127.0.0.1:8017/`。
|Verify:`cd backend && uv run pytest -q && uv run ruff check .`|前端:`cd frontend && pnpm build`(含 tsc 类型检查)|改动后至少跑对应一侧的最小验证集。
|Database:默认复用共享 `shared-pgvector`(127.0.0.1:25432)的 `research_agent` 库|连接用 `RA_DB_*` 分字段配置,禁止拼回单条 DSN(密码含 `@!` 等字符会转义出错)|凭据只走 `backend/.env`,不入库不入日志。
|Schema:建表当前由 `RA_AUTO_CREATE_TABLES` + `Base.metadata.create_all` 完成|尚未引入 alembic|改表结构或共享 contract/schema 前先确认并补回归测试。
|Architecture:collectors(采集)→ pipeline/text(去重)→ pipeline/enrich(LLM 富化,含降级)→ pipeline/scoring(三维打分)→ services/fetch_service(编排)|新增平台推送只加 `app/services/push/` 的 provider 并注册,不动核心。
|Config:`app/services/app_settings.py` 存数据库配置(LLM、通用参数),`app/core/config.py` 读环境变量|新增设置项同时改后端 schema 与前端设置页。
|LLM:OpenAI 兼容接口,未配置时全流程降级(不翻译、不 LLM 摘要/打分),任务日志标注「降级模式」|改动涉及 LLM 输出时保留降级分支。
|Proxy:shell 有 `all_proxy/http_proxy/https_proxy`,本地 curl/健康检查加 `--noproxy '*'`|httpx 已装 `socksio`;本地 webhook 联调注意代理绕过。
|Style:ruff line-length=100(select E,F,I,UP,B)|前端沿用现有 AntD 组件与中文文案,不要引入新 UI 库。
