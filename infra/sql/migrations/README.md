# Incremental SQL Migrations

本目录用于维护增量数据库变更，禁止直接修改 `infra/sql/010_tables.sql` 等基线 SQL。

## 文件命名

- 格式：`YYYYMMDD_HHMMSS_description.sql`
- 示例：`20260301_093000_add_user_avatar.sql`

## 编写规范

- 每个 migration 必须包含：
  - `BEGIN;`
  - 变更 SQL
  - `COMMIT;`
- 禁止外键（`FOREIGN KEY` / `REFERENCES`）。
- 变更必须可读、可审计，必要时增加回滚说明注释。

## 执行顺序

按文件名字典序依次执行：

```bash
for f in infra/sql/migrations/*.sql; do
  psql "$KD_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
```
