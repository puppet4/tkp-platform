"""接口成功响应 `data` 字段结构定义。

说明：
1. 所有业务接口统一返回 `SuccessResponse[data=...]`。
2. 本文件专注于定义各接口在 `data` 中的业务字段。
3. 字段描述会直接用于 Swagger 展示，便于联调时理解含义。
"""

from __future__ import annotations

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


class PermissionPolicySnapshotData(BaseSchema):
    """权限策略快照结构。"""

    snapshot_id: UUID = Field(description="策略快照 ID。")
    template_version: str = Field(description="快照生成时使用的权限模板版本。")
    role_permissions: list[TenantRolePermissionData] = Field(description="快照角色权限映射。")
    note: str | None = Field(default=None, description="快照备注。")
    created_at: datetime = Field(description="快照创建时间。")


class PermissionPolicyCenterData(BaseSchema):
    """策略中心统一视图结构。"""

    template_version: str = Field(description="权限模板版本。")
    catalog: list[str] = Field(description="权限目录。")
    role_permissions: list[TenantRolePermissionData] = Field(description="租户角色权限矩阵。")
    ui_manifest: PermissionUIManifestData = Field(description="当前角色前端权限映射。")


class PermissionPolicyRollbackData(BaseSchema):
    """策略回滚结果结构。"""

    snapshot_id: UUID = Field(description="回滚使用的快照 ID。")
    role_permissions: list[TenantRolePermissionData] = Field(description="回滚后角色权限矩阵。")


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


class KnowledgeBaseStatsData(BaseSchema):
    """知识库运营统计结构。"""

    kb_id: UUID = Field(description="知识库 ID。")
    document_total: int = Field(description="文档总数（含 deleted）。")
    document_ready: int = Field(description="状态为 ready 的文档数。")
    document_processing: int = Field(description="状态为 processing 的文档数。")
    document_failed: int = Field(description="状态为 failed 的文档数。")
    document_deleted: int = Field(description="状态为 deleted 的文档数。")
    chunk_total: int = Field(description="切片总数。")
    job_total: int = Field(description="入库任务总数。")
    job_queued: int = Field(description="queued 状态任务数。")
    job_processing: int = Field(description="processing 状态任务数。")
    job_retrying: int = Field(description="retrying 状态任务数。")
    job_completed: int = Field(description="completed 状态任务数。")
    job_dead_letter: int = Field(description="dead_letter 状态任务数。")
    latest_job_created_at: datetime | None = Field(default=None, description="最近任务创建时间。")
    latest_job_finished_at: datetime | None = Field(default=None, description="最近任务完成时间。")
    latest_job_error: str | None = Field(default=None, description="最近失败任务错误摘要。")


class IngestionOpsMetricsData(BaseSchema):
    """入库运行态指标结构。"""

    tenant_id: UUID = Field(description="租户 ID。")
    window_hours: int = Field(description="统计窗口小时数。")
    queued: int = Field(description="queued 状态任务数。")
    processing: int = Field(description="processing 状态任务数。")
    retrying: int = Field(description="retrying 状态任务数。")
    completed: int = Field(description="completed 状态任务数。")
    dead_letter: int = Field(description="dead_letter 状态任务数。")
    backlog_total: int = Field(description="积压任务数（queued + retrying）。")
    completed_last_window: int = Field(description="窗口内 completed 数量。")
    dead_letter_last_window: int = Field(description="窗口内 dead_letter 数量。")
    failure_rate_last_window: float = Field(description="窗口内失败率（0-1）。")
    avg_latency_ms_last_window: int | None = Field(default=None, description="窗口内平均处理耗时（毫秒）。")
    p95_latency_ms_last_window: int | None = Field(default=None, description="窗口内 p95 处理耗时（毫秒）。")
    stale_processing_jobs: int = Field(description="疑似卡住的 processing 任务数。")


class IngestionOpsAlertRuleData(BaseSchema):
    """入库告警规则状态。"""

    code: str = Field(description="规则编码。")
    name: str = Field(description="规则名称。")
    status: str = Field(description="规则状态（ok/warn/critical）。")
    current: int | float = Field(description="当前指标值。")
    warn_threshold: int | float = Field(description="告警阈值。")
    critical_threshold: int | float = Field(description="严重告警阈值。")
    message: str = Field(description="规则说明。")


class IngestionOpsAlertsData(BaseSchema):
    """入库告警汇总结构。"""

    tenant_id: UUID = Field(description="租户 ID。")
    overall_status: str = Field(description="整体状态（ok/warn/critical）。")
    rules: list[IngestionOpsAlertRuleData] = Field(description="规则级告警状态。")


class QuotaPolicyData(BaseSchema):
    """配额策略结构。"""

    id: UUID = Field(description="配额策略 ID。")
    tenant_id: UUID = Field(description="租户 ID。")
    scope_type: str = Field(description="配额范围类型（tenant/workspace）。")
    scope_id: UUID = Field(description="配额范围 ID。")
    metric_code: str = Field(description="配额指标编码。")
    limit_value: int = Field(description="窗口内允许上限。")
    window_minutes: int = Field(description="统计窗口分钟数。")
    enabled: bool = Field(description="策略是否启用。")
    created_at: datetime = Field(description="创建时间。")
    updated_at: datetime = Field(description="更新时间。")


class QuotaAlertData(BaseSchema):
    """配额超限告警结构。"""

    alert_id: UUID = Field(description="告警事件 ID。")
    metric_code: str = Field(description="触发超限的指标编码。")
    scope_type: str = Field(description="配额范围类型。")
    scope_id: UUID = Field(description="配额范围 ID。")
    limit_value: int = Field(description="策略上限。")
    used_value: int = Field(description="触发前窗口内已使用值。")
    projected_value: int = Field(description="触发时预测使用值。")
    window_minutes: int = Field(description="统计窗口分钟数。")
    created_at: datetime = Field(description="告警时间。")


class CostSummaryData(BaseSchema):
    """租户成本汇总结构。"""

    tenant_id: UUID = Field(description="租户 ID。")
    window_hours: int = Field(description="统计窗口小时数。")
    retrieval_request_total: int = Field(description="窗口内检索请求总数。")
    chat_completion_total: int = Field(description="窗口内问答完成次数。")
    prompt_tokens_total: int = Field(description="窗口内 prompt token 总数。")
    completion_tokens_total: int = Field(description="窗口内 completion token 总数。")
    total_tokens: int = Field(description="窗口内总 token 数。")
    agent_run_total: int = Field(description="窗口内 agent run 总数。")
    agent_cost_total: float = Field(description="窗口内 agent 侧累计成本。")
    chat_estimated_cost: float = Field(description="基于 token 的问答估算成本。")
    estimated_total_cost: float = Field(description="窗口内估算总成本。")


class OpsOverviewData(BaseSchema):
    """运营后台概览结构。"""

    tenant_id: UUID = Field(description="租户 ID。")
    window_hours: int = Field(description="统计窗口小时数。")
    generated_at: datetime = Field(description="概览生成时间。")
    ingestion_alert_status: str = Field(description="入库告警整体状态（ok/warn/critical）。")
    ingestion_backlog_total: int = Field(description="当前入库积压任务总数。")
    ingestion_failure_rate: float = Field(description="窗口内入库失败率（0-1）。")
    retrieval_zero_hit_rate: float = Field(description="窗口内检索零命中率（0-1）。")
    estimated_total_cost: float = Field(description="窗口内估算总成本。")
    incident_open_total: int = Field(description="未关闭工单总数。")
    incident_critical_open_total: int = Field(description="未关闭 critical 工单总数。")
    webhook_enabled_total: int = Field(description="已启用 webhook 数量。")


class TenantHealthItemData(BaseSchema):
    """单个工作空间健康项。"""

    workspace_id: UUID = Field(description="工作空间 ID。")
    workspace_name: str = Field(description="工作空间名称。")
    workspace_status: str = Field(description="工作空间状态。")
    document_total: int = Field(description="文档总数。")
    document_ready: int = Field(description="可检索文档数。")
    document_ready_ratio: float = Field(description="可检索文档占比（0-1）。")
    dead_letter_jobs: int = Field(description="窗口内 dead-letter 任务数。")
    retrieval_queries: int = Field(description="窗口内检索请求数。")
    retrieval_zero_hit: int = Field(description="窗口内零命中请求数。")
    retrieval_zero_hit_rate: float = Field(description="窗口内零命中率（0-1）。")
    status: str = Field(description="健康状态（healthy/warn/critical）。")


class CostLeaderboardItemData(BaseSchema):
    """租户成本榜单项。"""

    user_id: UUID = Field(description="用户 ID。")
    display_name: str = Field(description="用户展示名。")
    email: str = Field(description="用户邮箱。")
    retrieval_requests: int = Field(description="窗口内检索请求数。")
    chat_total_tokens: int = Field(description="窗口内会话总 token 数。")
    agent_runs: int = Field(description="窗口内 agent 运行次数。")
    agent_cost_total: float = Field(description="窗口内 agent 累计成本。")
    estimated_total_cost: float = Field(description="窗口内估算总成本。")


class IncidentDiagnosisItemData(BaseSchema):
    """异常诊断项结构。"""

    source_code: str = Field(description="异常来源编码。")
    severity: str = Field(description="严重级别（info/warn/critical）。")
    title: str = Field(description="诊断标题。")
    summary: str = Field(description="诊断摘要。")
    suggestion: str = Field(description="建议动作。")
    context: dict[str, Any] = Field(default_factory=dict, description="诊断上下文。")


class IncidentTicketData(BaseSchema):
    """异常工单结构。"""

    ticket_id: UUID = Field(description="工单 ID。")
    tenant_id: UUID = Field(description="租户 ID。")
    source_code: str = Field(description="异常来源编码。")
    severity: str = Field(description="严重级别。")
    status: str = Field(description="工单状态。")
    title: str = Field(description="工单标题。")
    summary: str = Field(description="工单摘要。")
    diagnosis: dict[str, Any] = Field(default_factory=dict, description="结构化诊断详情。")
    context: dict[str, Any] = Field(default_factory=dict, description="关联上下文。")
    assignee_user_id: UUID | None = Field(default=None, description="处理人用户 ID。")
    resolution_note: str | None = Field(default=None, description="处理结论。")
    created_by: UUID | None = Field(default=None, description="工单创建人用户 ID。")
    resolved_at: str | None = Field(default=None, description="工单关闭时间（ISO8601）。")
    created_at: datetime = Field(description="创建时间。")
    updated_at: datetime = Field(description="更新时间。")


class AlertWebhookData(BaseSchema):
    """告警 webhook 订阅结构。"""

    webhook_id: UUID = Field(description="订阅 ID。")
    tenant_id: UUID = Field(description="租户 ID。")
    name: str = Field(description="订阅名称。")
    url: str = Field(description="webhook 地址。")
    enabled: bool = Field(description="是否启用。")
    event_types: list[str] = Field(description="订阅事件类型。")
    timeout_seconds: int = Field(description="通知超时时间（秒）。")
    last_status_code: int | None = Field(default=None, description="最近一次通知响应码。")
    last_error: str | None = Field(default=None, description="最近一次通知错误。")
    last_notified_at: str | None = Field(default=None, description="最近一次通知时间（ISO8601）。")
    created_at: datetime = Field(description="创建时间。")
    updated_at: datetime = Field(description="更新时间。")


class AlertDispatchResultItemData(BaseSchema):
    """单个 webhook 分发结果。"""

    webhook_id: UUID = Field(description="订阅 ID。")
    name: str = Field(description="订阅名称。")
    url: str = Field(description="webhook 地址。")
    status_code: int | None = Field(default=None, description="请求响应码。")
    delivered: bool = Field(description="是否发送成功。")
    error: str | None = Field(default=None, description="失败原因。")
    dry_run: bool = Field(description="是否演练模式。")


class AlertDispatchResultData(BaseSchema):
    """告警分发汇总结果。"""

    tenant_id: UUID = Field(description="租户 ID。")
    event_type: str = Field(description="事件类型。")
    severity: str = Field(description="告警等级。")
    dry_run: bool = Field(description="是否演练模式。")
    matched_webhook_total: int = Field(description="命中的 webhook 数量。")
    delivered_total: int = Field(description="实际发送成功数量。")
    results: list[AlertDispatchResultItemData] = Field(description="逐 webhook 分发结果。")


class RetrievalQualityMetricsData(BaseSchema):
    """检索质量指标结构。"""

    tenant_id: UUID = Field(description="租户 ID。")
    window_hours: int = Field(description="统计窗口小时数。")
    query_total: int = Field(description="窗口内检索请求总数。")
    query_with_hits: int = Field(description="窗口内至少有一条命中的请求数。")
    zero_hit_queries: int = Field(description="窗口内零命中请求数。")
    zero_hit_rate: float = Field(description="窗口内零命中率（0-1）。")
    hit_total: int = Field(description="窗口内命中切片总数。")
    hit_with_citation: int = Field(description="窗口内带 citation 的命中切片数。")
    citation_coverage_rate: float = Field(description="命中切片引用覆盖率（0-1）。")
    avg_latency_ms: int | None = Field(default=None, description="窗口内平均检索耗时（毫秒）。")
    p95_latency_ms: int | None = Field(default=None, description="窗口内检索 p95 耗时（毫秒）。")


class MVPSLOCheckData(BaseSchema):
    """MVP SLO 单项检查结构。"""

    code: str = Field(description="检查项编码。")
    name: str = Field(description="检查项名称。")
    status: str = Field(description="检查状态（pass/fail）。")
    current: int | float = Field(description="当前指标值。")
    target: int | float = Field(description="目标阈值。")
    operator: str = Field(description="比较操作符（<= 或 >=）。")


class MVPSLOSummaryData(BaseSchema):
    """MVP SLO 摘要结构。"""

    tenant_id: UUID = Field(description="租户 ID。")
    window_hours: int = Field(description="统计窗口小时数。")
    overall_status: str = Field(description="整体状态（pass/fail）。")
    checks: list[MVPSLOCheckData] = Field(description="SLO 检查列表。")
    ingestion_metrics: IngestionOpsMetricsData = Field(description="入库指标快照。")
    retrieval_quality: RetrievalQualityMetricsData = Field(description="检索质量指标快照。")


class RetrievalEvalItemData(BaseSchema):
    """单条检索评测结果。"""

    query: str = Field(description="检索问题。")
    expected_terms: list[str] = Field(description="预期命中关键字列表。")
    matched: bool = Field(description="是否命中预期。")
    hit_count: int = Field(description="命中切片数。")
    citation_covered: bool = Field(description="该样本命中是否全部具备引用信息。")
    top_hit_score: int | None = Field(default=None, description="第一条命中分值。")
    latency_ms: int = Field(description="检索耗时（毫秒）。")


class RetrievalEvalSummaryData(BaseSchema):
    """检索评测汇总结构。"""

    tenant_id: UUID = Field(description="租户 ID。")
    sample_total: int = Field(description="评测样本总数。")
    matched_total: int = Field(description="命中预期样本数。")
    hit_at_k: float = Field(description="命中率（0-1）。")
    citation_coverage_rate: float = Field(description="样本级引用覆盖率（0-1）。")
    avg_latency_ms: int | None = Field(default=None, description="平均检索耗时（毫秒）。")
    results: list[RetrievalEvalItemData] = Field(description="样本评测明细。")


class RetrievalEvalRunData(BaseSchema):
    """检索评测运行简要结构。"""

    run_id: UUID = Field(description="评测运行 ID。")
    name: str = Field(description="评测任务名称。")
    status: str = Field(description="评测运行状态。")
    sample_total: int = Field(description="评测样本总数。")
    matched_total: int = Field(description="命中预期样本数。")
    hit_at_k: float = Field(description="命中率（0-1）。")
    citation_coverage_rate: float = Field(description="样本级引用覆盖率（0-1）。")
    avg_latency_ms: int | None = Field(default=None, description="平均检索耗时（毫秒）。")
    created_at: datetime = Field(description="评测创建时间。")


class RetrievalEvalRunDetailData(RetrievalEvalRunData):
    """检索评测运行详情结构。"""

    results: list[RetrievalEvalItemData] = Field(description="样本评测明细。")


class RetrievalEvalCompareData(BaseSchema):
    """检索评测对比结构。"""

    tenant_id: UUID = Field(description="租户 ID。")
    baseline_run_id: UUID = Field(description="基线运行 ID。")
    current_run_id: UUID = Field(description="当前运行 ID。")
    delta_hit_at_k: float | None = Field(default=None, description="命中率差值（current - baseline）。")
    delta_citation_coverage_rate: float | None = Field(default=None, description="引用覆盖率差值（current - baseline）。")
    delta_avg_latency_ms: float | None = Field(default=None, description="平均耗时差值（current - baseline）。")
    improved: bool = Field(description="是否整体改善。")
    baseline: RetrievalEvalRunDetailData = Field(description="基线评测详情。")
    current: RetrievalEvalRunDetailData = Field(description="当前评测详情。")


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
    retryable: bool = Field(description="当前任务是否允许手工重试。")
    can_retry_now: bool = Field(description="当前时刻是否可立即重试。")
    retry_in_seconds: int = Field(description="距离可重试还有多少秒，0 表示可立即重试。")
    diagnosis: "IngestionJobDiagnosisData" = Field(description="任务诊断信息。")


class IngestionJobDiagnosisData(BaseSchema):
    """入库任务诊断结构。"""

    category: str = Field(description="诊断分类，例如 retrying/dead_letter/completed。")
    summary: str = Field(description="诊断摘要。")
    suggestion: str = Field(description="建议操作。")


class RetrievalScoreBreakdownData(BaseSchema):
    """检索得分拆解结构。"""

    vector_score: int = Field(description="向量召回分。")
    keyword_score: int = Field(description="关键词匹配分。")
    rerank_bonus: int = Field(description="重排加分。")
    final_score: int = Field(description="最终分。")


class RetrievalQueryRewriteData(BaseSchema):
    """检索查询改写结构。"""

    original_query: str = Field(description="原始查询。")
    rewritten_query: str = Field(description="改写后查询。")
    rewrite_applied: bool = Field(description="是否应用了改写规则。")


class RetrievalHit(BaseSchema):
    """单条检索命中记录。"""

    chunk_id: UUID = Field(description="命中切片 ID。")
    document_id: UUID = Field(description="所属文档 ID。")
    document_version_id: UUID = Field(description="所属文档版本 ID。")
    kb_id: UUID = Field(description="所属知识库 ID。")
    chunk_no: int = Field(description="切片序号。")
    title_path: str | None = Field(default=None, description="切片标题路径。")
    score: int = Field(description="命中分数，分值越高代表相关性越高。")
    match_type: str = Field(description="命中类型（vector/keyword/hybrid）。")
    snippet: str = Field(description="切片摘要文本。")
    metadata: dict[str, Any] | None = Field(default=None, description="切片 metadata 快照。")
    citation: dict[str, Any] | None = Field(default=None, description="引用定位信息。")
    reason: str = Field(description="命中原因说明。")
    matched_terms: list[str] = Field(description="命中的查询词列表。")
    score_breakdown: RetrievalScoreBreakdownData = Field(description="分数拆解。")


class RetrievalQueryData(BaseSchema):
    """检索接口返回结构。"""

    hits: list[RetrievalHit] = Field(description="命中结果列表。")
    latency_ms: int = Field(description="检索耗时（毫秒）。")
    retrieval_strategy: str = Field(description="本次检索生效策略（hybrid/vector/keyword）。")
    query_rewrite: RetrievalQueryRewriteData = Field(description="查询改写信息。")
    effective_min_score: int = Field(description="本次检索生效的最低分阈值。")
    rerank_applied: bool = Field(description="是否执行了重排增强。")


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
