"""用户反馈模型。"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Text
from sqlalchemy.orm import Mapped, mapped_column

from tkp_api.db.base import Base


class UserFeedback(Base):
    """用户反馈表。"""

    __tablename__ = "user_feedbacks"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    user_id: Mapped[UUID] = mapped_column(index=True, nullable=False)

    # 关联对象
    conversation_id: Mapped[UUID | None] = mapped_column(index=True)
    message_id: Mapped[UUID | None] = mapped_column(index=True)
    retrieval_log_id: Mapped[UUID | None] = mapped_column(index=True)

    # 反馈类型：thumbs_up/thumbs_down/rating/comment
    feedback_type: Mapped[str] = mapped_column(index=True, nullable=False)

    # 反馈值（如评分 1-5，或布尔值）
    feedback_value: Mapped[str | None] = mapped_column()

    # 反馈评论
    comment: Mapped[str | None] = mapped_column(Text)

    # 反馈标签（如：不准确、不相关、有帮助等）
    tags: Mapped[list[str] | None] = mapped_column(JSON)

    # 快照数据（用于回放）
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # 是否已处理
    processed: Mapped[bool] = mapped_column(default=False, index=True)

    # 处理时间
    processed_at: Mapped[datetime | None] = mapped_column()

    # 处理结果
    processing_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class FeedbackReplay(Base):
    """反馈回放记录表。"""

    __tablename__ = "feedback_replays"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    feedback_id: Mapped[UUID] = mapped_column(index=True, nullable=False)

    # 回放类型：retrieval/generation/full_pipeline
    replay_type: Mapped[str] = mapped_column(nullable=False)

    # 回放状态：pending/running/completed/failed
    status: Mapped[str] = mapped_column(index=True, nullable=False, default="pending")

    # 原始结果
    original_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # 回放结果
    replay_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # 对比分析
    comparison: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # 改进建议
    suggestions: Mapped[list[str] | None] = mapped_column(JSON)

    # 错误信息
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column()
