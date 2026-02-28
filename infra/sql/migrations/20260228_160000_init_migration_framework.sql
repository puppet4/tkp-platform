BEGIN;

-- 初始化增量迁移框架（占位 migration，便于建立执行流水线）。
-- 后续结构变更请新增新的 migration 文件，不要直接修改基线 SQL。
SELECT 1;

COMMIT;
