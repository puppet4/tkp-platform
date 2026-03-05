"""运维中心模型。"""

from uuid import UUID

from sqlalchemy import Boolean, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tkp_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class OpsIncidentTicket(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """运维异常工单。"""

    __tablename__ = "ops_incident_tickets"

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    source_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warn")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    diagnosis_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    context_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    assignee_user_id: Mapped[UUID | None] = mapped_column()
    resolution_note: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column()
    resolved_at: Mapped[str | None] = mapped_column(String(64))


class OpsAlertWebhook(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """告警 webhook 订阅。"""

    __tablename__ = "ops_alert_webhooks"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uk_ops_alert_webhook_name"),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    secret: Mapped[str | None] = mapped_column(String(256))
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    event_types: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    last_status_code: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_notified_at: Mapped[str | None] = mapped_column(String(64))
