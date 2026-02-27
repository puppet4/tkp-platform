"""租户与身份模型。"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tkp_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from tkp_api.models.enums import MembershipStatus, TenantRole, TenantStatus


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """租户实体，系统最高数据隔离边界。"""

    __tablename__ = "tenants"

    # 面向用户展示的租户名称。
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 全局唯一短标识，常用于 URL 或配置引用。
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # 数据隔离级别，当前默认 shared，后续可扩展到独立资源池。
    isolation_level: Mapped[str] = mapped_column(String(32), nullable=False, default="shared")
    # 租户生命周期状态（active/suspended/deleted）。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=TenantStatus.ACTIVE)

class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """用户实体，对接外部身份系统后的本地账号。"""

    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("auth_provider", "external_subject", name="uk_user_external_identity"),)

    # 登录与通知主邮箱，系统内全局唯一。
    email: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    # 前端展示名，支持按外部身份信息自动刷新。
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 本地用户状态。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")
    # 外部认证提供方标识（如 dev、issuer）。
    auth_provider: Mapped[str] = mapped_column(String(64), nullable=False, default="jwt")
    # 外部身份系统中的主体 ID（sub）。
    external_subject: Mapped[str] = mapped_column(String(256), nullable=False)
    # 最近一次登录时间，用于审计与活跃度判断。
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

class TenantMembership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """租户成员关系。"""

    __tablename__ = "tenant_memberships"
    __table_args__ = (UniqueConstraint("tenant_id", "user_id", name="uk_tenant_membership"),)

    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 成员用户 ID。
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 租户角色（owner/admin/member/viewer）。
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=TenantRole.MEMBER)
    # 成员状态（active/invited/disabled）。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=MembershipStatus.ACTIVE)
