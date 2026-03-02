"""接口成功响应 `data` 字段结构定义。

说明：
1. 所有业务接口统一返回 `SuccessResponse[data=...]`。
2. 本文件专注于定义各接口在 `data` 中的业务字段。
3. 字段描述会直接用于 Swagger 展示，便于联调时理解含义。
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from tkp_api.schemas.common import BaseSchema


class HealthStatusData(BaseSchema):
    """健康检查返回结构。"""

    status: str = Field(description="健康状态值，常见为 ok 或 ready。")


class AuthUserProfile(BaseSchema):
    """当前登录用户的基础资料。"""

    id: UUID = Field(description="用户主键 ID。")
    email: str = Field(description="用户邮箱。")
    display_name: str = Field(description="用户展示名。")
    status: str = Field(description="用户状态，例如 active。")
    auth_provider: str = Field(description="认证来源，例如 JWT 签发方。")
    external_subject: str = Field(description="外部身份系统中的主体标识。")
    last_login_at: datetime | None = Field(default=None, description="最近一次登录时间。")


class TenantAccessItem(BaseSchema):
    """当前用户在某个租户下的访问视图。"""

    tenant_id: UUID = Field(description="租户 ID。")
    name: str = Field(description="租户名称。")
    slug: str = Field(description="租户短标识。")
    role: str = Field(description="当前用户在该租户中的角色。")
    status: str = Field(description="成员关系状态，例如 active。")


class WorkspaceAccessItem(BaseSchema):
    """当前用户在某个工作空间下的访问视图。"""

    workspace_id: UUID = Field(description="工作空间 ID。")
    tenant_id: UUID = Field(description="工作空间所属租户 ID。")
    name: str = Field(description="工作空间名称。")
    slug: str = Field(description="工作空间短标识。")
    role: str = Field(description="当前用户在该工作空间中的角色。")
    status: str = Field(description="成员关系状态，例如 active。")


class AuthMeData(BaseSchema):
    """`/auth/me` 接口返回的数据结构。"""

    user: AuthUserProfile = Field(description="当前登录用户信息。")
    tenants: list[TenantAccessItem] = Field(description="当前用户可访问的租户集合。")
    workspaces: list[WorkspaceAccessItem] = Field(description="当前用户可访问的工作空间集合。")


class PermissionSnapshotData(BaseSchema):
    """当前租户权限快照结构。"""

    tenant_role: str = Field(description="当前用户在租户中的角色。")
    allowed_actions: list[str] = Field(description="当前租户角色允许的动作列表。")


class PermissionCatalogData(BaseSchema):
    """权限目录结构。"""

    permission_codes: list[str] = Field(description="可用权限点编码列表。")


class PermissionUIItemData(BaseSchema):
    """单个前端权限项结构。"""

    code: str = Field(description="前端权限编码，例如 menu.workspace。")
    name: str = Field(description="前端展示名称。")
    required_actions: list[str] = Field(description="该前端能力依赖的后端动作权限集合。")
    allowed: bool = Field(description="当前角色是否允许展示/启用该能力。")


class PermissionUIManifestData(BaseSchema):
    """前端权限映射契约结构。"""

    version: str = Field(description="权限契约版本号，用于前后端兼容控制。")
    tenant_role: str = Field(description="当前用户在租户中的角色。")
    allowed_actions: list[str] = Field(description="当前角色最终生效的权限码集合。")
    menus: list[PermissionUIItemData] = Field(description="菜单权限映射列表。")
    buttons: list[PermissionUIItemData] = Field(description="按钮权限映射列表。")
    features: list[PermissionUIItemData] = Field(description="功能开关权限映射列表。")


class TenantRolePermissionData(BaseSchema):
    """单个角色权限映射结构。"""

    role: str = Field(description="角色标识。")
    permission_codes: list[str] = Field(description="该角色拥有的权限点编码列表。")


class PermissionTemplateData(BaseSchema):
    """权限模板结构。"""

    template_key: str = Field(description="模板标识。")
    version: str = Field(description="模板版本。")
    catalog: list[str] = Field(description="模板对应白名单权限目录。")
    role_permissions: list[TenantRolePermissionData] = Field(description="模板角色权限映射。")


class PermissionTemplatePublishData(BaseSchema):
    """模板发布结果结构。"""

    template_key: str = Field(description="模板标识。")
    version: str = Field(description="模板版本。")
    overwrite_existing: bool = Field(description="是否覆盖了已有租户角色权限。")
    role_permissions: list[TenantRolePermissionData] = Field(description="发布后的租户角色权限映射。")


class RoleUserBindingData(BaseSchema):
    """角色用户绑定结构。"""

    role: str = Field(description="角色标识。")
    tenant_id: UUID = Field(description="租户 ID。")
    user_id: UUID = Field(description="用户 ID。")
    email: str = Field(description="用户邮箱。")
    display_name: str = Field(description="用户展示名。")
    membership_status: str = Field(description="成员关系状态。")


class RoleOverviewData(BaseSchema):
    """角色关系总览结构。"""

    role: str = Field(description="角色标识。")
    user_count: int = Field(description="该角色的成员数量。")
    permission_codes: list[str] = Field(description="该角色对应的权限点编码集合。")


class TenantCreateData(BaseSchema):
    """创建租户接口返回结构。"""

    tenant_id: UUID = Field(description="新建租户 ID。")
    name: str = Field(description="租户名称。")
    slug: str = Field(description="租户短标识。")
    role: str = Field(description="创建者在租户中的角色，通常为 owner。")
    default_workspace_id: UUID = Field(description="系统自动创建的默认工作空间 ID。")


class TenantData(BaseSchema):
    """租户详情结构。"""

    tenant_id: UUID = Field(description="租户 ID。")
    name: str = Field(description="租户名称。")
    slug: str = Field(description="租户短标识。")
    status: str = Field(description="租户状态。")
    role: str = Field(description="当前用户在该租户中的角色。")


class TenantMemberData(BaseSchema):
    """租户成员新增/更新返回结构。"""

    tenant_id: UUID = Field(description="租户 ID。")
    user_id: UUID = Field(description="成员用户 ID。")
    email: str = Field(description="成员邮箱。")
    role: str = Field(description="成员在租户中的角色。")
    status: str = Field(description="成员关系状态。")


class WorkspaceData(BaseSchema):
    """工作空间信息结构。"""

    id: UUID = Field(description="工作空间 ID。")
    name: str = Field(description="工作空间名称。")
    slug: str = Field(description="工作空间短标识。")
    description: str | None = Field(default=None, description="工作空间描述。")
    status: str = Field(description="工作空间状态。")
    role: str = Field(description="当前用户在该工作空间中的角色。")


class WorkspaceMemberData(BaseSchema):
    """工作空间成员新增/更新返回结构。"""

    workspace_id: UUID = Field(description="工作空间 ID。")
    user_id: UUID = Field(description="成员用户 ID。")
    role: str = Field(description="成员在工作空间中的角色。")
    status: str = Field(description="成员关系状态。")


class KnowledgeBaseData(BaseSchema):
    """知识库信息结构。"""

    id: UUID = Field(description="知识库 ID。")
    workspace_id: UUID = Field(description="所属工作空间 ID。")
    name: str = Field(description="知识库名称。")
    description: str | None = Field(default=None, description="知识库描述。")
    embedding_model: str = Field(description="默认向量模型标识。")
    status: str = Field(description="知识库状态。")
    role: str | None = Field(default=None, description="当前用户在该知识库中的角色。")


class KBMembershipData(BaseSchema):
    """知识库成员新增/更新返回结构。"""

    kb_id: UUID = Field(description="知识库 ID。")
    user_id: UUID = Field(description="成员用户 ID。")
    role: str = Field(description="成员在知识库中的角色。")
    status: str = Field(description="成员关系状态。")


class DocumentData(BaseSchema):
    """文档基础信息结构。"""

    id: UUID = Field(description="文档 ID。")
    workspace_id: UUID = Field(description="文档所属工作空间 ID。")
    kb_id: UUID = Field(description="文档所属知识库 ID。")
    title: str = Field(description="文档标题。")
    source_type: str = Field(description="文档来源类型，例如 upload/url。")
    source_uri: str | None = Field(default=None, description="文档来源地址或文件名。")
    current_version: int = Field(description="当前版本号。")
    status: str = Field(description="文档状态。")
    metadata: dict[str, Any] | None = Field(default=None, description="文档元数据。")


class DocumentVersionData(BaseSchema):
    """文档版本信息结构。"""

    id: UUID = Field(description="文档版本 ID。")
    document_id: UUID = Field(description="所属文档 ID。")
    version: int = Field(description="文档版本号。")
    object_key: str | None = Field(default=None, description="对象存储键。")
    parser_type: str | None = Field(default=None, description="解析器类型。")
    parse_status: str = Field(description="解析状态。")
    checksum: str | None = Field(default=None, description="内容校验和。")
    created_at: datetime = Field(description="版本创建时间。")


class DocumentChunkData(BaseSchema):
    """文档切片信息结构。"""

    id: UUID = Field(description="切片 ID。")
    document_id: UUID = Field(description="所属文档 ID。")
    document_version_id: UUID = Field(description="所属文档版本 ID。")
    chunk_no: int = Field(description="切片序号。")
    title_path: str | None = Field(default=None, description="标题路径。")
    content: str = Field(description="切片内容。")
    token_count: int = Field(description="切片 token 数。")
    metadata: dict[str, Any] | None = Field(default=None, description="切片元数据。")
    created_at: datetime = Field(description="切片创建时间。")


class DocumentChunkPageData(BaseSchema):
    """文档切片分页结构。"""

    document_id: UUID = Field(description="文档 ID。")
    version: int = Field(description="查询的文档版本号。")
    document_version_id: UUID = Field(description="文档版本 ID。")
    total: int = Field(description="切片总数。")
    offset: int = Field(description="分页偏移。")
    limit: int = Field(description="分页大小。")
    items: list[DocumentChunkData] = Field(description="当前页切片列表。")


class TenantUserData(BaseSchema):
    """租户用户视图结构。"""

    user_id: UUID = Field(description="用户 ID。")
    email: str = Field(description="用户邮箱。")
    display_name: str = Field(description="用户展示名。")
    user_status: str = Field(description="用户状态。")
    tenant_role: str = Field(description="用户在当前租户中的角色。")
    membership_status: str = Field(description="用户在当前租户中的成员关系状态。")


class DocumentUploadData(BaseSchema):
    """上传文档接口返回结构。"""

    document_id: UUID = Field(description="文档 ID。")
    workspace_id: UUID = Field(description="文档所属工作空间 ID。")
    document_version_id: UUID = Field(description="本次上传生成的文档版本 ID。")
    version: int = Field(description="本次上传对应的版本号。")
    status: str = Field(description="文档状态。")
    job_id: UUID = Field(description="异步入库任务 ID。")
    job_status: str = Field(description="入库任务当前状态。")


class ReindexData(BaseSchema):
    """重建索引接口返回结构。"""

    job_id: UUID = Field(description="重建任务 ID。")
    status: str = Field(description="重建任务状态。")


class IngestionJobData(BaseSchema):
    """入库任务详情结构。"""

    job_id: UUID = Field(description="任务 ID。")
    workspace_id: UUID = Field(description="任务所属工作空间 ID。")
    document_id: UUID = Field(description="任务关联文档 ID。")
    document_version_id: UUID = Field(description="任务关联文档版本 ID。")
    status: str = Field(description="任务状态，例如 queued/processing/completed。")
    stage: str = Field(description="任务阶段标记，例如 loading/chunking/completed。")
    progress: int = Field(description="任务进度百分比（0-100）。")
    attempt_count: int = Field(description="当前已执行次数。")
    max_attempts: int = Field(description="最大允许执行次数。")
    next_run_at: datetime = Field(description="下次可执行时间。")
    locked_at: datetime | None = Field(default=None, description="任务被工作进程锁定的时间。")
    locked_by: str | None = Field(default=None, description="当前持锁工作进程标识。")
    heartbeat_at: datetime | None = Field(default=None, description="最近一次心跳时间。")
    started_at: datetime | None = Field(default=None, description="首次开始处理时间。")
    finished_at: datetime | None = Field(default=None, description="处理完成时间。")
    error: str | None = Field(default=None, description="最近一次错误信息。")
    terminal: bool = Field(description="是否为终态任务。")


class RetrievalHit(BaseSchema):
    """单条检索命中记录。"""

    chunk_id: UUID = Field(description="命中切片 ID。")
    document_id: UUID = Field(description="所属文档 ID。")
    document_version_id: UUID = Field(description="所属文档版本 ID。")
    kb_id: UUID = Field(description="所属知识库 ID。")
    score: int = Field(description="命中分数，分值越高代表相关性越高。")
    snippet: str = Field(description="切片摘要文本。")


class RetrievalQueryData(BaseSchema):
    """检索接口返回结构。"""

    hits: list[RetrievalHit] = Field(description="命中结果列表。")
    latency_ms: int = Field(description="检索耗时（毫秒）。")


class ChatCompletionData(BaseSchema):
    """问答接口返回结构。"""

    message_id: UUID = Field(description="助手回复消息 ID。")
    answer: str = Field(description="回答正文。")
    citations: list[dict[str, Any]] = Field(description="回答引用列表。")
    usage: dict[str, int] = Field(description="本次调用的 token 统计。")
    conversation_id: UUID = Field(description="会话 ID。")


class AgentRunData(BaseSchema):
    """智能体任务简要结构。"""

    run_id: UUID = Field(description="智能体任务 ID。")
    status: str = Field(description="智能体任务状态。")


class AgentRunDetailData(BaseSchema):
    """智能体任务详情结构。"""

    run_id: UUID = Field(description="智能体任务 ID。")
    status: str = Field(description="智能体任务状态。")
    plan_json: dict[str, Any] = Field(description="任务规划信息。")
    tool_calls: list[dict[str, Any]] = Field(description="工具调用记录。")
    cost: float = Field(description="任务累计成本估算。")
    started_at: datetime | None = Field(default=None, description="开始执行时间。")
    finished_at: datetime | None = Field(default=None, description="结束执行时间。")
