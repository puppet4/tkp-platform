"""租户初始化服务。"""

from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.models.enums import MembershipStatus, TenantRole, WorkspaceRole
from tkp_api.models.tenant import Tenant, TenantMembership
from tkp_api.models.workspace import Workspace, WorkspaceMembership


def normalize_tenant_slug(raw: str) -> str:
    """规范化租户 slug。"""
    normalized = re.sub(r"[^a-z0-9-]+", "-", raw.strip().lower())
    normalized = re.sub(r"-{2,}", "-", normalized).strip("-")
    return normalized or "tenant"


def build_unique_tenant_slug(db: Session, *, base_slug: str) -> str:
    """在现有租户集合中生成唯一 slug。"""
    seed = normalize_tenant_slug(base_slug)[:64]
    candidate = seed
    suffix = 1
    while db.execute(select(Tenant.id).where(Tenant.slug == candidate)).scalar_one_or_none():
        postfix = f"-{suffix}"
        candidate = f"{seed[: max(1, 64 - len(postfix))]}{postfix}"
        suffix += 1
    return candidate


def create_tenant_with_owner(
    db: Session,
    *,
    owner_user_id: UUID,
    tenant_name: str,
    tenant_slug: str,
    default_workspace_name: str = "默认工作空间",
    default_workspace_slug: str = "default",
    default_workspace_description: str = "系统自动创建的默认工作空间",
) -> tuple[Tenant, Workspace]:
    """创建租户并初始化创建者成员关系与默认工作空间。"""
    tenant = Tenant(name=tenant_name, slug=tenant_slug)
    db.add(tenant)
    db.flush()

    db.add(
        TenantMembership(
            tenant_id=tenant.id,
            user_id=owner_user_id,
            role=TenantRole.OWNER,
            status=MembershipStatus.ACTIVE,
        )
    )

    workspace = Workspace(
        tenant_id=tenant.id,
        name=default_workspace_name,
        slug=default_workspace_slug,
        description=default_workspace_description,
    )
    db.add(workspace)
    db.flush()

    db.add(
        WorkspaceMembership(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            user_id=owner_user_id,
            role=WorkspaceRole.OWNER,
            status=MembershipStatus.ACTIVE,
        )
    )
    return tenant, workspace
