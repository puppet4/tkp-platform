# TKP Platform Monorepo

Multi-service repository for a multi-tenant knowledge platform.

Code reading entry:
- `docs/code-guide.md`

## Layout

```text
services/
  api/
    src/tkp_api/
    pyproject.toml
  worker/
    src/tkp_worker/
    pyproject.toml
  rag/
    src/tkp_rag/
    pyproject.toml
knowledge/
docs/
```

## Workspace setup

```bash
uv sync
```

## Database initialization (SQL only)

数据库结构通过 `infra/sql` 维护，不使用代码自动建表。

```bash
psql "$KD_DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/000_extensions.sql
psql "$KD_DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/010_tables.sql
psql "$KD_DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/020_indexes.sql
psql "$KD_DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/030_comments.sql
psql "$KD_DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/040_seed_permissions.sql
```

治理检查（本地/CI 通用）：

```bash
bash scripts/check_sql_governance.sh
```

规则摘要：
- 禁止 `create_all` / `metadata.create_all` 之类代码建表。
- 禁止代码式 schema 同步脚本（如 `create_all.py`、`sync_comments.py`）。
- 禁止 SQL 中出现外键定义（`FOREIGN KEY` / `REFERENCES`）。

## API service

Start API:

```bash
PYTHONPATH=services/api/src uv run --project services/api uvicorn tkp_api.main:app --reload --port 8000
```

## Worker service

```bash
PYTHONPATH=services/worker/src uv run --project services/worker python -m tkp_worker.main
```

## RAG service

```bash
PYTHONPATH=services/rag/src uv run --project services/rag uvicorn tkp_rag.app:app --reload --port 8010
```

## Environment

Copy `.env.example` to `.env` in repo root and update values.

Required vars for API currently:

- `KD_DATABASE_URL`
- `KD_API_PREFIX`
- `KD_AUTH_MODE`
- `KD_AUTH_JWT_ALGORITHMS`
- `KD_AUTH_JWT_SECRET` (or `KD_AUTH_JWKS_URL`)
- `KD_STORAGE_ROOT`

Auth and tenancy headers:

- `Authorization: Bearer <jwt>`
- `X-Tenant-Id: <tenant_uuid>`
- `Idempotency-Key: <client_key>` (optional, for upload/reindex write idempotency)
