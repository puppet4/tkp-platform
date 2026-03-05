"""配额策略模型。"""

from uuid import UUID

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tkp_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class QuotaPolicy(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """租户/工作空间配额策略。"""

    __tablename__ = "quota_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "scope_type", "scope_id", "metric_code", name="uk_quota_policy_scope_metric"),
    )

    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False, default="tenant")
    scope_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    metric_code: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    limit_value: Mapped[int] = mapped_column(Integer, nullable=False)
    window_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1440)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[UUID | None] = mapped_column()
    updated_by: Mapped[UUID | None] = mapped_column()
