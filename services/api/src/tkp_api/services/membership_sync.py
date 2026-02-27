"""成员关系同步服务。"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.models.enums import MembershipStatus, TenantRole, WorkspaceRole, WorkspaceStatus
from tkp_api.models.tenant import TenantMembership
from tkp_api.models.workspace import Workspace, WorkspaceMembership


def normalize_email(value: str) -> str:
    """标准化邮箱字段（去空格 + 小写）。"""
    return value.strip().lower()


def workspace_role_from_tenant_role(tenant_role: str) -> str:
    """根据租户角色映射工作空间角色。"""
    if tenant_role == TenantRole.OWNER:
        return WorkspaceRole.OWNER
    if tenant_role == TenantRole.ADMIN:
        return WorkspaceRole.EDITOR
    return WorkspaceRole.VIEWER


def sync_workspace_memberships_for_tenant_member(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    tenant_role: str,
) -> None:
    """将一个租户成员同步到租户内全部非归档工作空间。"""
    target_workspace_role = workspace_role_from_tenant_role(tenant_role)
    workspaces = (
        db.execute(
            select(Workspace)
            .where(Workspace.tenant_id == tenant_id)
            .where(Workspace.status != WorkspaceStatus.ARCHIVED)
        )
        .scalars()
        .all()
    )
    workspace_ids = [workspace.id for workspace in workspaces]
    if not workspace_ids:
        return

    memberships = (
        db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.tenant_id == tenant_id)
            .where(WorkspaceMembership.user_id == user_id)
            .where(WorkspaceMembership.workspace_id.in_(workspace_ids))
        )
        .scalars()
        .all()
    )
    membership_map = {membership.workspace_id: membership for membership in memberships}

    for workspace_id in workspace_ids:
        membership = membership_map.get(workspace_id)
        if membership:
            membership.role = target_workspace_role
            membership.status = MembershipStatus.ACTIVE
            continue
        db.add(
            WorkspaceMembership(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=user_id,
                role=target_workspace_role,
                status=MembershipStatus.ACTIVE,
            )
        )


def disable_workspace_memberships_for_tenant_member(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
) -> None:
    """禁用租户内用户的全部工作空间成员关系。"""
    memberships = (
        db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.tenant_id == tenant_id)
            .where(WorkspaceMembership.user_id == user_id)
        )
        .scalars()
        .all()
    )
    for membership in memberships:
        membership.status = MembershipStatus.DISABLED


def sync_tenant_members_to_workspace(
    db: Session,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
) -> None:
    """将租户内 active 成员同步到指定工作空间。"""
    tenant_memberships = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == tenant_id)
            .where(TenantMembership.status == MembershipStatus.ACTIVE)
        )
        .scalars()
        .all()
    )
    if not tenant_memberships:
        return

    user_ids = [membership.user_id for membership in tenant_memberships]
    workspace_memberships = (
        db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.tenant_id == tenant_id)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .where(WorkspaceMembership.user_id.in_(user_ids))
        )
        .scalars()
        .all()
    )
    workspace_membership_map = {membership.user_id: membership for membership in workspace_memberships}

    for tenant_membership in tenant_memberships:
        target_workspace_role = workspace_role_from_tenant_role(tenant_membership.role)
        membership = workspace_membership_map.get(tenant_membership.user_id)
        if membership:
            membership.role = target_workspace_role
            membership.status = MembershipStatus.ACTIVE
            continue
        db.add(
            WorkspaceMembership(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                user_id=tenant_membership.user_id,
                role=target_workspace_role,
                status=MembershipStatus.ACTIVE,
            )
        )
