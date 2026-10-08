# 贡献指南

感谢参与 research-agent!欢迎提交 Issue、Pull Request 或补充文档。

## 开发环境

```bash
# 数据库(本地开发用 Docker 起一个 PostgreSQL 即可)
docker run -d --name research-agent-pg -p 25432:5432 \
  -e POSTGRES_USER=agent -e POSTGRES_PASSWORD=agent -e POSTGRES_DB=research_agent \
  postgres:16-alpine

# 后端(Python ≥ 3.12 + uv)
cd backend && cp .env.example .env && uv sync
uv run uvicorn app.main:app --host 127.0.0.1 --port 8017

# 前端(Node ≥ 20 + pnpm;开发模式把 /api 代理到 8017)
cd frontend && pnpm install && pnpm dev
```

## 提交规范

提交信息统一为 `<type>(<YYYYMMDD>): <summary>`:

- `type` ∈ `feat` / `fix` / `refactor` / `docs` / `test` / `chore`
- `summary` 用英文动词开头,不超过 50 个字符
- 例:`fix(20261008): keep channel token when editing`

## 代码规范

- **后端**:`ruff`(line-length=100,select `E,F,I,UP,B`);行为变更请补 `pytest` 用例,新增模块优先写成不联网的纯函数以便测试。
- **前端**:沿用现有 Ant Design 组件与中文文案,不引入新的 UI 库;提交前 `pnpm typecheck` 必须通过。
- **LLM 相关**:任何依赖 LLM 的功能都要保留未配置 / 调用失败时的降级分支,并在任务日志中标注。
- **安全**:不要提交 `.env`、Token、Cookie 等凭据;数据库查询参数化,不拼接不可信输入。

## 提交 PR 前

```bash
cd backend && uv run ruff check . && uv run pytest -q
cd frontend && pnpm typecheck && pnpm build
```

PR 描述请说明:变更动机、影响范围、验证方式(命令 / 截图)。

## 扩展点

| 想做的事 | 落地位置 |
| --- | --- |
| 新增采集源 | `backend/app/collectors/` 下新增 collector 并在 `__init__.py` 注册 |
| 新增推送渠道 | `backend/app/services/push/` 下实现 `PushProvider` 并注册,无需改核心 |
| 调整提示词 | `backend/app/prompts/*.md`(按 `(mtime, size)` 热加载,改完即生效) |
| 调整打分权重 | `backend/app/pipeline/scoring.py`(相关 / 热度 / 时效) |
| 数据模型 | `backend/app/models/`;当前用 `RA_AUTO_CREATE_TABLES` 建表,尚未接入迁移 |

## 行为准则

参与本项目即表示同意保持友善、专业的交流方式:就事论事、尊重不同经验水平的贡献者。
