"""会话与消息模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tkp_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from tkp_api.models.enums import MessageRole


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """问答会话记录。"""

    __tablename__ = "conversations"

    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 发起会话的用户 ID。
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 会话标题，通常来自首轮问题摘要。
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    # 会话知识范围快照（例如 kb_ids）。
    kb_scope: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

class Message(Base, UUIDPrimaryKeyMixin):
    """会话消息记录。"""

    __tablename__ = "messages"

    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 所属会话 ID。
    conversation_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 消息角色（user/assistant/tool/system）。
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=MessageRole.USER)
    # 消息正文。
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 引用来源列表。
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # token 统计等用量信息。
    usage: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # 消息创建时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
