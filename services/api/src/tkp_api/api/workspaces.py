"""工作空间管理接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.dependencies import get_request_context
from tkp_api.db.session import get_db
from tkp_api.models.enums import DocumentStatus, KBStatus, MembershipStatus, TenantRole, WorkspaceRole, WorkspaceStatus
from tkp_api.models.knowledge import Document, KBMembership, KnowledgeBase
from tkp_api.models.tenant import TenantMembership, User
from tkp_api.models.workspace import Workspace, WorkspaceMembership
from tkp_api.utils.response import success
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import WorkspaceData, WorkspaceMemberData
from tkp_api.schemas.workspace import WorkspaceCreateRequest, WorkspaceMemberUpsertRequest, WorkspaceUpdateRequest
from tkp_api.services import (
    PermissionAction,
    audit_log,
    can_manage_workspace_members,
    ensure_workspace_read_access,
    ensure_workspace_write_access,
    require_tenant_action,
)
from tkp_api.services.membership_sync import sync_tenant_members_to_workspace


router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _get_workspace_membership(
    db: Session,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
) -> WorkspaceMembership | None:
    """读取用户在工作空间的成员关系。"""
    return (
        db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.tenant_id == tenant_id)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .where(WorkspaceMembership.user_id == user_id)
            .where(WorkspaceMembership.status == MembershipStatus.ACTIVE)
        )
        .scalar_one_or_none()
    )

@router.post(
    "",
    summary="创建工作空间",
    description="在当前租户下创建工作空间，并将创建者设为工作空间 Owner。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[WorkspaceData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def create_workspace(
    payload: WorkspaceCreateRequest,
    request: Request,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """创建工作空间并初始化创建者成员关系。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.WORKSPACE_CREATE,
    )

    exists = (
        db.execute(
            select(Workspace)
            .where(Workspace.tenant_id == ctx.tenant_id)
            .where(Workspace.slug == payload.slug)
            .where(Workspace.status != WorkspaceStatus.ARCHIVED)
        )
        .scalar_one_or_none()
    )
    if exists:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="workspace slug exists")

    workspace = Workspace(
        tenant_id=ctx.tenant_id,
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        status=WorkspaceStatus.ACTIVE,
    )
    db.add(workspace)
    db.flush()

    creator_membership = WorkspaceMembership(
        tenant_id=ctx.tenant_id,
        workspace_id=workspace.id,
        user_id=ctx.user_id,
        role=WorkspaceRole.OWNER,
        status=MembershipStatus.ACTIVE,
    )
    db.add(creator_membership)
    db.flush()
    # 新建工作空间后，将当前租户 active 成员按租户角色同步到工作空间。
    sync_tenant_members_to_workspace(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=workspace.id,
    )
    # 保持“创建者即工作空间 Owner”的显式语义。
    creator_membership.role = WorkspaceRole.OWNER
    creator_membership.status = MembershipStatus.ACTIVE

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="workspace.create",
        resource_type="workspace",
        resource_id=str(workspace.id),
        after_json={"name": workspace.name, "slug": workspace.slug},
    )

    db.commit()
    return success(
        request,
        {
            "id": workspace.id,
            "name": workspace.name,
            "slug": workspace.slug,
            "description": workspace.description,
            "status": workspace.status,
            "role": WorkspaceRole.OWNER,
        },
    )


@router.get(
    "",
    summary="查询工作空间列表",
    description="返回当前用户在当前租户下可访问的工作空间。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[WorkspaceData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def list_workspaces(
    request: Request,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """按成员关系返回工作空间视图。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.WORKSPACE_READ,
    )

    memberships = (
        db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.tenant_id == ctx.tenant_id)
            .where(WorkspaceMembership.user_id == ctx.user_id)
            .where(WorkspaceMembership.status == MembershipStatus.ACTIVE)
        )
        .scalars()
        .all()
    )
    workspace_ids = list({membership.workspace_id for membership in memberships})
    workspace_map: dict[UUID, Workspace] = {}
    if workspace_ids:
        workspaces = db.execute(select(Workspace).where(Workspace.id.in_(workspace_ids))).scalars().all()
        workspace_map = {workspace.id: workspace for workspace in workspaces}

    data = [
        {
            "id": workspace.id,
            "name": workspace.name,
            "slug": workspace.slug,
            "description": workspace.description,
            "status": workspace.status,
            "role": membership.role,
        }
        for membership in memberships
        if (workspace := workspace_map.get(membership.workspace_id)) is not None
        and workspace.status != WorkspaceStatus.ARCHIVED
    ]
    return success(request, data)


@router.patch(
    "/{workspace_id}",
    summary="更新工作空间",
    description="更新工作空间基础信息（名称、slug、描述、状态）。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[WorkspaceData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_workspace(
    payload: WorkspaceUpdateRequest,
    request: Request,
    workspace_id: UUID = Path(..., description="目标工作空间 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """更新工作空间。"""
    workspace, membership = ensure_workspace_write_access(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=workspace_id,
        user_id=ctx.user_id,
    )

    before = {
        "name": workspace.name,
        "slug": workspace.slug,
        "description": workspace.description,
        "status": workspace.status,
    }

    if payload.slug and payload.slug != workspace.slug:
        exists = (
            db.execute(
                select(Workspace)
                .where(Workspace.tenant_id == ctx.tenant_id)
                .where(Workspace.slug == payload.slug)
                .where(Workspace.id != workspace_id)
                .where(Workspace.status != WorkspaceStatus.ARCHIVED)
            )
            .scalar_one_or_none()
        )
        if exists:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="workspace slug exists")
        workspace.slug = payload.slug

    if payload.name is not None:
        workspace.name = payload.name
    if payload.description is not None:
        workspace.description = payload.description
    if payload.status is not None:
        workspace.status = payload.status

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="workspace.update",
        resource_type="workspace",
        resource_id=str(workspace_id),
        before_json=before,
        after_json={
            "name": workspace.name,
            "slug": workspace.slug,
            "description": workspace.description,
            "status": workspace.status,
        },
    )
    db.commit()

    return success(
        request,
        {
            "id": workspace.id,
            "name": workspace.name,
            "slug": workspace.slug,
            "description": workspace.description,
            "status": workspace.status,
            "role": membership.role,
        },
    )


@router.delete(
    "/{workspace_id}",
    summary="删除工作空间",
    description="逻辑删除工作空间（归档），并禁用成员关系、归档其知识库。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[WorkspaceData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_workspace(
    request: Request,
    workspace_id: UUID = Path(..., description="目标工作空间 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """删除工作空间。"""
    workspace, membership = ensure_workspace_read_access(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=workspace_id,
        user_id=ctx.user_id,
    )
    if ctx.tenant_role not in {TenantRole.OWNER, TenantRole.ADMIN} and membership.role != WorkspaceRole.OWNER:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    workspace.status = WorkspaceStatus.ARCHIVED

    ws_memberships = db.execute(
        select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id)
    ).scalars().all()
    for ws_membership in ws_memberships:
        ws_membership.status = MembershipStatus.DISABLED

    kb_memberships = db.execute(
        select(KBMembership)
        .where(KBMembership.tenant_id == ctx.tenant_id)
        .where(KBMembership.kb_id.in_(select(KnowledgeBase.id).where(KnowledgeBase.workspace_id == workspace_id)))
    ).scalars().all()
    for kb_membership in kb_memberships:
        kb_membership.status = MembershipStatus.DISABLED

    knowledge_bases = db.execute(
        select(KnowledgeBase).where(KnowledgeBase.workspace_id == workspace_id)
    ).scalars().all()
    kb_ids = [kb.id for kb in knowledge_bases]
    for kb in knowledge_bases:
        kb.status = KBStatus.ARCHIVED

    if kb_ids:
        documents = db.execute(select(Document).where(Document.kb_id.in_(kb_ids))).scalars().all()
        for document in documents:
            document.status = DocumentStatus.DELETED

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="workspace.delete",
        resource_type="workspace",
        resource_id=str(workspace_id),
        before_json={"status": WorkspaceStatus.ACTIVE},
        after_json={"status": workspace.status},
    )
    db.commit()

    return success(
        request,
        {
            "id": workspace.id,
            "name": workspace.name,
            "slug": workspace.slug,
            "description": workspace.description,
            "status": workspace.status,
            "role": membership.role,
        },
    )

@router.get(
    "/{workspace_id}/members",
    summary="查询工作空间成员",
    description="返回目标工作空间成员列表。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[WorkspaceMemberData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_workspace_members(
    request: Request,
    workspace_id: UUID = Path(..., description="目标工作空间 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询工作空间成员。"""
    workspace, membership = ensure_workspace_read_access(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=workspace_id,
        user_id=ctx.user_id,
    )
    if not can_manage_workspace_members(tenant_role=ctx.tenant_role, workspace_role=membership.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    memberships = db.execute(
        select(WorkspaceMembership).where(WorkspaceMembership.workspace_id == workspace_id)
    ).scalars().all()
    data = [
        {
            "workspace_id": workspace.id,
            "user_id": ws_membership.user_id,
            "role": ws_membership.role,
            "status": ws_membership.status,
        }
        for ws_membership in memberships
    ]
    return success(request, data)


@router.post(
    "/{workspace_id}/members",
    summary="新增或更新工作空间成员",
    description="为目标用户授予工作空间角色，目标用户必须先属于当前租户。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[WorkspaceMemberData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def upsert_workspace_member(
    payload: WorkspaceMemberUpsertRequest,
    request: Request,
    workspace_id: UUID = Path(..., description="目标工作空间 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """维护工作空间成员关系并记录审计日志。"""
    workspace, membership = ensure_workspace_read_access(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=workspace_id,
        user_id=ctx.user_id,
    )
    if not can_manage_workspace_members(tenant_role=ctx.tenant_role, workspace_role=membership.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    target_user = db.get(User, payload.user_id)
    if not target_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    tenant_membership = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == ctx.tenant_id)
            .where(TenantMembership.user_id == payload.user_id)
            .where(TenantMembership.status == MembershipStatus.ACTIVE)
        )
        .scalar_one_or_none()
    )
    if not tenant_membership:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="user not in tenant")

    target_membership = (
        db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace_id)
            .where(WorkspaceMembership.user_id == payload.user_id)
        )
        .scalar_one_or_none()
    )

    before = None
    if target_membership:
        before = {"role": target_membership.role, "status": target_membership.status}
        target_membership.role = payload.role
        target_membership.status = MembershipStatus.ACTIVE
    else:
        target_membership = WorkspaceMembership(
            tenant_id=ctx.tenant_id,
            workspace_id=workspace_id,
            user_id=payload.user_id,
            role=payload.role,
            status=MembershipStatus.ACTIVE,
        )
        db.add(target_membership)
        db.flush()

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="workspace.member.upsert",
        resource_type="workspace_membership",
        resource_id=str(target_membership.id),
        before_json=before,
        after_json={
            "workspace_id": str(workspace_id),
            "user_id": str(payload.user_id),
            "role": target_membership.role,
            "status": target_membership.status,
        },
    )

    db.commit()
    return success(
        request,
        {
            "workspace_id": workspace_id,
            "user_id": payload.user_id,
            "role": target_membership.role,
            "status": target_membership.status,
        },
    )


@router.delete(
    "/{workspace_id}/members/{user_id}",
    summary="移除工作空间成员",
    description="将目标用户在工作空间的成员关系置为 disabled。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[WorkspaceMemberData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def remove_workspace_member(
    request: Request,
    workspace_id: UUID = Path(..., description="目标工作空间 ID。"),
    user_id: UUID = Path(..., description="目标用户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """移除工作空间成员。"""
    _, membership = ensure_workspace_read_access(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=workspace_id,
        user_id=ctx.user_id,
    )
    if not can_manage_workspace_members(tenant_role=ctx.tenant_role, workspace_role=membership.role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    target_membership = _get_workspace_membership(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=workspace_id,
        user_id=user_id,
    )
    if not target_membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membership not found")

    if target_membership.role == WorkspaceRole.OWNER:
        owners = (
            db.execute(
                select(WorkspaceMembership)
                .where(WorkspaceMembership.workspace_id == workspace_id)
                .where(WorkspaceMembership.role == WorkspaceRole.OWNER)
                .where(WorkspaceMembership.status == MembershipStatus.ACTIVE)
            )
            .scalars()
            .all()
        )
        if len(owners) <= 1:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cannot remove last owner")

    target_membership.status = MembershipStatus.DISABLED

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="workspace.member.remove",
        resource_type="workspace_membership",
        resource_id=str(target_membership.id),
        before_json={"role": target_membership.role, "status": MembershipStatus.ACTIVE},
        after_json={"role": target_membership.role, "status": target_membership.status},
    )
    db.commit()

    return success(
        request,
        {
            "workspace_id": workspace_id,
            "user_id": user_id,
            "role": target_membership.role,
            "status": target_membership.status,
        },
    )



__all__ = ["router"]
