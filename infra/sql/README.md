# 数据库初始化脚本

## 快速开始

### 方式一：使用合并后的单文件（推荐）

```bash
# 初始化数据库
psql -U postgres -d tkp_api -f init_all.sql
```

### 方式二：使用 Docker

```bash
# 通过 docker-compose 自动初始化
docker-compose up -d postgres

# 数据库会自动执行 /docker-entrypoint-initdb.d 中的脚本
```

### 方式三：分步执行

```bash
# 1. 扩展
psql -U postgres -d tkp_api -f 000_extensions.sql

# 2. 表结构
psql -U postgres -d tkp_api -f 010_tables.sql

# 3. 迁移（按顺序）
for f in migrations/*.sql; do
  psql -U postgres -d tkp_api -f "$f"
done

# 4. 索引
psql -U postgres -d tkp_api -f 020_indexes.sql

# 5. 注释
psql -U postgres -d tkp_api -f 030_comments.sql

# 6. 初始数据
psql -U postgres -d tkp_api -f 040_seed_permissions.sql
```

## 文件说明

### 核心文件

- **`init_all.sql`** - 合并后的完整初始化脚本（1606行，推荐使用）
- **`init_database.sql`** - 使用 `\i` 命令引用其他文件的脚本

### 分离文件

- `000_extensions.sql` - PostgreSQL 扩展（pgcrypto, vector）
- `010_tables.sql` - 所有表结构定义
- `020_indexes.sql` - 所有索引定义
- `030_comments.sql` - 表和列的注释
- `040_seed_permissions.sql` - 初始权限数据

### 迁移文件

`migrations/` 目录包含11个数据库迁移文件

## 重置数据库

```bash
# 删除数据库
dropdb -U postgres tkp_api

# 重新创建
createdb -U postgres tkp_api

# 初始化
psql -U postgres -d tkp_api -f init_all.sql
```

## 验证

```bash
# 检查表
psql -U postgres -d tkp_api -c "\dt"

# 检查扩展
psql -U postgres -d tkp_api -c "\dx"

# 检查索引
psql -U postgres -d tkp_api -c "\di"
```

## 注意事项

1. **幂等性**：所有脚本都使用 `IF NOT EXISTS` 或 `IF EXISTS`，可以安全地重复执行
2. **顺序**：迁移文件按时间戳命名，必须按顺序执行
3. **权限**：需要数据库超级用户权限来创建扩展
4. **备份**：生产环境执行前请先备份数据库
