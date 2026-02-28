# SQL Schema Maintenance

数据库结构统一通过本目录 SQL 维护，不再使用 Python 自动建表或结构同步脚本。

## 目录说明

- `000_extensions.sql`：扩展安装（`pgcrypto`、`vector`）
- `010_tables.sql`：建表脚本（无外键约束）
- `020_indexes.sql`：索引脚本（覆盖高频查询）
- `030_comments.sql`：表与字段注释
- `040_seed_permissions.sql`：租户角色默认权限点初始化
- `migrations/`：增量 SQL 变更目录（禁止直接修改基线 SQL）
- `baseline.lock`：基线 SQL 校验锁文件（用于 CI 防止改基线）

## 执行顺序

```bash
psql "$KD_DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/000_extensions.sql
psql "$KD_DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/010_tables.sql
psql "$KD_DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/020_indexes.sql
psql "$KD_DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/030_comments.sql
psql "$KD_DATABASE_URL" -v ON_ERROR_STOP=1 -f infra/sql/040_seed_permissions.sql

for f in infra/sql/migrations/*.sql; do
  psql "$KD_DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
```

## 命名规范

- 主键：`pk_<table>`
- 唯一约束：`uk_<table>_<biz>`
- 检查约束：`ck_<table>_<biz>`
- 索引：`ix_<table>_<columns>`

## 约束说明

- 团队规范要求不使用数据库外键，本目录 SQL 不包含任何 `FOREIGN KEY`。
- 实体关联由应用层维护，查询采用“先查主数据，再按 ID 逻辑关联”的方式。
- 数据库结构变更只允许通过本目录 SQL 文件维护，禁止通过代码自动建表/同步。
- 基线文件（`000`~`040`）禁止直接修改；若确需调整，请新增 `migrations/*.sql`。
