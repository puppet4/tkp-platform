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


class OpsReleaseRollout(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """发布/回滚流水。"""

    __tablename__ = "ops_release_rollouts"

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    strategy: Mapped[str] = mapped_column(String(32), nullable=False, default="canary")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="planned")
    risk_level: Mapped[str] = mapped_column(String(16), nullable=False, default="medium")
    canary_percent: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    scope_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    rollback_of: Mapped[UUID | None] = mapped_column(index=True)
    approved_by: Mapped[UUID | None] = mapped_column()
    note: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[str | None] = mapped_column(String(64))
    completed_at: Mapped[str | None] = mapped_column(String(64))


class OpsDeletionProof(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """删除证明记录。"""

    __tablename__ = "ops_deletion_proofs"

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    subject_hash: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    signature: Mapped[str] = mapped_column(String(128), nullable=False)
    deleted_by: Mapped[UUID | None] = mapped_column()
    deleted_at: Mapped[str] = mapped_column(String(64), nullable=False)
    ticket_id: Mapped[UUID | None] = mapped_column(index=True)
    proof_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class OpsAlertStatus(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """告警状态记录。"""

    __tablename__ = "ops_alert_status"

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    alert_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    acknowledged_by: Mapped[UUID | None] = mapped_column()
    acknowledged_at: Mapped[str | None] = mapped_column(String(64))
    resolved_by: Mapped[UUID | None] = mapped_column()
    resolved_at: Mapped[str | None] = mapped_column(String(64))
    notes: Mapped[str | None] = mapped_column(Text)
