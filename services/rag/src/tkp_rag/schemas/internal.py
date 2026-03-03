"""RAG 内部接口请求/响应模型。"""

from typing import Any
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class RetrievalQueryInternalRequest(BaseModel):
    """检索查询请求。"""

    tenant_id: UUID = Field(description="租户 ID。")
    kb_ids: list[UUID] = Field(default_factory=list, description="知识库范围。")
    query: str = Field(min_length=1, description="查询文本。")
    top_k: int = Field(default=8, ge=1, le=50, description="命中上限。")
    filters: dict[str, Any] = Field(default_factory=dict, description="metadata 过滤条件。")
    with_citations: bool = Field(default=True, description="是否返回 citation。")
    retrieval_strategy: Literal["hybrid", "vector", "keyword"] = Field(
        default="hybrid",
        description="检索策略。",
    )
    min_score: int = Field(default=0, ge=0, le=1000, description="最低分阈值。")


class RetrievalQueryInternalResponse(BaseModel):
    """检索查询响应。"""

    hits: list[dict[str, Any]] = Field(description="命中切片列表。")
    latency_ms: int = Field(description="检索耗时（毫秒）。")
    retrieval_strategy: str = Field(description="本次检索生效策略。")


class ChatGenerateInternalRequest(BaseModel):
    """回答生成请求。"""

    tenant_id: UUID = Field(description="租户 ID。")
    kb_ids: list[UUID] = Field(default_factory=list, description="知识库范围。")
    question: str = Field(min_length=1, description="问题文本。")
    top_k: int = Field(default=6, ge=1, le=50, description="检索命中上限。")
    filters: dict[str, Any] = Field(default_factory=dict, description="metadata 过滤条件。")
    with_citations: bool = Field(default=True, description="是否返回 citation。")


class ChatGenerateInternalResponse(BaseModel):
    """回答生成响应。"""

    answer: str = Field(description="回答文本。")
    citations: list[dict[str, Any]] = Field(description="引用列表。")
    usage: dict[str, int] = Field(description="token 使用统计。")
    latency_ms: int = Field(description="检索+生成耗时（毫秒）。")


class AgentPlanInternalRequest(BaseModel):
    """智能体规划请求。"""

    tenant_id: UUID = Field(description="租户 ID。")
    user_id: UUID = Field(description="用户 ID。")
    task: str = Field(min_length=1, description="任务描述。")
    kb_ids: list[UUID] = Field(default_factory=list, description="知识库范围。")
    conversation_id: UUID | None = Field(default=None, description="可选会话 ID。")
    tool_policy: dict[str, Any] = Field(default_factory=dict, description="工具策略。")


class AgentPlanInternalResponse(BaseModel):
    """智能体规划响应。"""

    plan_json: dict[str, Any] = Field(description="规划结果。")
    tool_calls: list[dict[str, Any]] = Field(description="预置工具调用轨迹。")
    status: str = Field(description="初始任务状态。")
