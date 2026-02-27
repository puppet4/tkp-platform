"""工作空间模型。"""

from uuid import UUID

from sqlalchemy import String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from tkp_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from tkp_api.models.enums import MembershipStatus, WorkspaceRole, WorkspaceStatus


class Workspace(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """工作空间实体，承载知识库和文档的协作隔离边界。"""

    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("tenant_id", "slug", name="uk_workspace_slug"),)

    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 工作空间名称，面向用户展示。
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 租户内唯一短标识，用于地址与筛选。
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    # 可选描述，记录用途或团队说明。
    description: Mapped[str | None] = mapped_column(Text)
    # 工作空间状态（active/archived）。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=WorkspaceStatus.ACTIVE)

class WorkspaceMembership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """工作空间成员关系。"""

    __tablename__ = "workspace_memberships"
    __table_args__ = (UniqueConstraint("workspace_id", "user_id", name="uk_workspace_membership"),)

    # 冗余租户 ID，便于租户维度过滤与索引。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 工作空间 ID。
    workspace_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 用户 ID。
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 工作空间角色（ws_owner/ws_editor/ws_viewer）。
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=WorkspaceRole.VIEWER)
    # 成员关系状态。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=MembershipStatus.ACTIVE)
