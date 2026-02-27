"""智能体相关请求结构。"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class AgentRunCreateRequest(BaseModel):
    """创建智能体运行任务请求体。"""

    conversation_id: UUID | None = Field(default=None, description="可选会话 ID。")
    task: str = Field(min_length=1, description="任务描述。", examples=["根据知识库生成入职培训清单"])
    kb_ids: list[UUID] = Field(default_factory=list, description="本次运行请求使用的知识库范围。")
    tool_policy: dict[str, Any] = Field(default_factory=dict, description="可选工具策略覆盖配置。")
