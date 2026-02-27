"""智能体运行模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tkp_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from tkp_api.models.enums import AgentRunStatus


class AgentRun(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """智能体任务运行记录。"""

    __tablename__ = "agent_runs"

    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 任务发起人用户 ID。
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 可选会话 ID，用于将智能体任务与会话关联。
    conversation_id: Mapped[UUID | None] = mapped_column()
    # 智能体规划结果（任务拆解、策略等）。
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # 工具调用轨迹。
    tool_calls: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # 任务状态。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=AgentRunStatus.QUEUED)
    # 任务成本估算。
    cost: Mapped[float] = mapped_column(Numeric(18, 6), nullable=False, default=0)
    # 开始执行时间。
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 结束执行时间。
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
