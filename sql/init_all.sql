-- 基础扩展：UUID 生成 + 向量类型。
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- 表结构
-- ============================================================================

-- 说明：
-- 1) 严格遵循“无外键”规范，仅保留主键、唯一约束、检查约束。
-- 2) 所有关联关系由应用层通过 UUID 字段维护。

CREATE TABLE IF NOT EXISTS tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(128) NOT NULL,
    slug VARCHAR(64) NOT NULL,
    isolation_level VARCHAR(32) NOT NULL DEFAULT 'shared',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_tenants_status CHECK (status IN ('active', 'suspended', 'deleted'))
);

-- 部分唯一索引：只对非删除状态生效
CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_slug_active_unique ON tenants (slug) WHERE status != 'deleted';

CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email VARCHAR(256) NOT NULL,
    display_name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    auth_provider VARCHAR(64) NOT NULL DEFAULT 'jwt',
    external_subject VARCHAR(256) NOT NULL,
    last_login_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_users_email UNIQUE (email),
    CONSTRAINT uk_user_external_identity UNIQUE (auth_provider, external_subject)
);

CREATE TABLE IF NOT EXISTS tenant_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'member',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_tenant_membership UNIQUE (tenant_id, user_id),
    CONSTRAINT ck_tenant_memberships_role CHECK (role IN ('owner', 'admin', 'member', 'viewer')),
    CONSTRAINT ck_tenant_memberships_status CHECK (status IN ('active', 'invited', 'disabled'))
);

CREATE TABLE IF NOT EXISTS workspaces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    name VARCHAR(128) NOT NULL,
    slug VARCHAR(64) NOT NULL,
    description TEXT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_workspaces_status CHECK (status IN ('active', 'archived'))
);

-- 部分唯一索引：只对非归档状态生效
CREATE UNIQUE INDEX IF NOT EXISTS idx_workspace_slug_active_unique ON workspaces (tenant_id, slug) WHERE status != 'archived';

CREATE TABLE IF NOT EXISTS workspace_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    user_id UUID NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'ws_viewer',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_workspace_membership UNIQUE (workspace_id, user_id),
    CONSTRAINT ck_workspace_memberships_role CHECK (role IN ('ws_owner', 'ws_editor', 'ws_viewer')),
    CONSTRAINT ck_workspace_memberships_status CHECK (status IN ('active', 'invited', 'disabled'))
);

CREATE TABLE IF NOT EXISTS knowledge_bases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    name VARCHAR(128) NOT NULL,
    description TEXT NULL,
    embedding_model VARCHAR(128) NOT NULL,
    retrieval_strategy JSONB NOT NULL DEFAULT '{}'::JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_by UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_knowledge_bases_status CHECK (status IN ('active', 'archived'))
);

-- 部分唯一索引：只对非归档状态生效
CREATE UNIQUE INDEX IF NOT EXISTS idx_kb_name_active_unique ON knowledge_bases (tenant_id, workspace_id, name) WHERE status != 'archived';

CREATE TABLE IF NOT EXISTS kb_memberships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    kb_id UUID NOT NULL,
    user_id UUID NOT NULL,
    role VARCHAR(32) NOT NULL DEFAULT 'kb_viewer',
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_kb_membership UNIQUE (kb_id, user_id),
    CONSTRAINT ck_kb_memberships_role CHECK (role IN ('kb_owner', 'kb_editor', 'kb_viewer')),
    CONSTRAINT ck_kb_memberships_status CHECK (status IN ('active', 'invited', 'disabled'))
);

CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    kb_id UUID NOT NULL,
    title VARCHAR(256) NOT NULL,
    source_type VARCHAR(32) NOT NULL DEFAULT 'upload',
    source_uri TEXT NULL,
    current_version INTEGER NOT NULL DEFAULT 1,
    status VARCHAR(32) NOT NULL DEFAULT 'pending',
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_by UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_documents_source_type CHECK (source_type IN ('upload', 'url', 'notion', 'git')),
    CONSTRAINT ck_documents_status CHECK (status IN ('pending', 'processing', 'ready', 'failed', 'deleted')),
    CONSTRAINT ck_documents_current_version CHECK (current_version > 0)
);

CREATE TABLE IF NOT EXISTS document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    document_id UUID NOT NULL,
    version INTEGER NOT NULL,
    object_key TEXT NULL,
    parser_type VARCHAR(64) NULL,
    parse_status VARCHAR(32) NOT NULL DEFAULT 'pending',
    checksum VARCHAR(128) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_document_version UNIQUE (document_id, version),
    CONSTRAINT ck_document_versions_parse_status CHECK (parse_status IN ('pending', 'success', 'failed')),
    CONSTRAINT ck_document_versions_version CHECK (version > 0)
);

CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    kb_id UUID NOT NULL,
    document_id UUID NOT NULL,
    document_version_id UUID NOT NULL,
    chunk_no INTEGER NOT NULL,
    parent_chunk_id UUID NULL,
    title_path TEXT NULL,
    content TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_chunk_no UNIQUE (document_version_id, chunk_no),
    CONSTRAINT ck_document_chunks_chunk_no CHECK (chunk_no >= 0),
    CONSTRAINT ck_document_chunks_token_count CHECK (token_count >= 0)
);

CREATE TABLE IF NOT EXISTS chunk_embeddings (
    chunk_id UUID PRIMARY KEY,
    tenant_id UUID NOT NULL,
    kb_id UUID NOT NULL,
    embedding_model VARCHAR(128) NOT NULL,
    vector VECTOR(1536) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ingestion_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    workspace_id UUID NOT NULL,
    kb_id UUID NOT NULL,
    document_id UUID NOT NULL,
    document_version_id UUID NOT NULL,
    idempotency_key VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    stage VARCHAR(64) NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 5,
    next_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    locked_at TIMESTAMPTZ NULL,
    locked_by VARCHAR(128) NULL,
    heartbeat_at TIMESTAMPTZ NULL,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    error TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_ingestion_job_idempotency UNIQUE (tenant_id, idempotency_key),
    CONSTRAINT ck_ingestion_jobs_status CHECK (status IN ('queued', 'processing', 'retrying', 'completed', 'dead_letter')),
    CONSTRAINT ck_ingestion_jobs_progress CHECK (progress >= 0 AND progress <= 100),
    CONSTRAINT ck_ingestion_jobs_attempt_count CHECK (attempt_count >= 0),
    CONSTRAINT ck_ingestion_jobs_max_attempts CHECK (max_attempts > 0)
);

CREATE TABLE IF NOT EXISTS retrieval_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    query_text TEXT NOT NULL,
    kb_ids JSONB NOT NULL DEFAULT '[]'::JSONB,
    top_k INTEGER NOT NULL DEFAULT 8,
    filter_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    result_chunks JSONB NOT NULL DEFAULT '[]'::JSONB,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_retrieval_logs_top_k CHECK (top_k > 0),
    CONSTRAINT ck_retrieval_logs_latency_ms CHECK (latency_ms >= 0)
);

CREATE TABLE IF NOT EXISTS user_credentials (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    password_hash VARCHAR(256) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    password_updated_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_user_credential_user UNIQUE (user_id)
);

CREATE TABLE IF NOT EXISTS user_mfa_totp (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    secret_base32 VARCHAR(128) NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    verified_at TIMESTAMPTZ NULL,
    backup_codes_hashes TEXT NOT NULL DEFAULT '[]',
    last_used_counter INTEGER NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_user_mfa_totp_user UNIQUE (user_id)
);

CREATE TABLE IF NOT EXISTS tenant_role_permissions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    role VARCHAR(32) NOT NULL,
    permission_code VARCHAR(128) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_tenant_role_permission UNIQUE (tenant_id, role, permission_code)
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    actor_user_id UUID NULL,
    action VARCHAR(128) NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id VARCHAR(128) NOT NULL,
    before_json JSONB NULL,
    after_json JSONB NULL,
    ip INET NULL,
    user_agent TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    title VARCHAR(256) NOT NULL,
    kb_scope JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    conversation_id UUID NOT NULL,
    role VARCHAR(16) NOT NULL DEFAULT 'user',
    content TEXT NOT NULL,
    citations JSONB NOT NULL DEFAULT '[]'::JSONB,
    usage JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_messages_role CHECK (role IN ('user', 'assistant', 'tool', 'system'))
);

CREATE TABLE IF NOT EXISTS agent_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    conversation_id UUID NULL,
    plan_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    tool_calls JSONB NOT NULL DEFAULT '[]'::JSONB,
    status VARCHAR(32) NOT NULL DEFAULT 'queued',
    cost NUMERIC(18, 6) NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ NULL,
    finished_at TIMESTAMPTZ NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_agent_runs_status CHECK (status IN ('queued', 'running', 'success', 'failed', 'blocked', 'canceled')),
    CONSTRAINT ck_agent_runs_cost CHECK (cost >= 0)
);

-- ============================================================================
-- 迁移
-- ============================================================================

-- 来自: migrations/20250306_210000_add_user_feedback_tables.sql
-- 用户反馈和回放表迁移
-- 创建时间: 2025-03-06

-- 用户反馈表
CREATE TABLE IF NOT EXISTS user_feedbacks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    user_id UUID NOT NULL,
    conversation_id UUID,
    message_id UUID,
    retrieval_log_id UUID,
    feedback_type VARCHAR(50) NOT NULL,
    feedback_value VARCHAR(255),
    comment TEXT,
    tags JSONB,
    snapshot JSONB,
    processed BOOLEAN DEFAULT FALSE NOT NULL,
    processed_at TIMESTAMP WITH TIME ZONE,
    processing_result JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- 索引
CREATE INDEX idx_user_feedbacks_tenant_id ON user_feedbacks(tenant_id);
CREATE INDEX idx_user_feedbacks_user_id ON user_feedbacks(user_id);
CREATE INDEX idx_user_feedbacks_conversation_id ON user_feedbacks(conversation_id);
CREATE INDEX idx_user_feedbacks_message_id ON user_feedbacks(message_id);
CREATE INDEX idx_user_feedbacks_retrieval_log_id ON user_feedbacks(retrieval_log_id);
CREATE INDEX idx_user_feedbacks_feedback_type ON user_feedbacks(feedback_type);
CREATE INDEX idx_user_feedbacks_processed ON user_feedbacks(processed);

-- 反馈回放表
CREATE TABLE IF NOT EXISTS feedback_replays (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    feedback_id UUID NOT NULL,
    replay_type VARCHAR(50) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending' NOT NULL,
    original_result JSONB,
    replay_result JSONB,
    comparison JSONB,
    suggestions JSONB,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- 索引
CREATE INDEX idx_feedback_replays_tenant_id ON feedback_replays(tenant_id);
CREATE INDEX idx_feedback_replays_feedback_id ON feedback_replays(feedback_id);
CREATE INDEX idx_feedback_replays_status ON feedback_replays(status);

-- 逻辑关联（无外键约束，依赖应用层与任务补偿保证一致性）

-- 注释
COMMENT ON TABLE user_feedbacks IS '用户反馈表';
COMMENT ON TABLE feedback_replays IS '反馈回放记录表';

-- 来自: migrations/20250306_220000_add_agent_checkpoint_tables.sql
-- Agent 恢复点表迁移
-- 创建时间: 2025-03-06

-- Agent 恢复点表
CREATE TABLE IF NOT EXISTS agent_checkpoints (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    agent_run_id UUID NOT NULL,
    checkpoint_seq INTEGER DEFAULT 0 NOT NULL,
    checkpoint_type VARCHAR(50) NOT NULL,
    state_snapshot JSONB NOT NULL,
    completed_steps JSONB DEFAULT '[]'::jsonb,
    pending_steps JSONB DEFAULT '[]'::jsonb,
    context_data JSONB DEFAULT '{}'::jsonb,
    tool_call_history JSONB DEFAULT '[]'::jsonb,
    error_info JSONB,
    recoverable BOOLEAN DEFAULT TRUE NOT NULL,
    recovery_strategy VARCHAR(50),
    notes TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL
);

-- 索引
CREATE INDEX idx_agent_checkpoints_tenant_id ON agent_checkpoints(tenant_id);
CREATE INDEX idx_agent_checkpoints_agent_run_id ON agent_checkpoints(agent_run_id);
CREATE INDEX idx_agent_checkpoints_run_seq ON agent_checkpoints(agent_run_id, checkpoint_seq);

-- Agent 恢复记录表
CREATE TABLE IF NOT EXISTS agent_recoveries (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    agent_run_id UUID NOT NULL,
    checkpoint_id UUID NOT NULL,
    status VARCHAR(50) DEFAULT 'pending' NOT NULL,
    recovery_strategy VARCHAR(50) NOT NULL,
    before_state JSONB,
    after_state JSONB,
    recovery_result JSONB,
    error_message TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW() NOT NULL,
    completed_at TIMESTAMP WITH TIME ZONE
);

-- 索引
CREATE INDEX idx_agent_recoveries_tenant_id ON agent_recoveries(tenant_id);
CREATE INDEX idx_agent_recoveries_agent_run_id ON agent_recoveries(agent_run_id);
CREATE INDEX idx_agent_recoveries_checkpoint_id ON agent_recoveries(checkpoint_id);
CREATE INDEX idx_agent_recoveries_status ON agent_recoveries(status);

-- 逻辑关联（无外键约束，依赖应用层与任务补偿保证一致性）

-- 注释
COMMENT ON TABLE agent_checkpoints IS 'Agent 执行恢复点表';
COMMENT ON TABLE agent_recoveries IS 'Agent 恢复记录表';

-- 来自: migrations/20260228_160000_init_migration_framework.sql
BEGIN;

-- 初始化增量迁移框架（占位 migration，便于建立执行流水线）。
-- 后续结构变更请新增新的 migration 文件，不要直接修改基线 SQL。
SELECT 1;

COMMIT;

-- 来自: migrations/20260302_140000_add_user_delete_permissions.sql
BEGIN;

INSERT INTO tenant_role_permissions (id, tenant_id, role, permission_code, created_at, updated_at)
SELECT gen_random_uuid(), rp.tenant_id, 'owner', 'api.user.delete', NOW(), NOW()
FROM (
    SELECT DISTINCT tenant_id
    FROM tenant_role_permissions
    WHERE role = 'owner'
) AS rp
ON CONFLICT (tenant_id, role, permission_code) DO NOTHING;

INSERT INTO tenant_role_permissions (id, tenant_id, role, permission_code, created_at, updated_at)
SELECT gen_random_uuid(), rp.tenant_id, 'owner', 'button.user.delete', NOW(), NOW()
FROM (
    SELECT DISTINCT tenant_id
    FROM tenant_role_permissions
    WHERE role = 'owner'
) AS rp
ON CONFLICT (tenant_id, role, permission_code) DO NOTHING;

INSERT INTO tenant_role_permissions (id, tenant_id, role, permission_code, created_at, updated_at)
SELECT gen_random_uuid(), rp.tenant_id, 'admin', 'api.user.delete', NOW(), NOW()
FROM (
    SELECT DISTINCT tenant_id
    FROM tenant_role_permissions
    WHERE role = 'admin'
) AS rp
ON CONFLICT (tenant_id, role, permission_code) DO NOTHING;

INSERT INTO tenant_role_permissions (id, tenant_id, role, permission_code, created_at, updated_at)
SELECT gen_random_uuid(), rp.tenant_id, 'admin', 'button.user.delete', NOW(), NOW()
FROM (
    SELECT DISTINCT tenant_id
    FROM tenant_role_permissions
    WHERE role = 'admin'
) AS rp
ON CONFLICT (tenant_id, role, permission_code) DO NOTHING;

COMMIT;

-- 来自: migrations/20260309_160000_add_governance_permissions.sql
BEGIN;

WITH role_actions(role, permission_code) AS (
    VALUES
        ('owner', 'api.governance.deletion.request.create'),
        ('owner', 'api.governance.deletion.request.read'),
        ('owner', 'api.governance.deletion.request.review'),
        ('owner', 'api.governance.deletion.execute'),
        ('owner', 'api.governance.retention.cleanup'),
        ('owner', 'api.governance.pii.mask'),
        ('admin', 'api.governance.deletion.request.create'),
        ('admin', 'api.governance.deletion.request.read'),
        ('admin', 'api.governance.deletion.request.review'),
        ('admin', 'api.governance.deletion.execute'),
        ('admin', 'api.governance.retention.cleanup'),
        ('admin', 'api.governance.pii.mask'),
        ('member', 'api.governance.deletion.request.create'),
        ('member', 'api.governance.deletion.request.read'),
        ('member', 'api.governance.pii.mask'),
        ('viewer', 'api.governance.deletion.request.create'),
        ('viewer', 'api.governance.deletion.request.read'),
        ('viewer', 'api.governance.pii.mask')
),
tenant_roles AS (
    SELECT DISTINCT tenant_id, role
    FROM tenant_role_permissions
    WHERE role IN ('owner', 'admin', 'member', 'viewer')
)
INSERT INTO tenant_role_permissions (id, tenant_id, role, permission_code, created_at, updated_at)
SELECT gen_random_uuid(), tr.tenant_id, ra.role, ra.permission_code, NOW(), NOW()
FROM role_actions AS ra
JOIN tenant_roles AS tr ON tr.role = ra.role
ON CONFLICT (tenant_id, role, permission_code) DO NOTHING;

COMMIT;

-- 来自: migrations/20260305_160000_add_retrieval_eval_tables.sql
BEGIN;

CREATE TABLE IF NOT EXISTS retrieval_eval_runs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    created_by UUID NOT NULL,
    name VARCHAR(128) NOT NULL DEFAULT 'adhoc',
    kb_ids JSONB NOT NULL DEFAULT '[]'::JSONB,
    top_k INTEGER NOT NULL DEFAULT 5,
    sample_total INTEGER NOT NULL DEFAULT 0,
    matched_total INTEGER NOT NULL DEFAULT 0,
    hit_at_k DOUBLE PRECISION NOT NULL DEFAULT 0,
    citation_coverage_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
    avg_latency_ms INTEGER NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'completed',
    summary_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_retrieval_eval_runs_top_k CHECK (top_k > 0),
    CONSTRAINT ck_retrieval_eval_runs_sample_total CHECK (sample_total >= 0),
    CONSTRAINT ck_retrieval_eval_runs_matched_total CHECK (matched_total >= 0),
    CONSTRAINT ck_retrieval_eval_runs_hit_at_k CHECK (hit_at_k >= 0 AND hit_at_k <= 1),
    CONSTRAINT ck_retrieval_eval_runs_citation_coverage_rate CHECK (
        citation_coverage_rate >= 0 AND citation_coverage_rate <= 1
    ),
    CONSTRAINT ck_retrieval_eval_runs_status CHECK (status IN ('queued', 'running', 'completed', 'failed'))
);

CREATE TABLE IF NOT EXISTS retrieval_eval_items (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id UUID NOT NULL,
    tenant_id UUID NOT NULL,
    sample_no INTEGER NOT NULL,
    query_text TEXT NOT NULL,
    expected_terms JSONB NOT NULL DEFAULT '[]'::JSONB,
    matched BOOLEAN NOT NULL DEFAULT FALSE,
    hit_count INTEGER NOT NULL DEFAULT 0,
    citation_covered BOOLEAN NOT NULL DEFAULT FALSE,
    top_hit_score INTEGER NULL,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    result_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_retrieval_eval_item_run_no UNIQUE (run_id, sample_no),
    CONSTRAINT ck_retrieval_eval_items_sample_no CHECK (sample_no > 0),
    CONSTRAINT ck_retrieval_eval_items_hit_count CHECK (hit_count >= 0),
    CONSTRAINT ck_retrieval_eval_items_latency_ms CHECK (latency_ms >= 0)
);

CREATE INDEX IF NOT EXISTS ix_retrieval_eval_runs_tenant_created_at
    ON retrieval_eval_runs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_retrieval_eval_runs_created_by
    ON retrieval_eval_runs (created_by);
CREATE INDEX IF NOT EXISTS ix_retrieval_eval_items_tenant_run
    ON retrieval_eval_items (tenant_id, run_id);
CREATE INDEX IF NOT EXISTS ix_retrieval_eval_items_run_sample_no
    ON retrieval_eval_items (run_id, sample_no);

COMMENT ON TABLE retrieval_eval_runs IS '检索评测运行记录表。';
COMMENT ON COLUMN retrieval_eval_runs.tenant_id IS '租户 ID。';
COMMENT ON COLUMN retrieval_eval_runs.created_by IS '发起评测用户 ID。';
COMMENT ON COLUMN retrieval_eval_runs.name IS '评测任务名称。';
COMMENT ON COLUMN retrieval_eval_runs.kb_ids IS '评测范围知识库 ID 列表。';
COMMENT ON COLUMN retrieval_eval_runs.top_k IS '评测检索 top_k。';
COMMENT ON COLUMN retrieval_eval_runs.sample_total IS '样本总数。';
COMMENT ON COLUMN retrieval_eval_runs.matched_total IS '命中样本数。';
COMMENT ON COLUMN retrieval_eval_runs.hit_at_k IS '命中率。';
COMMENT ON COLUMN retrieval_eval_runs.citation_coverage_rate IS '引用覆盖率。';
COMMENT ON COLUMN retrieval_eval_runs.avg_latency_ms IS '平均延迟。';
COMMENT ON COLUMN retrieval_eval_runs.status IS '运行状态。';
COMMENT ON COLUMN retrieval_eval_runs.summary_json IS '汇总快照。';
COMMENT ON COLUMN retrieval_eval_runs.created_at IS '创建时间。';
COMMENT ON COLUMN retrieval_eval_runs.updated_at IS '更新时间。';

COMMENT ON TABLE retrieval_eval_items IS '检索评测样本明细表。';
COMMENT ON COLUMN retrieval_eval_items.run_id IS '评测运行 ID。';
COMMENT ON COLUMN retrieval_eval_items.tenant_id IS '租户 ID。';
COMMENT ON COLUMN retrieval_eval_items.sample_no IS '样本序号。';
COMMENT ON COLUMN retrieval_eval_items.query_text IS '评测问题。';
COMMENT ON COLUMN retrieval_eval_items.expected_terms IS '预期关键词列表。';
COMMENT ON COLUMN retrieval_eval_items.matched IS '是否命中。';
COMMENT ON COLUMN retrieval_eval_items.hit_count IS '命中数。';
COMMENT ON COLUMN retrieval_eval_items.citation_covered IS '引用覆盖情况。';
COMMENT ON COLUMN retrieval_eval_items.top_hit_score IS '第一命中分。';
COMMENT ON COLUMN retrieval_eval_items.latency_ms IS '检索延迟毫秒。';
COMMENT ON COLUMN retrieval_eval_items.result_json IS '样本结果快照。';
COMMENT ON COLUMN retrieval_eval_items.created_at IS '创建时间。';

COMMIT;

-- 来自: migrations/20260305_183000_add_quota_policies.sql
BEGIN;

CREATE TABLE IF NOT EXISTS quota_policies (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    scope_type VARCHAR(16) NOT NULL,
    scope_id UUID NOT NULL,
    metric_code VARCHAR(64) NOT NULL,
    limit_value INTEGER NOT NULL,
    window_minutes INTEGER NOT NULL DEFAULT 1440,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_by UUID NULL,
    updated_by UUID NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_quota_policy_scope_metric UNIQUE (tenant_id, scope_type, scope_id, metric_code),
    CONSTRAINT ck_quota_policies_scope_type CHECK (scope_type IN ('tenant', 'workspace')),
    CONSTRAINT ck_quota_policies_limit_value CHECK (limit_value >= 0),
    CONSTRAINT ck_quota_policies_window_minutes CHECK (window_minutes >= 1)
);

CREATE INDEX IF NOT EXISTS ix_quota_policies_tenant_scope
    ON quota_policies (tenant_id, scope_type, scope_id);
CREATE INDEX IF NOT EXISTS ix_quota_policies_metric_enabled
    ON quota_policies (metric_code, enabled);

COMMENT ON TABLE quota_policies IS '租户与工作空间配额策略表。';
COMMENT ON COLUMN quota_policies.tenant_id IS '租户 ID。';
COMMENT ON COLUMN quota_policies.scope_type IS '配额范围类型（tenant/workspace）。';
COMMENT ON COLUMN quota_policies.scope_id IS '配额范围 ID。tenant 级为 tenant_id，workspace 级为 workspace_id。';
COMMENT ON COLUMN quota_policies.metric_code IS '配额指标编码。';
COMMENT ON COLUMN quota_policies.limit_value IS '窗口内允许上限值。';
COMMENT ON COLUMN quota_policies.window_minutes IS '统计窗口分钟数。';
COMMENT ON COLUMN quota_policies.enabled IS '是否启用该策略。';
COMMENT ON COLUMN quota_policies.created_by IS '创建策略用户 ID。';
COMMENT ON COLUMN quota_policies.updated_by IS '最后更新策略用户 ID。';
COMMENT ON COLUMN quota_policies.created_at IS '创建时间。';
COMMENT ON COLUMN quota_policies.updated_at IS '更新时间。';

COMMIT;

-- 来自: migrations/20260306_100000_add_ops_phase3_tables.sql
BEGIN;

CREATE TABLE IF NOT EXISTS ops_incident_tickets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    source_code VARCHAR(64) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'warn',
    status VARCHAR(16) NOT NULL DEFAULT 'open',
    title VARCHAR(256) NOT NULL,
    summary TEXT NOT NULL,
    diagnosis_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    context_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    assignee_user_id UUID NULL,
    resolution_note TEXT NULL,
    created_by UUID NULL,
    resolved_at VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_ops_incident_tickets_severity CHECK (severity IN ('info', 'warn', 'critical')),
    CONSTRAINT ck_ops_incident_tickets_status CHECK (status IN ('open', 'acknowledged', 'resolved'))
);

CREATE INDEX IF NOT EXISTS ix_ops_incident_tickets_tenant_status_created_at
    ON ops_incident_tickets (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ops_incident_tickets_source_code
    ON ops_incident_tickets (source_code);

CREATE TABLE IF NOT EXISTS ops_alert_webhooks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    name VARCHAR(64) NOT NULL,
    url TEXT NOT NULL,
    secret VARCHAR(256) NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    event_types JSONB NOT NULL DEFAULT '[]'::JSONB,
    timeout_seconds INTEGER NOT NULL DEFAULT 3,
    last_status_code INTEGER NULL,
    last_error TEXT NULL,
    last_notified_at VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uk_ops_alert_webhook_name UNIQUE (tenant_id, name),
    CONSTRAINT ck_ops_alert_webhooks_timeout_seconds CHECK (timeout_seconds >= 1 AND timeout_seconds <= 30)
);

CREATE INDEX IF NOT EXISTS ix_ops_alert_webhooks_tenant_enabled
    ON ops_alert_webhooks (tenant_id, enabled);

COMMENT ON TABLE ops_incident_tickets IS '运维异常工单表。';
COMMENT ON COLUMN ops_incident_tickets.tenant_id IS '租户 ID。';
COMMENT ON COLUMN ops_incident_tickets.source_code IS '异常来源编码。';
COMMENT ON COLUMN ops_incident_tickets.severity IS '工单严重级别。';
COMMENT ON COLUMN ops_incident_tickets.status IS '工单状态。';
COMMENT ON COLUMN ops_incident_tickets.title IS '工单标题。';
COMMENT ON COLUMN ops_incident_tickets.summary IS '异常摘要。';
COMMENT ON COLUMN ops_incident_tickets.diagnosis_json IS '诊断详情 JSON。';
COMMENT ON COLUMN ops_incident_tickets.context_json IS '上下文 JSON。';
COMMENT ON COLUMN ops_incident_tickets.assignee_user_id IS '当前处理人用户 ID。';
COMMENT ON COLUMN ops_incident_tickets.resolution_note IS '处理结论。';
COMMENT ON COLUMN ops_incident_tickets.created_by IS '工单创建人用户 ID。';
COMMENT ON COLUMN ops_incident_tickets.resolved_at IS '工单关闭时间（ISO8601）。';
COMMENT ON COLUMN ops_incident_tickets.created_at IS '创建时间。';
COMMENT ON COLUMN ops_incident_tickets.updated_at IS '更新时间。';

COMMENT ON TABLE ops_alert_webhooks IS '告警 webhook 订阅表。';
COMMENT ON COLUMN ops_alert_webhooks.tenant_id IS '租户 ID。';
COMMENT ON COLUMN ops_alert_webhooks.name IS '订阅名称。';
COMMENT ON COLUMN ops_alert_webhooks.url IS 'webhook 地址。';
COMMENT ON COLUMN ops_alert_webhooks.secret IS '可选签名密钥。';
COMMENT ON COLUMN ops_alert_webhooks.enabled IS '是否启用。';
COMMENT ON COLUMN ops_alert_webhooks.event_types IS '订阅事件类型列表。';
COMMENT ON COLUMN ops_alert_webhooks.timeout_seconds IS '通知超时时间（秒）。';
COMMENT ON COLUMN ops_alert_webhooks.last_status_code IS '最近一次通知响应码。';
COMMENT ON COLUMN ops_alert_webhooks.last_error IS '最近一次通知错误。';
COMMENT ON COLUMN ops_alert_webhooks.last_notified_at IS '最近一次通知时间（ISO8601）。';
COMMENT ON COLUMN ops_alert_webhooks.created_at IS '创建时间。';
COMMENT ON COLUMN ops_alert_webhooks.updated_at IS '更新时间。';

-- 告警状态记录表
CREATE TABLE IF NOT EXISTS ops_alert_status (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    alert_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'active',
    acknowledged_by UUID NULL,
    acknowledged_at VARCHAR(64) NULL,
    resolved_by UUID NULL,
    resolved_at VARCHAR(64) NULL,
    notes TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_ops_alert_status_status CHECK (status IN ('active', 'acknowledged', 'resolved', 'closed'))
);

CREATE INDEX IF NOT EXISTS ix_ops_alert_status_tenant_id
    ON ops_alert_status (tenant_id);
CREATE INDEX IF NOT EXISTS ix_ops_alert_status_alert_id
    ON ops_alert_status (alert_id);
CREATE INDEX IF NOT EXISTS ix_ops_alert_status_status
    ON ops_alert_status (status);

COMMENT ON TABLE ops_alert_status IS '告警状态记录表。';
COMMENT ON COLUMN ops_alert_status.tenant_id IS '租户 ID。';
COMMENT ON COLUMN ops_alert_status.alert_id IS '告警 ID。';
COMMENT ON COLUMN ops_alert_status.status IS '告警状态（active/acknowledged/resolved/closed）。';
COMMENT ON COLUMN ops_alert_status.acknowledged_by IS '确认人用户 ID。';
COMMENT ON COLUMN ops_alert_status.acknowledged_at IS '确认时间（ISO8601）。';
COMMENT ON COLUMN ops_alert_status.resolved_by IS '解决人用户 ID。';
COMMENT ON COLUMN ops_alert_status.resolved_at IS '解决时间（ISO8601）。';
COMMENT ON COLUMN ops_alert_status.notes IS '备注信息。';
COMMENT ON COLUMN ops_alert_status.created_at IS '创建时间。';
COMMENT ON COLUMN ops_alert_status.updated_at IS '更新时间。';

COMMIT;

-- 来自: migrations/20260306_130000_add_ops_phase4_tables.sql
BEGIN;

CREATE TABLE IF NOT EXISTS ops_release_rollouts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    version VARCHAR(64) NOT NULL,
    strategy VARCHAR(32) NOT NULL DEFAULT 'canary',
    status VARCHAR(32) NOT NULL DEFAULT 'planned',
    risk_level VARCHAR(16) NOT NULL DEFAULT 'medium',
    canary_percent INTEGER NOT NULL DEFAULT 10,
    scope_json JSONB NOT NULL DEFAULT '{}'::JSONB,
    rollback_of UUID NULL,
    approved_by UUID NULL,
    note TEXT NULL,
    started_at VARCHAR(64) NULL,
    completed_at VARCHAR(64) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_ops_release_rollouts_strategy CHECK (strategy IN ('canary', 'blue_green', 'rolling')),
    CONSTRAINT ck_ops_release_rollouts_status CHECK (status IN ('planned', 'running', 'completed', 'rolled_back', 'canceled')),
    CONSTRAINT ck_ops_release_rollouts_risk_level CHECK (risk_level IN ('low', 'medium', 'high')),
    CONSTRAINT ck_ops_release_rollouts_canary_percent CHECK (canary_percent >= 0 AND canary_percent <= 100)
);

CREATE INDEX IF NOT EXISTS ix_ops_release_rollouts_tenant_created_at
    ON ops_release_rollouts (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ops_release_rollouts_tenant_status
    ON ops_release_rollouts (tenant_id, status);
CREATE INDEX IF NOT EXISTS ix_ops_release_rollouts_version
    ON ops_release_rollouts (version);
CREATE INDEX IF NOT EXISTS ix_ops_release_rollouts_rollback_of
    ON ops_release_rollouts (rollback_of);

CREATE TABLE IF NOT EXISTS ops_deletion_proofs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL,
    resource_type VARCHAR(64) NOT NULL,
    resource_id VARCHAR(128) NOT NULL,
    subject_hash VARCHAR(128) NOT NULL,
    signature VARCHAR(128) NOT NULL,
    deleted_by UUID NULL,
    deleted_at VARCHAR(64) NOT NULL,
    ticket_id UUID NULL,
    proof_payload JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_ops_deletion_proofs_resource_type CHECK (resource_type IN ('document', 'knowledge_base', 'workspace', 'tenant', 'user'))
);

CREATE INDEX IF NOT EXISTS ix_ops_deletion_proofs_tenant_created_at
    ON ops_deletion_proofs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ops_deletion_proofs_resource
    ON ops_deletion_proofs (tenant_id, resource_type, resource_id);
CREATE INDEX IF NOT EXISTS ix_ops_deletion_proofs_subject_hash
    ON ops_deletion_proofs (subject_hash);
CREATE INDEX IF NOT EXISTS ix_ops_deletion_proofs_ticket_id
    ON ops_deletion_proofs (ticket_id);

COMMENT ON TABLE ops_release_rollouts IS '发布与回滚记录表。';
COMMENT ON COLUMN ops_release_rollouts.tenant_id IS '租户 ID。';
COMMENT ON COLUMN ops_release_rollouts.version IS '发布版本标识。';
COMMENT ON COLUMN ops_release_rollouts.strategy IS '发布策略（canary/blue_green/rolling）。';
COMMENT ON COLUMN ops_release_rollouts.status IS '发布状态。';
COMMENT ON COLUMN ops_release_rollouts.risk_level IS '变更风险等级。';
COMMENT ON COLUMN ops_release_rollouts.canary_percent IS '金丝雀灰度比例（0-100）。';
COMMENT ON COLUMN ops_release_rollouts.scope_json IS '发布范围定义。';
COMMENT ON COLUMN ops_release_rollouts.rollback_of IS '若为回滚动作，指向被回滚发布 ID。';
COMMENT ON COLUMN ops_release_rollouts.approved_by IS '审批人用户 ID。';
COMMENT ON COLUMN ops_release_rollouts.note IS '发布备注。';
COMMENT ON COLUMN ops_release_rollouts.started_at IS '发布启动时间（ISO8601）。';
COMMENT ON COLUMN ops_release_rollouts.completed_at IS '发布完成时间（ISO8601）。';
COMMENT ON COLUMN ops_release_rollouts.created_at IS '创建时间。';
COMMENT ON COLUMN ops_release_rollouts.updated_at IS '更新时间。';

COMMENT ON TABLE ops_deletion_proofs IS '删除证明记录表。';
COMMENT ON COLUMN ops_deletion_proofs.tenant_id IS '租户 ID。';
COMMENT ON COLUMN ops_deletion_proofs.resource_type IS '删除资源类型。';
COMMENT ON COLUMN ops_deletion_proofs.resource_id IS '删除资源标识。';
COMMENT ON COLUMN ops_deletion_proofs.subject_hash IS '删除主体摘要（hash）。';
COMMENT ON COLUMN ops_deletion_proofs.signature IS '证明签名。';
COMMENT ON COLUMN ops_deletion_proofs.deleted_by IS '执行删除的用户 ID。';
COMMENT ON COLUMN ops_deletion_proofs.deleted_at IS '删除发生时间（ISO8601）。';
COMMENT ON COLUMN ops_deletion_proofs.ticket_id IS '关联排障/工单 ID。';
COMMENT ON COLUMN ops_deletion_proofs.proof_payload IS '删除证明补充载荷。';
COMMENT ON COLUMN ops_deletion_proofs.created_at IS '创建时间。';
COMMENT ON COLUMN ops_deletion_proofs.updated_at IS '更新时间。';

COMMIT;

-- 来自: migrations/20260306_200000_add_vector_embedding_column.sql
BEGIN;

-- 为 document_chunks 添加向量列以支持语义检索
-- 使用 1536 维度（OpenAI text-embedding-3-small 默认维度）

ALTER TABLE document_chunks
ADD COLUMN IF NOT EXISTS embedding vector(1536);

-- 为向量列创建 HNSW 索引以加速相似度搜索
-- 使用余弦距离（cosine distance）作为相似度度量
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding_cosine
ON document_chunks
USING hnsw (embedding vector_cosine_ops);

-- 添加嵌入模型标识列，用于追踪使用的模型版本
ALTER TABLE document_chunks
ADD COLUMN IF NOT EXISTS embedding_model VARCHAR(128);

-- 添加嵌入生成时间戳
ALTER TABLE document_chunks
ADD COLUMN IF NOT EXISTS embedded_at TIMESTAMPTZ;

COMMENT ON COLUMN document_chunks.embedding IS '文本块的向量表示，用于语义检索';
COMMENT ON COLUMN document_chunks.embedding_model IS '生成向量的模型标识（如 text-embedding-3-small）';
COMMENT ON COLUMN document_chunks.embedded_at IS '向量生成时间';

COMMIT;
-- 来自: migrations/20260307_100000_enable_rls.sql
-- Row Level Security (RLS) 配置
-- 为多租户数据隔离提供数据库层面的安全保障

BEGIN;

-- 启用 RLS 的表列表
-- 所有包含 tenant_id 的业务表都应启用 RLS

-- 1. 启用 tenants 表的 RLS
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;

-- 租户只能访问自己的记录
DROP POLICY IF EXISTS tenant_isolation_policy ON tenants;
CREATE POLICY tenant_isolation_policy ON tenants
    FOR ALL
    USING (id = current_setting('app.current_tenant_id', true)::uuid);

-- 2. 启用 users 表的 RLS
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- 用户可以访问自己的记录
DROP POLICY IF EXISTS user_self_access_policy ON users;
CREATE POLICY user_self_access_policy ON users
    FOR ALL
    USING (id = current_setting('app.current_user_id', true)::uuid);

-- 3. 启用 tenant_memberships 表的 RLS
ALTER TABLE tenant_memberships ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的成员关系
DROP POLICY IF EXISTS tenant_membership_isolation_policy ON tenant_memberships;
CREATE POLICY tenant_membership_isolation_policy ON tenant_memberships
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 4. 启用 workspaces 表的 RLS
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的工作空间
DROP POLICY IF EXISTS workspace_isolation_policy ON workspaces;
CREATE POLICY workspace_isolation_policy ON workspaces
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 5. 启用 knowledge_bases 表的 RLS
ALTER TABLE knowledge_bases ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的知识库
DROP POLICY IF EXISTS kb_isolation_policy ON knowledge_bases;
CREATE POLICY kb_isolation_policy ON knowledge_bases
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 6. 启用 kb_memberships 表的 RLS
ALTER TABLE kb_memberships ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户知识库的成员关系
DROP POLICY IF EXISTS kb_membership_isolation_policy ON kb_memberships;
CREATE POLICY kb_membership_isolation_policy ON kb_memberships
    FOR ALL
    USING (
        kb_id IN (
            SELECT id FROM knowledge_bases
            WHERE tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
    );

-- 7. 启用 documents 表的 RLS
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的文档
DROP POLICY IF EXISTS document_isolation_policy ON documents;
CREATE POLICY document_isolation_policy ON documents
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 8. 启用 document_versions 表的 RLS
ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的文档版本
DROP POLICY IF EXISTS document_version_isolation_policy ON document_versions;
CREATE POLICY document_version_isolation_policy ON document_versions
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 9. 启用 document_chunks 表的 RLS
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的文档切片
DROP POLICY IF EXISTS document_chunk_isolation_policy ON document_chunks;
CREATE POLICY document_chunk_isolation_policy ON document_chunks
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 10. 启用 conversations 表的 RLS
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的对话
DROP POLICY IF EXISTS conversation_isolation_policy ON conversations;
CREATE POLICY conversation_isolation_policy ON conversations
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 11. 启用 messages 表的 RLS
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户对话的消息
DROP POLICY IF EXISTS message_isolation_policy ON messages;
CREATE POLICY message_isolation_policy ON messages
    FOR ALL
    USING (
        conversation_id IN (
            SELECT id FROM conversations
            WHERE tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
    );

-- 12. 启用 agent_runs 表的 RLS
ALTER TABLE agent_runs ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的 Agent 运行记录
DROP POLICY IF EXISTS agent_run_isolation_policy ON agent_runs;
CREATE POLICY agent_run_isolation_policy ON agent_runs
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 13. 启用 audit_logs 表的 RLS
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的审计日志
DROP POLICY IF EXISTS audit_log_isolation_policy ON audit_logs;
CREATE POLICY audit_log_isolation_policy ON audit_logs
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 14. 启用 retrieval_logs 表的 RLS
ALTER TABLE retrieval_logs ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的检索日志
DROP POLICY IF EXISTS retrieval_log_isolation_policy ON retrieval_logs;
CREATE POLICY retrieval_log_isolation_policy ON retrieval_logs
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 15. 启用 ingestion_jobs 表的 RLS
ALTER TABLE ingestion_jobs ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的接入任务
DROP POLICY IF EXISTS ingestion_job_isolation_policy ON ingestion_jobs;
CREATE POLICY ingestion_job_isolation_policy ON ingestion_jobs
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 注意事项：
-- 1. 应用层需要在每个数据库会话开始时设置 current_tenant_id 和 current_user_id
--    示例: SET LOCAL app.current_tenant_id = 'xxx-xxx-xxx';
-- 2. RLS 策略会自动应用于所有 SELECT/INSERT/UPDATE/DELETE 操作
-- 3. 超级用户（postgres）不受 RLS 限制，用于管理和维护
-- 4. 应用服务账号应该是普通用户，受 RLS 限制
-- 5. 性能考虑：RLS 策略会增加查询开销，建议配合索引优化

COMMIT;

-- 注意：deletion_requests 和 deletion_proofs 表已被移除
-- 现在使用 ops_deletion_proofs 表来记录删除证明

-- ============================================================================
-- 索引
-- ============================================================================

-- 基础访问路径索引（覆盖 tenant/user/workspace/kb/document 高频过滤）。

CREATE INDEX IF NOT EXISTS ix_tenants_status ON tenants (status);

CREATE INDEX IF NOT EXISTS ix_users_status ON users (status);
CREATE INDEX IF NOT EXISTS ix_users_auth_provider ON users (auth_provider);

CREATE INDEX IF NOT EXISTS ix_tenant_memberships_tenant_id ON tenant_memberships (tenant_id);
CREATE INDEX IF NOT EXISTS ix_tenant_memberships_user_id ON tenant_memberships (user_id);
CREATE INDEX IF NOT EXISTS ix_tenant_memberships_tenant_user_status
    ON tenant_memberships (tenant_id, user_id, status);
CREATE INDEX IF NOT EXISTS ix_tenant_memberships_user_status
    ON tenant_memberships (user_id, status);
CREATE INDEX IF NOT EXISTS ix_tenant_memberships_tenant_role_status
    ON tenant_memberships (tenant_id, role, status);

CREATE INDEX IF NOT EXISTS ix_workspaces_tenant_id ON workspaces (tenant_id);
CREATE INDEX IF NOT EXISTS ix_workspaces_tenant_status ON workspaces (tenant_id, status);

CREATE INDEX IF NOT EXISTS ix_workspace_memberships_tenant_id ON workspace_memberships (tenant_id);
CREATE INDEX IF NOT EXISTS ix_workspace_memberships_workspace_id ON workspace_memberships (workspace_id);
CREATE INDEX IF NOT EXISTS ix_workspace_memberships_user_id ON workspace_memberships (user_id);
CREATE INDEX IF NOT EXISTS ix_workspace_memberships_workspace_user_status
    ON workspace_memberships (workspace_id, user_id, status);
CREATE INDEX IF NOT EXISTS ix_workspace_memberships_tenant_user_status
    ON workspace_memberships (tenant_id, user_id, status);
CREATE INDEX IF NOT EXISTS ix_workspace_memberships_tenant_workspace_status
    ON workspace_memberships (tenant_id, workspace_id, status);
CREATE INDEX IF NOT EXISTS ix_workspace_memberships_user_status_active
    ON workspace_memberships (user_id, status)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS ix_knowledge_bases_tenant_id ON knowledge_bases (tenant_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_bases_workspace_id ON knowledge_bases (workspace_id);
CREATE INDEX IF NOT EXISTS ix_knowledge_bases_tenant_workspace_status
    ON knowledge_bases (tenant_id, workspace_id, status);

CREATE INDEX IF NOT EXISTS ix_kb_memberships_tenant_id ON kb_memberships (tenant_id);
CREATE INDEX IF NOT EXISTS ix_kb_memberships_kb_id ON kb_memberships (kb_id);
CREATE INDEX IF NOT EXISTS ix_kb_memberships_user_id ON kb_memberships (user_id);
CREATE INDEX IF NOT EXISTS ix_kb_memberships_kb_user_status
    ON kb_memberships (kb_id, user_id, status);
CREATE INDEX IF NOT EXISTS ix_kb_memberships_tenant_user_status
    ON kb_memberships (tenant_id, user_id, status);
CREATE INDEX IF NOT EXISTS ix_kb_memberships_tenant_kb_status
    ON kb_memberships (tenant_id, kb_id, status);

CREATE INDEX IF NOT EXISTS ix_documents_tenant_id ON documents (tenant_id);
CREATE INDEX IF NOT EXISTS ix_documents_workspace_id ON documents (workspace_id);
CREATE INDEX IF NOT EXISTS ix_documents_kb_id ON documents (kb_id);
CREATE INDEX IF NOT EXISTS ix_documents_tenant_workspace_kb_status
    ON documents (tenant_id, workspace_id, kb_id, status);
CREATE INDEX IF NOT EXISTS ix_documents_tenant_kb_status
    ON documents (tenant_id, kb_id, status);
CREATE INDEX IF NOT EXISTS ix_documents_upload_dedupe
    ON documents (tenant_id, workspace_id, kb_id, source_type, source_uri)
    WHERE source_uri IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_document_versions_tenant_id ON document_versions (tenant_id);
CREATE INDEX IF NOT EXISTS ix_document_versions_document_id ON document_versions (document_id);
CREATE INDEX IF NOT EXISTS ix_document_versions_document_created_at
    ON document_versions (document_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_document_versions_document_version
    ON document_versions (document_id, version DESC);
CREATE INDEX IF NOT EXISTS ix_document_versions_tenant_status
    ON document_versions (tenant_id, parse_status);

CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_id ON document_chunks (tenant_id);
CREATE INDEX IF NOT EXISTS ix_document_chunks_workspace_id ON document_chunks (workspace_id);
CREATE INDEX IF NOT EXISTS ix_document_chunks_kb_id ON document_chunks (kb_id);
CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id ON document_chunks (document_id);
CREATE INDEX IF NOT EXISTS ix_document_chunks_document_version_id ON document_chunks (document_version_id);
CREATE INDEX IF NOT EXISTS ix_document_chunks_tenant_kb_created_at
    ON document_chunks (tenant_id, kb_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_tenant_id ON chunk_embeddings (tenant_id);
CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_kb_id ON chunk_embeddings (kb_id);
CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_tenant_kb ON chunk_embeddings (tenant_id, kb_id);
CREATE INDEX IF NOT EXISTS ix_chunk_embeddings_vector_ivfflat
    ON chunk_embeddings USING ivfflat (vector vector_cosine_ops) WITH (lists = 100);

CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_tenant_id ON ingestion_jobs (tenant_id);
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_workspace_id ON ingestion_jobs (workspace_id);
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_kb_id ON ingestion_jobs (kb_id);
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_document_id ON ingestion_jobs (document_id);
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_document_version_id ON ingestion_jobs (document_version_id);
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_tenant_status_next_run
    ON ingestion_jobs (tenant_id, status, next_run_at);
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_status_next_run
    ON ingestion_jobs (status, next_run_at);
CREATE INDEX IF NOT EXISTS ix_ingestion_jobs_locked_by_locked_at
    ON ingestion_jobs (locked_by, locked_at);

CREATE INDEX IF NOT EXISTS ix_retrieval_logs_tenant_id ON retrieval_logs (tenant_id);
CREATE INDEX IF NOT EXISTS ix_retrieval_logs_user_id ON retrieval_logs (user_id);
CREATE INDEX IF NOT EXISTS ix_retrieval_logs_tenant_user_created_at
    ON retrieval_logs (tenant_id, user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_user_credentials_user_id ON user_credentials (user_id);
CREATE INDEX IF NOT EXISTS ix_user_credentials_status ON user_credentials (status);

CREATE INDEX IF NOT EXISTS ix_user_mfa_totp_user_id ON user_mfa_totp (user_id);
CREATE INDEX IF NOT EXISTS ix_user_mfa_totp_enabled ON user_mfa_totp (enabled);

CREATE INDEX IF NOT EXISTS ix_tenant_role_permissions_tenant_id ON tenant_role_permissions (tenant_id);
CREATE INDEX IF NOT EXISTS ix_tenant_role_permissions_role ON tenant_role_permissions (role);
CREATE INDEX IF NOT EXISTS ix_tenant_role_permissions_permission_code ON tenant_role_permissions (permission_code);
CREATE INDEX IF NOT EXISTS ix_tenant_role_permissions_tenant_role
    ON tenant_role_permissions (tenant_id, role);

CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_id ON audit_logs (tenant_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_user_id ON audit_logs (actor_user_id);
CREATE INDEX IF NOT EXISTS ix_audit_logs_created_at ON audit_logs (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_created_at
    ON audit_logs (tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_audit_logs_action ON audit_logs (action);
CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_action_created_at
    ON audit_logs (tenant_id, action, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_conversations_tenant_id ON conversations (tenant_id);
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations (user_id);
CREATE INDEX IF NOT EXISTS ix_conversations_tenant_user_updated_at
    ON conversations (tenant_id, user_id, updated_at DESC);

CREATE INDEX IF NOT EXISTS ix_messages_tenant_id ON messages (tenant_id);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages (conversation_id);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_created_at
    ON messages (conversation_id, created_at);

CREATE INDEX IF NOT EXISTS ix_agent_runs_tenant_id ON agent_runs (tenant_id);
CREATE INDEX IF NOT EXISTS ix_agent_runs_user_id ON agent_runs (user_id);
CREATE INDEX IF NOT EXISTS ix_agent_runs_conversation_id ON agent_runs (conversation_id);
CREATE INDEX IF NOT EXISTS ix_agent_runs_tenant_status_created_at
    ON agent_runs (tenant_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_agent_runs_tenant_user_created_at
    ON agent_runs (tenant_id, user_id, created_at DESC);

-- ============================================================================
-- 注释
-- ============================================================================

-- 表注释
COMMENT ON TABLE tenants IS '租户主表，系统最高数据隔离边界。';
COMMENT ON TABLE users IS '用户主表，承载外部身份在本系统的映射。';
COMMENT ON TABLE tenant_memberships IS '租户成员关系表。';
COMMENT ON TABLE workspaces IS '工作空间主表。';
COMMENT ON TABLE workspace_memberships IS '工作空间成员关系表。';
COMMENT ON TABLE knowledge_bases IS '知识库主表。';
COMMENT ON TABLE kb_memberships IS '知识库成员关系表。';
COMMENT ON TABLE documents IS '文档主记录表。';
COMMENT ON TABLE document_versions IS '文档版本表。';
COMMENT ON TABLE document_chunks IS '文档切片表，检索最小粒度。';
COMMENT ON TABLE chunk_embeddings IS '切片向量表，一条切片对应一条向量。';
COMMENT ON TABLE ingestion_jobs IS '文档入库异步任务表。';
COMMENT ON TABLE retrieval_logs IS '检索请求与结果日志表。';
COMMENT ON TABLE user_credentials IS '用户本地凭据表（邮箱/密码哈希）。';
COMMENT ON TABLE user_mfa_totp IS '用户 TOTP 二次验证配置表。';
COMMENT ON TABLE tenant_role_permissions IS '租户角色权限点映射表。';
COMMENT ON TABLE audit_logs IS '关键操作审计日志表。';
COMMENT ON TABLE conversations IS '会话主表。';
COMMENT ON TABLE messages IS '会话消息表。';
COMMENT ON TABLE agent_runs IS '智能体任务运行表。';

-- tenants
COMMENT ON COLUMN tenants.id IS '主键 UUID。';
COMMENT ON COLUMN tenants.name IS '租户名称。';
COMMENT ON COLUMN tenants.slug IS '全局唯一短标识。';
COMMENT ON COLUMN tenants.isolation_level IS '隔离级别，默认 shared。';
COMMENT ON COLUMN tenants.status IS '租户状态：active/suspended/deleted。';
COMMENT ON COLUMN tenants.created_at IS '创建时间。';
COMMENT ON COLUMN tenants.updated_at IS '更新时间。';

-- users
COMMENT ON COLUMN users.id IS '主键 UUID。';
COMMENT ON COLUMN users.email IS '登录邮箱，全局唯一。';
COMMENT ON COLUMN users.display_name IS '展示名称。';
COMMENT ON COLUMN users.status IS '用户状态（建议 active/disabled）。';
COMMENT ON COLUMN users.auth_provider IS '认证提供方（如 jwt/dev）。';
COMMENT ON COLUMN users.external_subject IS '外部身份主体 ID。';
COMMENT ON COLUMN users.last_login_at IS '最近登录时间。';
COMMENT ON COLUMN users.created_at IS '创建时间。';
COMMENT ON COLUMN users.updated_at IS '更新时间。';

-- tenant_memberships
COMMENT ON COLUMN tenant_memberships.id IS '主键 UUID。';
COMMENT ON COLUMN tenant_memberships.tenant_id IS '租户 ID（逻辑关联 tenants.id）。';
COMMENT ON COLUMN tenant_memberships.user_id IS '用户 ID（逻辑关联 users.id）。';
COMMENT ON COLUMN tenant_memberships.role IS '租户角色：owner/admin/member/viewer。';
COMMENT ON COLUMN tenant_memberships.status IS '成员状态：active/invited/disabled。';
COMMENT ON COLUMN tenant_memberships.created_at IS '创建时间。';
COMMENT ON COLUMN tenant_memberships.updated_at IS '更新时间。';

-- workspaces
COMMENT ON COLUMN workspaces.id IS '主键 UUID。';
COMMENT ON COLUMN workspaces.tenant_id IS '租户 ID（逻辑关联 tenants.id）。';
COMMENT ON COLUMN workspaces.name IS '工作空间名称。';
COMMENT ON COLUMN workspaces.slug IS '租户内唯一短标识。';
COMMENT ON COLUMN workspaces.description IS '工作空间描述。';
COMMENT ON COLUMN workspaces.status IS '工作空间状态：active/archived。';
COMMENT ON COLUMN workspaces.created_at IS '创建时间。';
COMMENT ON COLUMN workspaces.updated_at IS '更新时间。';

-- workspace_memberships
COMMENT ON COLUMN workspace_memberships.id IS '主键 UUID。';
COMMENT ON COLUMN workspace_memberships.tenant_id IS '租户 ID（冗余字段，便于过滤）。';
COMMENT ON COLUMN workspace_memberships.workspace_id IS '工作空间 ID（逻辑关联 workspaces.id）。';
COMMENT ON COLUMN workspace_memberships.user_id IS '用户 ID（逻辑关联 users.id）。';
COMMENT ON COLUMN workspace_memberships.role IS '工作空间角色：ws_owner/ws_editor/ws_viewer。';
COMMENT ON COLUMN workspace_memberships.status IS '成员状态：active/invited/disabled。';
COMMENT ON COLUMN workspace_memberships.created_at IS '创建时间。';
COMMENT ON COLUMN workspace_memberships.updated_at IS '更新时间。';

-- knowledge_bases
COMMENT ON COLUMN knowledge_bases.id IS '主键 UUID。';
COMMENT ON COLUMN knowledge_bases.tenant_id IS '租户 ID（逻辑关联 tenants.id）。';
COMMENT ON COLUMN knowledge_bases.workspace_id IS '工作空间 ID（逻辑关联 workspaces.id）。';
COMMENT ON COLUMN knowledge_bases.name IS '知识库名称。';
COMMENT ON COLUMN knowledge_bases.description IS '知识库描述。';
COMMENT ON COLUMN knowledge_bases.embedding_model IS '默认向量模型标识。';
COMMENT ON COLUMN knowledge_bases.retrieval_strategy IS '检索策略配置 JSON。';
COMMENT ON COLUMN knowledge_bases.status IS '知识库状态：active/archived。';
COMMENT ON COLUMN knowledge_bases.created_by IS '创建人用户 ID。';
COMMENT ON COLUMN knowledge_bases.created_at IS '创建时间。';
COMMENT ON COLUMN knowledge_bases.updated_at IS '更新时间。';

-- kb_memberships
COMMENT ON COLUMN kb_memberships.id IS '主键 UUID。';
COMMENT ON COLUMN kb_memberships.tenant_id IS '租户 ID（冗余字段，便于过滤）。';
COMMENT ON COLUMN kb_memberships.kb_id IS '知识库 ID（逻辑关联 knowledge_bases.id）。';
COMMENT ON COLUMN kb_memberships.user_id IS '用户 ID（逻辑关联 users.id）。';
COMMENT ON COLUMN kb_memberships.role IS '知识库角色：kb_owner/kb_editor/kb_viewer。';
COMMENT ON COLUMN kb_memberships.status IS '成员状态：active/invited/disabled。';
COMMENT ON COLUMN kb_memberships.created_at IS '创建时间。';
COMMENT ON COLUMN kb_memberships.updated_at IS '更新时间。';

-- documents
COMMENT ON COLUMN documents.id IS '主键 UUID。';
COMMENT ON COLUMN documents.tenant_id IS '租户 ID（逻辑关联 tenants.id）。';
COMMENT ON COLUMN documents.workspace_id IS '工作空间 ID（逻辑关联 workspaces.id）。';
COMMENT ON COLUMN documents.kb_id IS '知识库 ID（逻辑关联 knowledge_bases.id）。';
COMMENT ON COLUMN documents.title IS '文档标题。';
COMMENT ON COLUMN documents.source_type IS '来源类型：upload/url/notion/git。';
COMMENT ON COLUMN documents.source_uri IS '来源 URI 或对象名。';
COMMENT ON COLUMN documents.current_version IS '当前生效版本号。';
COMMENT ON COLUMN documents.status IS '文档状态：pending/processing/ready/failed/deleted。';
COMMENT ON COLUMN documents.metadata IS '文档扩展元数据 JSON。';
COMMENT ON COLUMN documents.created_by IS '创建人用户 ID。';
COMMENT ON COLUMN documents.created_at IS '创建时间。';
COMMENT ON COLUMN documents.updated_at IS '更新时间。';

-- document_versions
COMMENT ON COLUMN document_versions.id IS '主键 UUID。';
COMMENT ON COLUMN document_versions.tenant_id IS '租户 ID。';
COMMENT ON COLUMN document_versions.document_id IS '文档 ID。';
COMMENT ON COLUMN document_versions.version IS '文档版本号（同文档内递增）。';
COMMENT ON COLUMN document_versions.object_key IS '对象存储键。';
COMMENT ON COLUMN document_versions.parser_type IS '解析器类型。';
COMMENT ON COLUMN document_versions.parse_status IS '解析状态：pending/success/failed。';
COMMENT ON COLUMN document_versions.checksum IS '内容校验和。';
COMMENT ON COLUMN document_versions.created_at IS '创建时间。';

-- document_chunks
COMMENT ON COLUMN document_chunks.id IS '主键 UUID。';
COMMENT ON COLUMN document_chunks.tenant_id IS '租户 ID。';
COMMENT ON COLUMN document_chunks.workspace_id IS '工作空间 ID。';
COMMENT ON COLUMN document_chunks.kb_id IS '知识库 ID。';
COMMENT ON COLUMN document_chunks.document_id IS '文档 ID。';
COMMENT ON COLUMN document_chunks.document_version_id IS '文档版本 ID。';
COMMENT ON COLUMN document_chunks.chunk_no IS '切片序号。';
COMMENT ON COLUMN document_chunks.parent_chunk_id IS '父切片 ID。';
COMMENT ON COLUMN document_chunks.title_path IS '标题层级路径。';
COMMENT ON COLUMN document_chunks.content IS '切片文本内容。';
COMMENT ON COLUMN document_chunks.token_count IS 'token 粗略统计。';
COMMENT ON COLUMN document_chunks.metadata IS '切片元数据 JSON。';
COMMENT ON COLUMN document_chunks.created_at IS '创建时间。';

-- chunk_embeddings
COMMENT ON COLUMN chunk_embeddings.chunk_id IS '切片 ID（与 document_chunks.id 一对一逻辑关系）。';
COMMENT ON COLUMN chunk_embeddings.tenant_id IS '租户 ID。';
COMMENT ON COLUMN chunk_embeddings.kb_id IS '知识库 ID。';
COMMENT ON COLUMN chunk_embeddings.embedding_model IS '向量模型标识。';
COMMENT ON COLUMN chunk_embeddings.vector IS '向量值（1536 维）。';
COMMENT ON COLUMN chunk_embeddings.created_at IS '创建时间。';

-- ingestion_jobs
COMMENT ON COLUMN ingestion_jobs.id IS '主键 UUID。';
COMMENT ON COLUMN ingestion_jobs.tenant_id IS '租户 ID。';
COMMENT ON COLUMN ingestion_jobs.workspace_id IS '工作空间 ID。';
COMMENT ON COLUMN ingestion_jobs.kb_id IS '知识库 ID。';
COMMENT ON COLUMN ingestion_jobs.document_id IS '文档 ID。';
COMMENT ON COLUMN ingestion_jobs.document_version_id IS '文档版本 ID。';
COMMENT ON COLUMN ingestion_jobs.idempotency_key IS '幂等键。';
COMMENT ON COLUMN ingestion_jobs.status IS '任务状态：queued/processing/retrying/completed/dead_letter。';
COMMENT ON COLUMN ingestion_jobs.stage IS '任务阶段。';
COMMENT ON COLUMN ingestion_jobs.progress IS '任务进度（0-100）。';
COMMENT ON COLUMN ingestion_jobs.attempt_count IS '已尝试次数。';
COMMENT ON COLUMN ingestion_jobs.max_attempts IS '最大尝试次数。';
COMMENT ON COLUMN ingestion_jobs.next_run_at IS '下次可执行时间。';
COMMENT ON COLUMN ingestion_jobs.locked_at IS '锁定时间。';
COMMENT ON COLUMN ingestion_jobs.locked_by IS '持锁工作进程标识。';
COMMENT ON COLUMN ingestion_jobs.heartbeat_at IS '最近心跳时间。';
COMMENT ON COLUMN ingestion_jobs.started_at IS '开始执行时间。';
COMMENT ON COLUMN ingestion_jobs.finished_at IS '结束时间。';
COMMENT ON COLUMN ingestion_jobs.error IS '错误摘要。';
COMMENT ON COLUMN ingestion_jobs.created_at IS '创建时间。';
COMMENT ON COLUMN ingestion_jobs.updated_at IS '更新时间。';

-- retrieval_logs
COMMENT ON COLUMN retrieval_logs.id IS '主键 UUID。';
COMMENT ON COLUMN retrieval_logs.tenant_id IS '租户 ID。';
COMMENT ON COLUMN retrieval_logs.user_id IS '查询用户 ID。';
COMMENT ON COLUMN retrieval_logs.query_text IS '查询文本。';
COMMENT ON COLUMN retrieval_logs.kb_ids IS '命中范围知识库 ID 列表。';
COMMENT ON COLUMN retrieval_logs.top_k IS '请求 top_k。';
COMMENT ON COLUMN retrieval_logs.filter_json IS '检索过滤参数 JSON。';
COMMENT ON COLUMN retrieval_logs.result_chunks IS '检索结果快照 JSON。';
COMMENT ON COLUMN retrieval_logs.latency_ms IS '检索耗时毫秒。';
COMMENT ON COLUMN retrieval_logs.created_at IS '创建时间。';

-- user_credentials
COMMENT ON COLUMN user_credentials.id IS '主键 UUID。';
COMMENT ON COLUMN user_credentials.user_id IS '用户 ID。';
COMMENT ON COLUMN user_credentials.password_hash IS '密码哈希。';
COMMENT ON COLUMN user_credentials.status IS '凭据状态（active/disabled）。';
COMMENT ON COLUMN user_credentials.password_updated_at IS '最近修改密码时间。';
COMMENT ON COLUMN user_credentials.created_at IS '创建时间。';
COMMENT ON COLUMN user_credentials.updated_at IS '更新时间。';

-- user_mfa_totp
COMMENT ON COLUMN user_mfa_totp.id IS '主键 UUID。';
COMMENT ON COLUMN user_mfa_totp.user_id IS '用户 ID。';
COMMENT ON COLUMN user_mfa_totp.secret_base32 IS 'TOTP 密钥（Base32 编码）。';
COMMENT ON COLUMN user_mfa_totp.enabled IS '是否启用 MFA。';
COMMENT ON COLUMN user_mfa_totp.verified_at IS '首次验证通过时间。';
COMMENT ON COLUMN user_mfa_totp.backup_codes_hashes IS '备用恢复码哈希数组(JSON 字符串)。';
COMMENT ON COLUMN user_mfa_totp.last_used_counter IS '最近一次使用的 TOTP 计数器。';
COMMENT ON COLUMN user_mfa_totp.created_at IS '创建时间。';
COMMENT ON COLUMN user_mfa_totp.updated_at IS '更新时间。';

-- tenant_role_permissions
COMMENT ON COLUMN tenant_role_permissions.id IS '主键 UUID。';
COMMENT ON COLUMN tenant_role_permissions.tenant_id IS '租户 ID。';
COMMENT ON COLUMN tenant_role_permissions.role IS '角色（owner/admin/member/viewer）。';
COMMENT ON COLUMN tenant_role_permissions.permission_code IS '权限点编码（api/menu/button/feature）。';
COMMENT ON COLUMN tenant_role_permissions.created_at IS '创建时间。';
COMMENT ON COLUMN tenant_role_permissions.updated_at IS '更新时间。';

-- audit_logs
COMMENT ON COLUMN audit_logs.id IS '主键 UUID。';
COMMENT ON COLUMN audit_logs.tenant_id IS '租户 ID。';
COMMENT ON COLUMN audit_logs.actor_user_id IS '操作人用户 ID。';
COMMENT ON COLUMN audit_logs.action IS '动作编码。';
COMMENT ON COLUMN audit_logs.resource_type IS '资源类型。';
COMMENT ON COLUMN audit_logs.resource_id IS '资源标识。';
COMMENT ON COLUMN audit_logs.before_json IS '变更前快照。';
COMMENT ON COLUMN audit_logs.after_json IS '变更后快照。';
COMMENT ON COLUMN audit_logs.ip IS '客户端 IP。';
COMMENT ON COLUMN audit_logs.user_agent IS '客户端 UA。';
COMMENT ON COLUMN audit_logs.created_at IS '创建时间。';

-- conversations
COMMENT ON COLUMN conversations.id IS '主键 UUID。';
COMMENT ON COLUMN conversations.tenant_id IS '租户 ID。';
COMMENT ON COLUMN conversations.user_id IS '会话所属用户 ID。';
COMMENT ON COLUMN conversations.title IS '会话标题。';
COMMENT ON COLUMN conversations.kb_scope IS '会话知识范围 JSON。';
COMMENT ON COLUMN conversations.created_at IS '创建时间。';
COMMENT ON COLUMN conversations.updated_at IS '更新时间。';

-- messages
COMMENT ON COLUMN messages.id IS '主键 UUID。';
COMMENT ON COLUMN messages.tenant_id IS '租户 ID。';
COMMENT ON COLUMN messages.conversation_id IS '会话 ID。';
COMMENT ON COLUMN messages.role IS '消息角色：user/assistant/tool/system。';
COMMENT ON COLUMN messages.content IS '消息内容。';
COMMENT ON COLUMN messages.citations IS '引用来源列表 JSON。';
COMMENT ON COLUMN messages.usage IS 'token/耗时等用量 JSON。';
COMMENT ON COLUMN messages.created_at IS '创建时间。';

-- agent_runs
COMMENT ON COLUMN agent_runs.id IS '主键 UUID。';
COMMENT ON COLUMN agent_runs.tenant_id IS '租户 ID。';
COMMENT ON COLUMN agent_runs.user_id IS '任务发起用户 ID。';
COMMENT ON COLUMN agent_runs.conversation_id IS '关联会话 ID。';
COMMENT ON COLUMN agent_runs.plan_json IS '智能体规划结果 JSON。';
COMMENT ON COLUMN agent_runs.tool_calls IS '工具调用轨迹 JSON。';
COMMENT ON COLUMN agent_runs.status IS '任务状态：queued/running/success/failed/blocked/canceled。';
COMMENT ON COLUMN agent_runs.cost IS '任务成本估算。';
COMMENT ON COLUMN agent_runs.started_at IS '开始执行时间。';
COMMENT ON COLUMN agent_runs.finished_at IS '结束执行时间。';
COMMENT ON COLUMN agent_runs.created_at IS '创建时间。';
COMMENT ON COLUMN agent_runs.updated_at IS '更新时间。';

-- ============================================================================
-- 初始数据
-- ============================================================================

-- 为“尚未配置权限”的租户角色写入默认权限点。
-- 规则：同一 tenant+role 已有任意权限点时，不做覆盖。

WITH role_defaults(role, permission_code) AS (
    VALUES
        -- owner: 全量 API + 全量 UI 权限
        ('owner', 'api.tenant.read'),
        ('owner', 'api.tenant.update'),
        ('owner', 'api.tenant.delete'),
        ('owner', 'api.tenant.member.manage'),
        ('owner', 'api.user.read'),
        ('owner', 'api.user.update'),
        ('owner', 'api.workspace.create'),
        ('owner', 'api.workspace.read'),
        ('owner', 'api.workspace.update'),
        ('owner', 'api.workspace.delete'),
        ('owner', 'api.workspace.member.manage'),
        ('owner', 'api.kb.create'),
        ('owner', 'api.kb.read'),
        ('owner', 'api.kb.update'),
        ('owner', 'api.kb.delete'),
        ('owner', 'api.kb.member.manage'),
        ('owner', 'api.document.read'),
        ('owner', 'api.document.write'),
        ('owner', 'api.document.delete'),
        ('owner', 'api.retrieval.query'),
        ('owner', 'api.chat.completion'),
        ('owner', 'api.agent.run.create'),
        ('owner', 'api.agent.run.read'),
        ('owner', 'api.agent.run.cancel'),
        ('owner', 'api.governance.deletion.request.create'),
        ('owner', 'api.governance.deletion.request.read'),
        ('owner', 'api.governance.deletion.request.review'),
        ('owner', 'api.governance.deletion.execute'),
        ('owner', 'api.governance.retention.cleanup'),
        ('owner', 'api.governance.pii.mask'),
        ('owner', 'menu.tenant'),
        ('owner', 'menu.workspace'),
        ('owner', 'menu.kb'),
        ('owner', 'menu.document'),
        ('owner', 'menu.user'),
        ('owner', 'button.tenant.update'),
        ('owner', 'button.tenant.delete'),
        ('owner', 'button.workspace.create'),
        ('owner', 'button.workspace.update'),
        ('owner', 'button.workspace.delete'),
        ('owner', 'button.kb.create'),
        ('owner', 'button.kb.update'),
        ('owner', 'button.kb.delete'),
        ('owner', 'button.document.upload'),
        ('owner', 'button.document.update'),
        ('owner', 'button.document.delete'),
        ('owner', 'button.member.add'),
        ('owner', 'button.member.remove'),
        ('owner', 'feature.auth.permissions'),

        -- admin: 不含 tenant.delete，其余同 owner
        ('admin', 'api.tenant.read'),
        ('admin', 'api.tenant.update'),
        ('admin', 'api.tenant.member.manage'),
        ('admin', 'api.user.read'),
        ('admin', 'api.user.update'),
        ('admin', 'api.workspace.create'),
        ('admin', 'api.workspace.read'),
        ('admin', 'api.workspace.update'),
        ('admin', 'api.workspace.delete'),
        ('admin', 'api.workspace.member.manage'),
        ('admin', 'api.kb.create'),
        ('admin', 'api.kb.read'),
        ('admin', 'api.kb.update'),
        ('admin', 'api.kb.delete'),
        ('admin', 'api.kb.member.manage'),
        ('admin', 'api.document.read'),
        ('admin', 'api.document.write'),
        ('admin', 'api.document.delete'),
        ('admin', 'api.retrieval.query'),
        ('admin', 'api.chat.completion'),
        ('admin', 'api.agent.run.create'),
        ('admin', 'api.agent.run.read'),
        ('admin', 'api.agent.run.cancel'),
        ('admin', 'api.governance.deletion.request.create'),
        ('admin', 'api.governance.deletion.request.read'),
        ('admin', 'api.governance.deletion.request.review'),
        ('admin', 'api.governance.deletion.execute'),
        ('admin', 'api.governance.retention.cleanup'),
        ('admin', 'api.governance.pii.mask'),
        ('admin', 'menu.tenant'),
        ('admin', 'menu.workspace'),
        ('admin', 'menu.kb'),
        ('admin', 'menu.document'),
        ('admin', 'menu.user'),
        ('admin', 'button.tenant.update'),
        ('admin', 'button.tenant.delete'),
        ('admin', 'button.workspace.create'),
        ('admin', 'button.workspace.update'),
        ('admin', 'button.workspace.delete'),
        ('admin', 'button.kb.create'),
        ('admin', 'button.kb.update'),
        ('admin', 'button.kb.delete'),
        ('admin', 'button.document.upload'),
        ('admin', 'button.document.update'),
        ('admin', 'button.document.delete'),
        ('admin', 'button.member.add'),
        ('admin', 'button.member.remove'),
        ('admin', 'feature.auth.permissions'),

        -- member: 基础协作能力
        ('member', 'api.tenant.read'),
        ('member', 'api.workspace.create'),
        ('member', 'api.workspace.read'),
        ('member', 'api.kb.read'),
        ('member', 'api.document.read'),
        ('member', 'api.retrieval.query'),
        ('member', 'api.chat.completion'),
        ('member', 'api.agent.run.create'),
        ('member', 'api.agent.run.read'),
        ('member', 'api.agent.run.cancel'),
        ('member', 'api.governance.deletion.request.create'),
        ('member', 'api.governance.deletion.request.read'),
        ('member', 'api.governance.pii.mask'),
        ('member', 'menu.workspace'),
        ('member', 'menu.kb'),
        ('member', 'menu.document'),
        ('member', 'button.document.upload'),
        ('member', 'button.document.update'),
        ('member', 'button.document.delete'),

        -- viewer: 只读能力
        ('viewer', 'api.tenant.read'),
        ('viewer', 'api.workspace.read'),
        ('viewer', 'api.kb.read'),
        ('viewer', 'api.document.read'),
        ('viewer', 'api.retrieval.query'),
        ('viewer', 'api.chat.completion'),
        ('viewer', 'api.agent.run.create'),
        ('viewer', 'api.agent.run.read'),
        ('viewer', 'api.agent.run.cancel'),
        ('viewer', 'api.governance.deletion.request.create'),
        ('viewer', 'api.governance.deletion.request.read'),
        ('viewer', 'api.governance.pii.mask'),
        ('viewer', 'menu.workspace'),
        ('viewer', 'menu.kb'),
        ('viewer', 'menu.document')
),
candidate_roles AS (
    SELECT
        t.id AS tenant_id,
        r.role AS role
    FROM tenants AS t
    CROSS JOIN (VALUES ('owner'), ('admin'), ('member'), ('viewer')) AS r(role)
    WHERE NOT EXISTS (
        SELECT 1
        FROM tenant_role_permissions AS p
        WHERE p.tenant_id = t.id
          AND p.role = r.role
    )
)
INSERT INTO tenant_role_permissions (
    id,
    tenant_id,
    role,
    permission_code,
    created_at,
    updated_at
)
SELECT
    gen_random_uuid(),
    c.tenant_id,
    c.role,
    d.permission_code,
    NOW(),
    NOW()
FROM candidate_roles AS c
JOIN role_defaults AS d
  ON d.role = c.role
ON CONFLICT (tenant_id, role, permission_code) DO NOTHING;
