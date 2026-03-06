-- Row Level Security (RLS) 配置
-- 为多租户数据隔离提供数据库层面的安全保障

-- 启用 RLS 的表列表
-- 所有包含 tenant_id 的业务表都应启用 RLS

-- 1. 启用 tenants 表的 RLS
ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;

-- 租户只能访问自己的记录
CREATE POLICY tenant_isolation_policy ON tenants
    FOR ALL
    USING (id = current_setting('app.current_tenant_id', true)::uuid);

-- 2. 启用 users 表的 RLS
ALTER TABLE users ENABLE ROW LEVEL SECURITY;

-- 用户可以访问自己的记录
CREATE POLICY user_self_access_policy ON users
    FOR ALL
    USING (id = current_setting('app.current_user_id', true)::uuid);

-- 3. 启用 tenant_memberships 表的 RLS
ALTER TABLE tenant_memberships ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的成员关系
CREATE POLICY tenant_membership_isolation_policy ON tenant_memberships
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 4. 启用 workspaces 表的 RLS
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的工作空间
CREATE POLICY workspace_isolation_policy ON workspaces
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 5. 启用 knowledge_bases 表的 RLS
ALTER TABLE knowledge_bases ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的知识库
CREATE POLICY kb_isolation_policy ON knowledge_bases
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 6. 启用 kb_memberships 表的 RLS
ALTER TABLE kb_memberships ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户知识库的成员关系
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
CREATE POLICY document_isolation_policy ON documents
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 8. 启用 document_versions 表的 RLS
ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户知识库的文档版本
CREATE POLICY document_version_isolation_policy ON document_versions
    FOR ALL
    USING (
        kb_id IN (
            SELECT id FROM knowledge_bases
            WHERE tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
    );

-- 9. 启用 document_chunks 表的 RLS
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的文档切片
CREATE POLICY document_chunk_isolation_policy ON document_chunks
    FOR ALL
    USING (
        document_version_id IN (
            SELECT dv.id FROM document_versions dv
            JOIN knowledge_bases kb ON dv.kb_id = kb.id
            WHERE kb.tenant_id = current_setting('app.current_tenant_id', true)::uuid
        )
    );

-- 10. 启用 conversations 表的 RLS
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的对话
CREATE POLICY conversation_isolation_policy ON conversations
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 11. 启用 messages 表的 RLS
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户对话的消息
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
CREATE POLICY agent_run_isolation_policy ON agent_runs
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 13. 启用 audit_logs 表的 RLS
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的审计日志
CREATE POLICY audit_log_isolation_policy ON audit_logs
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 14. 启用 retrieval_logs 表的 RLS
ALTER TABLE retrieval_logs ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的检索日志
CREATE POLICY retrieval_log_isolation_policy ON retrieval_logs
    FOR ALL
    USING (tenant_id = current_setting('app.current_tenant_id', true)::uuid);

-- 15. 启用 ingestion_jobs 表的 RLS
ALTER TABLE ingestion_jobs ENABLE ROW LEVEL SECURITY;

-- 只能访问当前租户的接入任务
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
