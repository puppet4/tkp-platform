"""知识库相关请求结构。"""

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class KnowledgeBaseCreateRequest(BaseModel):
    """创建知识库请求体。"""

    workspace_id: UUID = Field(description="知识库归属工作空间 ID。")
    name: str = Field(min_length=2, max_length=128, description="知识库名称。", examples=["产品手册库"])
    description: str | None = Field(default=None, description="知识库说明。", examples=["2026 版产品文档"])
    embedding_model: str = Field(
        default="text-embedding-3-large",
        min_length=2,
        max_length=128,
        description="默认向量模型标识。",
        examples=["text-embedding-3-large"],
    )
    retrieval_strategy: dict[str, Any] = Field(
        default_factory=dict,
        description="检索策略参数，例如默认 top_k、重排开关等。",
        examples=[{"top_k": 8, "rerank": False}],
    )


class KBMembershipUpsertRequest(BaseModel):
    """知识库成员新增/更新请求体。"""

    role: Literal["kb_owner", "kb_editor", "kb_viewer"] = Field(
        description="需要授予的知识库角色。",
        examples=["kb_viewer"],
    )


class KnowledgeBaseUpdateRequest(BaseModel):
    """更新知识库请求体。"""

    name: str | None = Field(default=None, min_length=2, max_length=128, description="新的知识库名称。")
    description: str | None = Field(default=None, description="新的知识库描述。")
    embedding_model: str | None = Field(
        default=None,
        min_length=2,
        max_length=128,
        description="默认向量模型标识。",
    )
    retrieval_strategy: dict[str, Any] | None = Field(
        default=None,
        description="新的检索策略参数。",
    )
    status: Literal["active", "archived"] | None = Field(
        default=None,
        description="知识库状态。",
    )
