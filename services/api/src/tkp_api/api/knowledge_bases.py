"""知识库管理接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.dependencies import get_request_context
from tkp_api.db.session import get_db
from tkp_api.models.enums import DocumentStatus, KBRole, KBStatus, MembershipStatus, TenantRole, WorkspaceRole
from tkp_api.models.knowledge import Document, KBMembership, KnowledgeBase
from tkp_api.models.workspace import WorkspaceMembership
from tkp_api.utils.response import success
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.knowledge import KBMembershipUpsertRequest, KnowledgeBaseCreateRequest, KnowledgeBaseUpdateRequest
from tkp_api.schemas.responses import KBMembershipData, KnowledgeBaseData
from tkp_api.services import (
    PermissionAction,
    audit_log,
    can_manage_kb_members,
    ensure_kb_write_access,
    ensure_workspace_write_access,
    require_tenant_action,
)


router = APIRouter(prefix="/knowledge-bases", tags=["knowledge_bases"])


def _get_kb_or_404(db: Session, *, tenant_id: UUID, kb_id: UUID) -> KnowledgeBase:
    """读取知识库并校验归属。"""
    kb = db.get(KnowledgeBase, kb_id)
    if not kb or kb.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="knowledge base not found")
    return kb


def _get_workspace_membership(
    db: Session,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    user_id: UUID,
) -> WorkspaceMembership | None:
    """读取用户在工作空间内的成员关系。"""
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
    summary="创建知识库",
    description="在指定工作空间中创建知识库，并为创建者授予 KB Owner。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[KnowledgeBaseData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def create_knowledge_base(
    payload: KnowledgeBaseCreateRequest,
    request: Request,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """创建知识库并初始化知识库成员关系。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.KB_CREATE,
    )
    ensure_workspace_write_access(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=payload.workspace_id,
        user_id=ctx.user_id,
    )

    kb = KnowledgeBase(
        tenant_id=ctx.tenant_id,
        workspace_id=payload.workspace_id,
        name=payload.name,
        description=payload.description,
        embedding_model=payload.embedding_model,
        retrieval_strategy=payload.retrieval_strategy,
        created_by=ctx.user_id,
        status=KBStatus.ACTIVE,
    )
    db.add(kb)
    db.flush()

    db.add(
        KBMembership(
            tenant_id=ctx.tenant_id,
            kb_id=kb.id,
            user_id=ctx.user_id,
            role=KBRole.OWNER,
            status=MembershipStatus.ACTIVE,
        )
    )

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="kb.create",
        resource_type="knowledge_base",
        resource_id=str(kb.id),
        after_json={
            "workspace_id": str(kb.workspace_id),
            "name": kb.name,
            "embedding_model": kb.embedding_model,
            "retrieval_strategy": kb.retrieval_strategy,
        },
    )
    db.commit()

    return success(
        request,
        {
            "id": kb.id,
            "workspace_id": kb.workspace_id,
            "name": kb.name,
            "description": kb.description,
            "embedding_model": kb.embedding_model,
            "status": kb.status,
            "role": KBRole.OWNER,
        },
    )


@router.get(
    "",
    summary="查询知识库列表",
    description="返回当前用户可见的知识库，可按工作空间过滤。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[KnowledgeBaseData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def list_knowledge_bases(
    request: Request,
    workspace_id: UUID | None = Query(default=None, description="可选工作空间过滤条件。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """按工作空间成员与知识库成员双重授权返回知识库列表。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.KB_READ,
    )

    ws_stmt = (
        select(WorkspaceMembership)
        .where(WorkspaceMembership.user_id == ctx.user_id)
        .where(WorkspaceMembership.tenant_id == ctx.tenant_id)
        .where(WorkspaceMembership.status == MembershipStatus.ACTIVE)
    )
    if workspace_id:
        ws_stmt = ws_stmt.where(WorkspaceMembership.workspace_id == workspace_id)

    ws_memberships = db.execute(ws_stmt).scalars().all()
    allowed_workspace_ids = list({membership.workspace_id for membership in ws_memberships})
    if not allowed_workspace_ids:
        return success(request, [])

    kb_memberships = (
        db.execute(
            select(KBMembership)
            .where(KBMembership.user_id == ctx.user_id)
            .where(KBMembership.tenant_id == ctx.tenant_id)
            .where(KBMembership.status == MembershipStatus.ACTIVE)
        )
        .scalars()
        .all()
    )
    kb_role_map = {membership.kb_id: membership.role for membership in kb_memberships}
    if not kb_role_map:
        return success(request, [])

    kbs = (
        db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.tenant_id == ctx.tenant_id)
            .where(KnowledgeBase.workspace_id.in_(allowed_workspace_ids))
            .where(KnowledgeBase.id.in_(list(kb_role_map.keys())))
            .where(KnowledgeBase.status != KBStatus.ARCHIVED)
        )
        .scalars()
        .all()
    )

    data = [
        {
            "id": kb.id,
            "workspace_id": kb.workspace_id,
            "name": kb.name,
            "description": kb.description,
            "embedding_model": kb.embedding_model,
            "status": kb.status,
            "role": kb_role_map.get(kb.id),
        }
        for kb in kbs
    ]
    return success(request, data)


@router.patch(
    "/{kb_id}",
    summary="更新知识库",
    description="更新知识库基础信息。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[KnowledgeBaseData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_knowledge_base(
    payload: KnowledgeBaseUpdateRequest,
    request: Request,
    kb_id: UUID = Path(..., description="目标知识库 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """更新知识库。"""
    kb, _, kb_membership = ensure_kb_write_access(
        db,
        tenant_id=ctx.tenant_id,
        kb_id=kb_id,
        user_id=ctx.user_id,
    )
    role = kb_membership.role if kb_membership else None
    before = {
        "name": kb.name,
        "description": kb.description,
        "embedding_model": kb.embedding_model,
        "retrieval_strategy": kb.retrieval_strategy,
        "status": kb.status,
    }

    if payload.name is not None:
        kb.name = payload.name
    if payload.description is not None:
        kb.description = payload.description
    if payload.embedding_model is not None:
        kb.embedding_model = payload.embedding_model
    if payload.retrieval_strategy is not None:
        kb.retrieval_strategy = payload.retrieval_strategy
    if payload.status is not None:
        kb.status = payload.status

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="kb.update",
        resource_type="knowledge_base",
        resource_id=str(kb_id),
        before_json=before,
        after_json={
            "name": kb.name,
            "description": kb.description,
            "embedding_model": kb.embedding_model,
            "retrieval_strategy": kb.retrieval_strategy,
            "status": kb.status,
        },
    )
    db.commit()

    return success(
        request,
        {
            "id": kb.id,
            "workspace_id": kb.workspace_id,
            "name": kb.name,
            "description": kb.description,
            "embedding_model": kb.embedding_model,
            "status": kb.status,
            "role": role,
        },
    )


@router.delete(
    "/{kb_id}",
    summary="删除知识库",
    description="逻辑删除知识库（归档），并禁用其成员关系与文档。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[KnowledgeBaseData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_knowledge_base(
    request: Request,
    kb_id: UUID = Path(..., description="目标知识库 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """删除知识库。"""
    kb = _get_kb_or_404(db, tenant_id=ctx.tenant_id, kb_id=kb_id)
    requester_ws_membership = _get_workspace_membership(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=kb.workspace_id,
        user_id=ctx.user_id,
    )
    requester_kb_membership = (
        db.execute(
            select(KBMembership)
            .where(KBMembership.tenant_id == ctx.tenant_id)
            .where(KBMembership.kb_id == kb_id)
            .where(KBMembership.user_id == ctx.user_id)
            .where(KBMembership.status == MembershipStatus.ACTIVE)
        )
        .scalar_one_or_none()
    )
    ws_role = requester_ws_membership.role if requester_ws_membership else None
    kb_role = requester_kb_membership.role if requester_kb_membership else None
    if not can_manage_kb_members(tenant_role=ctx.tenant_role, workspace_role=ws_role, kb_role=kb_role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    kb.status = KBStatus.ARCHIVED
    memberships = db.execute(
        select(KBMembership).where(KBMembership.kb_id == kb_id)
    ).scalars().all()
    for membership in memberships:
        membership.status = MembershipStatus.DISABLED

    documents = db.execute(select(Document).where(Document.kb_id == kb_id)).scalars().all()
    for document in documents:
        document.status = DocumentStatus.DELETED

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="kb.delete",
        resource_type="knowledge_base",
        resource_id=str(kb_id),
        before_json={"status": KBStatus.ACTIVE},
        after_json={"status": kb.status},
    )
    db.commit()

    return success(
        request,
        {
            "id": kb.id,
            "workspace_id": kb.workspace_id,
            "name": kb.name,
            "description": kb.description,
            "embedding_model": kb.embedding_model,
            "status": kb.status,
            "role": kb_role,
        },
    )

@router.get(
    "/{kb_id}/members",
    summary="查询知识库成员",
    description="返回目标知识库成员列表。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[KBMembershipData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_kb_members(
    request: Request,
    kb_id: UUID = Path(..., description="目标知识库 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询知识库成员。"""
    kb = _get_kb_or_404(db, tenant_id=ctx.tenant_id, kb_id=kb_id)
    ws_membership = _get_workspace_membership(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=kb.workspace_id,
        user_id=ctx.user_id,
    )
    kb_membership = (
        db.execute(
            select(KBMembership)
            .where(KBMembership.kb_id == kb_id)
            .where(KBMembership.user_id == ctx.user_id)
            .where(KBMembership.status == MembershipStatus.ACTIVE)
        )
        .scalar_one_or_none()
    )
    ws_role = ws_membership.role if ws_membership else None
    kb_role = kb_membership.role if kb_membership else None
    if not can_manage_kb_members(
        tenant_role=ctx.tenant_role,
        workspace_role=ws_role,
        kb_role=kb_role,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    memberships = db.execute(select(KBMembership).where(KBMembership.kb_id == kb_id)).scalars().all()
    data = [
        {
            "kb_id": kb.id,
            "user_id": membership.user_id,
            "role": membership.role,
            "status": membership.status,
        }
        for membership in memberships
    ]
    return success(request, data)


@router.put(
    "/{kb_id}/members/{user_id}",
    summary="新增或更新知识库成员",
    description="授予或更新知识库成员角色，目标用户必须属于同一工作空间。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[KBMembershipData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def upsert_kb_membership(
    payload: KBMembershipUpsertRequest,
    request: Request,
    kb_id: UUID = Path(..., description="目标知识库 ID。"),
    user_id: UUID = Path(..., description="目标用户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """维护知识库成员关系并记录审计日志。"""
    kb = _get_kb_or_404(db, tenant_id=ctx.tenant_id, kb_id=kb_id)
    ws_membership = _get_workspace_membership(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=kb.workspace_id,
        user_id=ctx.user_id,
    )
    requester_kb_membership = (
        db.execute(
            select(KBMembership)
            .where(KBMembership.kb_id == kb_id)
            .where(KBMembership.user_id == ctx.user_id)
            .where(KBMembership.status == MembershipStatus.ACTIVE)
        )
        .scalar_one_or_none()
    )
    ws_role = ws_membership.role if ws_membership else None
    kb_role = requester_kb_membership.role if requester_kb_membership else None
    if not can_manage_kb_members(tenant_role=ctx.tenant_role, workspace_role=ws_role, kb_role=kb_role):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    target_ws_membership = (
        db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == kb.workspace_id)
            .where(WorkspaceMembership.user_id == user_id)
            .where(WorkspaceMembership.status == MembershipStatus.ACTIVE)
        )
        .scalar_one_or_none()
    )
    if not target_ws_membership:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="user not in workspace")

    membership = (
        db.execute(
            select(KBMembership)
            .where(KBMembership.kb_id == kb_id)
            .where(KBMembership.user_id == user_id)
        )
        .scalar_one_or_none()
    )

    before = None
    if membership:
        before = {"role": membership.role, "status": membership.status}
        membership.role = payload.role
        membership.status = MembershipStatus.ACTIVE
    else:
        membership = KBMembership(
            tenant_id=ctx.tenant_id,
            kb_id=kb_id,
            user_id=user_id,
            role=payload.role,
            status=MembershipStatus.ACTIVE,
        )
        db.add(membership)
        db.flush()

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="kb.member.upsert",
        resource_type="kb_membership",
        resource_id=str(membership.id),
        before_json=before,
        after_json={"kb_id": str(kb_id), "user_id": str(user_id), "role": membership.role, "status": membership.status},
    )

    db.commit()
    return success(
        request,
        {
            "kb_id": kb_id,
            "user_id": user_id,
            "role": membership.role,
            "status": membership.status,
        },
    )


@router.delete(
    "/{kb_id}/members/{user_id}",
    summary="移除知识库成员",
    description="将目标用户在知识库的成员关系置为 disabled。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[KBMembershipData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def remove_kb_membership(
    request: Request,
    kb_id: UUID = Path(..., description="目标知识库 ID。"),
    user_id: UUID = Path(..., description="目标用户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """移除知识库成员。"""
    kb = _get_kb_or_404(db, tenant_id=ctx.tenant_id, kb_id=kb_id)
    ws_membership = _get_workspace_membership(
        db,
        tenant_id=ctx.tenant_id,
        workspace_id=kb.workspace_id,
        user_id=ctx.user_id,
    )
    kb_membership = (
        db.execute(
            select(KBMembership)
            .where(KBMembership.kb_id == kb_id)
            .where(KBMembership.user_id == ctx.user_id)
            .where(KBMembership.status == MembershipStatus.ACTIVE)
        )
        .scalar_one_or_none()
    )
    ws_role = ws_membership.role if ws_membership else None
    kb_role = kb_membership.role if kb_membership else None
    if not can_manage_kb_members(
        tenant_role=ctx.tenant_role,
        workspace_role=ws_role,
        kb_role=kb_role,
    ):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    membership = (
        db.execute(
            select(KBMembership)
            .where(KBMembership.kb_id == kb_id)
            .where(KBMembership.user_id == user_id)
        )
        .scalar_one_or_none()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membership not found")

    if membership.role == KBRole.OWNER and membership.status == MembershipStatus.ACTIVE:
        owners = (
            db.execute(
                select(KBMembership)
                .where(KBMembership.kb_id == kb_id)
                .where(KBMembership.role == KBRole.OWNER)
                .where(KBMembership.status == MembershipStatus.ACTIVE)
            )
            .scalars()
            .all()
        )
        if len(owners) <= 1:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cannot remove last owner")

    membership.status = MembershipStatus.DISABLED
    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="kb.member.remove",
        resource_type="kb_membership",
        resource_id=str(membership.id),
        before_json={"role": membership.role, "status": MembershipStatus.ACTIVE},
        after_json={"role": membership.role, "status": membership.status},
    )
    db.commit()

    return success(
        request,
        {
            "kb_id": kb.id,
            "user_id": user_id,
            "role": membership.role,
            "status": membership.status,
        },
    )



__all__ = ["router"]
