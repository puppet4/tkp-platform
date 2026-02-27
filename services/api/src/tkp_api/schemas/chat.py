"""问答相关请求结构。"""

from uuid import UUID

from pydantic import BaseModel, Field


class ChatMessageInput(BaseModel):
    """单条消息输入。"""

    role: str = Field(description="消息角色，如 user/assistant/system/tool。", examples=["user"])
    content: str = Field(description="消息文本内容。", examples=["请总结这份制度文档"])


class ChatGenerationConfig(BaseModel):
    """生成参数配置。"""

    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="采样温度。", examples=[0.2])
    max_tokens: int = Field(default=600, ge=1, le=8000, description="最大生成 token 数。", examples=[600])


class ChatCompletionRequest(BaseModel):
    """问答接口请求体。"""

    conversation_id: UUID | None = Field(default=None, description="已有会话 ID，可选。")
    messages: list[ChatMessageInput] = Field(description="消息数组，最后一条视为当前问题。")
    kb_ids: list[UUID] = Field(default_factory=list, description="可选知识库范围，空表示全部可见知识库。")
    generation: ChatGenerationConfig = Field(
        default_factory=ChatGenerationConfig,
        description="生成参数配置，未传时使用默认值。",
    )
