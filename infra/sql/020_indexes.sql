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
