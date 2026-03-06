"""Agent 恢复点模型。"""

from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import JSON, Text
from sqlalchemy.orm import Mapped, mapped_column

from tkp_api.db.base import Base


class AgentCheckpoint(Base):
    """Agent 执行恢复点表。"""

    __tablename__ = "agent_checkpoints"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    agent_run_id: Mapped[UUID] = mapped_column(index=True, nullable=False)

    # 恢复点序号（同一个 run 可以有多个恢复点）
    checkpoint_seq: Mapped[int] = mapped_column(nullable=False, default=0)

    # 恢复点类型：step_completed/tool_executed/error_occurred/manual
    checkpoint_type: Mapped[str] = mapped_column(nullable=False)

    # 执行状态快照
    state_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)

    # 已完成的步骤列表
    completed_steps: Mapped[list[str]] = mapped_column(JSON, default=list)

    # 待执行的步骤列表
    pending_steps: Mapped[list[str]] = mapped_column(JSON, default=list)

    # 上下文数据（变量、中间结果等）
    context_data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # 工具调用历史
    tool_call_history: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # 错误信息（如果是错误恢复点）
    error_info: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # 是否可恢复
    recoverable: Mapped[bool] = mapped_column(default=True, nullable=False)

    # 恢复策略：resume/retry/skip/abort
    recovery_strategy: Mapped[str | None] = mapped_column()

    # 备注
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)


class AgentRecovery(Base):
    """Agent 恢复记录表。"""

    __tablename__ = "agent_recoveries"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    tenant_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    agent_run_id: Mapped[UUID] = mapped_column(index=True, nullable=False)
    checkpoint_id: Mapped[UUID] = mapped_column(index=True, nullable=False)

    # 恢复状态：pending/running/completed/failed
    status: Mapped[str] = mapped_column(index=True, nullable=False, default="pending")

    # 恢复策略
    recovery_strategy: Mapped[str] = mapped_column(nullable=False)

    # 恢复前状态
    before_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # 恢复后状态
    after_state: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # 恢复结果
    recovery_result: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    # 错误信息
    error_message: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column()
