"""运维与评测请求结构。"""

from pydantic import BaseModel, Field
from uuid import UUID


class RetrievalEvalSampleRequest(BaseModel):
    """单条检索评测样本。"""

    query: str = Field(min_length=1, description="检索问题。")
    expected_terms: list[str] = Field(default_factory=list, description="预期命中关键字列表。")


class RetrievalEvalRequest(BaseModel):
    """检索评测请求体。"""

    kb_ids: list[UUID] = Field(default_factory=list, description="评测限定知识库范围；为空表示当前用户可读范围。")
    top_k: int = Field(default=5, ge=1, le=20, description="每条样本的检索条数。")
    samples: list[RetrievalEvalSampleRequest] = Field(
        min_length=1,
        max_length=100,
        description="评测样本列表。",
    )


class RetrievalEvalRunCreateRequest(RetrievalEvalRequest):
    """创建检索评测运行请求体。"""

    name: str = Field(default="adhoc", min_length=1, max_length=128, description="评测任务名称。")


class QuotaPolicyUpsertRequest(BaseModel):
    """配额策略创建/更新请求体。"""

    metric_code: str = Field(min_length=1, max_length=64, description="配额指标编码。")
    scope_type: str = Field(default="tenant", description="配额范围类型（tenant/workspace）。")
    scope_id: UUID | None = Field(default=None, description="范围 ID。scope_type=workspace 时必填。")
    limit_value: int = Field(ge=0, le=10_000_000, description="窗口内允许上限。")
    window_minutes: int = Field(default=1440, ge=1, le=10080, description="统计窗口分钟数。")
    enabled: bool = Field(default=True, description="是否启用策略。")


class IncidentTicketCreateRequest(BaseModel):
    """创建异常工单请求。"""

    source_code: str = Field(min_length=1, max_length=64, description="异常来源编码。")
    severity: str = Field(default="warn", description="严重级别（info/warn/critical）。")
    title: str = Field(min_length=1, max_length=256, description="工单标题。")
    summary: str = Field(min_length=1, description="异常摘要。")
    diagnosis: dict = Field(default_factory=dict, description="结构化诊断详情。")
    context: dict = Field(default_factory=dict, description="关联上下文。")


class IncidentTicketUpdateRequest(BaseModel):
    """更新异常工单请求。"""

    status: str | None = Field(default=None, description="工单状态（open/acknowledged/resolved）。")
    assignee_user_id: UUID | None = Field(default=None, description="处理人用户 ID。")
    resolution_note: str | None = Field(default=None, max_length=4000, description="处理结论。")


class AlertWebhookUpsertRequest(BaseModel):
    """告警 webhook 创建/更新请求。"""

    name: str = Field(min_length=1, max_length=64, description="订阅名称。")
    url: str = Field(min_length=1, max_length=2000, description="webhook 地址。")
    secret: str | None = Field(default=None, max_length=256, description="可选签名密钥。")
    enabled: bool = Field(default=True, description="是否启用。")
    event_types: list[str] = Field(default_factory=list, description="订阅事件类型，为空表示全部事件。")
    timeout_seconds: int = Field(default=3, ge=1, le=30, description="通知超时时间（秒）。")


class AlertDispatchRequest(BaseModel):
    """告警分发请求。"""

    event_type: str = Field(min_length=1, max_length=64, description="告警事件类型。")
    severity: str = Field(default="warn", description="告警等级（info/warn/critical）。")
    title: str = Field(min_length=1, max_length=256, description="告警标题。")
    message: str = Field(min_length=1, description="告警内容。")
    attributes: dict = Field(default_factory=dict, description="扩展属性。")
    dry_run: bool = Field(default=True, description="是否仅演练不实际发送。")
