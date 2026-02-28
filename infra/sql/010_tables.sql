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
    CONSTRAINT uk_tenants_slug UNIQUE (slug),
    CONSTRAINT ck_tenants_status CHECK (status IN ('active', 'suspended', 'deleted'))
);

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
    CONSTRAINT uk_workspace_slug UNIQUE (tenant_id, slug),
    CONSTRAINT ck_workspaces_status CHECK (status IN ('active', 'archived'))
);

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
    CONSTRAINT uk_kb_name UNIQUE (tenant_id, workspace_id, name),
    CONSTRAINT ck_knowledge_bases_status CHECK (status IN ('active', 'archived'))
);

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
