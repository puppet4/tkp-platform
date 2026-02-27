"""审计日志模型。"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tkp_api.models.base import Base, UUIDPrimaryKeyMixin


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """关键操作审计日志。"""

    __tablename__ = "audit_logs"

    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 操作人用户 ID，系统动作可为空。
    actor_user_id: Mapped[UUID | None] = mapped_column()
    # 动作标识，例如 kb.create / document.upload。
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    # 资源类型，例如 tenant/workspace/document。
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # 资源标识（通常为字符串化 UUID）。
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    # 变更前快照。
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # 变更后快照。
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    # 客户端 IP。
    ip: Mapped[str | None] = mapped_column(INET)
    # 客户端 User-Agent。
    user_agent: Mapped[str | None] = mapped_column(Text)
    # 审计记录创建时间。
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
