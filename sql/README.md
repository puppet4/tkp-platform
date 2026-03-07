# 数据库初始化脚本

## 快速开始

### 方式一：使用统一初始化脚本（推荐）

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

## 文件说明

### 核心文件

- **`init_all.sql`** - 统一的完整初始化脚本（1606行）
  - 包含所有扩展、表结构、索引、注释和初始数据
  - 幂等性设计，可安全重复执行

- **`baseline.lock`** - 基线校验文件（用于 CI）

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

1. **幂等性**：脚本使用 `IF NOT EXISTS` 或 `IF EXISTS`，可以安全地重复执行
2. **权限**：需要数据库超级用户权限来创建扩展
3. **备份**：生产环境执行前请先备份数据库
4. **结构变更**：不要直接修改 `init_all.sql`，应该通过迁移脚本管理
