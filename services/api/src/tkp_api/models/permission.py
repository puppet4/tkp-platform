"""权限映射模型。"""

from uuid import UUID

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tkp_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class TenantRolePermission(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """租户角色权限点映射。

    说明：
    1. 支持 API、菜单、按钮、功能点等任意权限码。
    2. 同一租户 + 同一角色 + 同一权限码 唯一。
    """

    __tablename__ = "tenant_role_permissions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "role", "permission_code", name="uk_tenant_role_permission"),
    )

    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 角色标识（owner/admin/member/viewer）。
    role: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # 权限点编码（如 api.user.list / menu.tenant / button.user.delete）。
    permission_code: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
