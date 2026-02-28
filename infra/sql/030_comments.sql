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
