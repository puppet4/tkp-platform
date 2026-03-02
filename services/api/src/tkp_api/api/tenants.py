"""租户管理接口。"""

from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.dependencies import get_current_user, get_request_context
from tkp_api.db.session import get_db
from tkp_api.models.enums import (
    DocumentStatus,
    KBStatus,
    MembershipStatus,
    TenantRole,
    TenantStatus,
    WorkspaceStatus,
)
from tkp_api.models.knowledge import Document, KBMembership, KnowledgeBase
from tkp_api.models.tenant import Tenant, TenantMembership, User
from tkp_api.models.workspace import Workspace, WorkspaceMembership
from tkp_api.utils.response import success
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import TenantAccessItem, TenantCreateData, TenantData, TenantMemberData
from tkp_api.schemas.tenant import (
    TenantCreateRequest,
    TenantMemberInviteRequest,
    TenantMemberRoleUpdateRequest,
    TenantMemberUpsertRequest,
    TenantUpdateRequest,
)
from tkp_api.services import PermissionAction, audit_log, create_tenant_with_owner, require_tenant_action
from tkp_api.services.membership_sync import (
    disable_workspace_memberships_for_tenant_member,
    normalize_email,
    sync_workspace_memberships_for_tenant_member,
)


router = APIRouter(prefix="/tenants", tags=["tenants"])


def _ensure_tenant_context(*, ctx, tenant_id: UUID) -> None:
    """校验路径租户与请求头租户一致。"""
    if ctx.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def _get_tenant_or_404(db: Session, tenant_id: UUID) -> Tenant:
    """获取租户实体。"""
    tenant = db.get(Tenant, tenant_id)
    if not tenant or tenant.status == TenantStatus.DELETED:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    return tenant

@router.get(
    "",
    summary="查询我的租户",
    description="返回当前用户具备有效成员关系的租户列表。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[TenantAccessItem]],
    responses={401: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def list_tenants(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取当前用户在租户维度的访问列表。"""
    memberships = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.user_id == user.id)
            .where(TenantMembership.status == MembershipStatus.ACTIVE)
        )
        .scalars()
        .all()
    )
    tenant_ids = list({membership.tenant_id for membership in memberships})
    tenant_map = {}
    if tenant_ids:
        tenants = db.execute(select(Tenant).where(Tenant.id.in_(tenant_ids))).scalars().all()
        tenant_map = {tenant.id: tenant for tenant in tenants}

    data = [
        {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "role": membership.role,
            "status": membership.status,
        }
        for membership in memberships
        if (tenant := tenant_map.get(membership.tenant_id)) is not None and tenant.status != TenantStatus.DELETED
    ]
    return success(request, data)


@router.post(
    "",
    summary="创建租户",
    description="创建新租户，并自动初始化默认工作空间与创建者 Owner 权限。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantCreateData],
    responses={
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse, "description": "租户 slug 已存在。"},
        500: {"model": ErrorResponse},
    },
)
def create_tenant(
    payload: TenantCreateRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建租户并完成初始化引导数据。"""
    # slug 全局唯一，避免跨租户地址冲突。
    existing = db.execute(select(Tenant).where(Tenant.slug == payload.slug)).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tenant slug exists")

    tenant, default_workspace = create_tenant_with_owner(
        db,
        owner_user_id=user.id,
        tenant_name=payload.name,
        tenant_slug=payload.slug,
        default_workspace_name="默认工作空间",
        default_workspace_slug="default",
        default_workspace_description="系统自动创建的默认工作空间",
    )

    audit_log(
        db=db,
        request=request,
        tenant_id=tenant.id,
        actor_user_id=user.id,
        action="tenant.create",
        resource_type="tenant",
        resource_id=str(tenant.id),
        after_json={"name": tenant.name, "slug": tenant.slug},
    )
    db.commit()

    return success(
        request,
        {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "role": TenantRole.OWNER,
            "default_workspace_id": default_workspace.id,
        },
    )


@router.get(
    "/invitations",
    summary="查询我的租户邀请",
    description="返回当前用户待加入（invited）的租户邀请列表。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[TenantAccessItem]],
    responses={401: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def list_my_tenant_invitations(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """列出当前用户收到的租户邀请。"""
    memberships = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.user_id == user.id)
            .where(TenantMembership.status == MembershipStatus.INVITED)
        )
        .scalars()
        .all()
    )
    tenant_ids = list({membership.tenant_id for membership in memberships})
    tenant_map: dict[UUID, Tenant] = {}
    if tenant_ids:
        tenants = db.execute(select(Tenant).where(Tenant.id.in_(tenant_ids))).scalars().all()
        tenant_map = {tenant.id: tenant for tenant in tenants}

    data = [
        {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "role": membership.role,
            "status": membership.status,
        }
        for membership in memberships
        if (tenant := tenant_map.get(membership.tenant_id)) is not None and tenant.status != TenantStatus.DELETED
    ]
    return success(request, data)


@router.get(
    "/{tenant_id}",
    summary="查询租户详情",
    description="返回目标租户基础信息与当前用户在该租户中的角色。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_tenant(
    request: Request,
    tenant_id: UUID = Path(..., description="目标租户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询单个租户详情。"""
    _ensure_tenant_context(ctx=ctx, tenant_id=tenant_id)
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.TENANT_READ,
    )
    tenant = _get_tenant_or_404(db, tenant_id)
    return success(
        request,
        {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "status": tenant.status,
            "role": ctx.tenant_role,
        },
    )


@router.patch(
    "/{tenant_id}",
    summary="更新租户",
    description="更新租户基础信息（名称、slug、状态）。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_tenant(
    payload: TenantUpdateRequest,
    request: Request,
    tenant_id: UUID = Path(..., description="目标租户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """更新租户基础信息。"""
    _ensure_tenant_context(ctx=ctx, tenant_id=tenant_id)
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.TENANT_UPDATE,
    )
    tenant = _get_tenant_or_404(db, tenant_id)

    before = {"name": tenant.name, "slug": tenant.slug, "status": tenant.status}

    if payload.slug and payload.slug != tenant.slug:
        exists = db.execute(select(Tenant).where(Tenant.slug == payload.slug)).scalar_one_or_none()
        if exists and exists.id != tenant.id:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="tenant slug exists")
        tenant.slug = payload.slug

    if payload.name:
        tenant.name = payload.name
    if payload.status:
        tenant.status = payload.status

    audit_log(
        db=db,
        request=request,
        tenant_id=tenant.id,
        actor_user_id=ctx.user_id,
        action="tenant.update",
        resource_type="tenant",
        resource_id=str(tenant.id),
        before_json=before,
        after_json={"name": tenant.name, "slug": tenant.slug, "status": tenant.status},
    )
    db.commit()

    return success(
        request,
        {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "status": tenant.status,
            "role": ctx.tenant_role,
        },
    )


@router.delete(
    "/{tenant_id}",
    summary="删除租户",
    description="逻辑删除租户，并归档其工作空间/知识库，禁用成员关系。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_tenant(
    request: Request,
    tenant_id: UUID = Path(..., description="目标租户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """逻辑删除租户及其权限关系。"""
    _ensure_tenant_context(ctx=ctx, tenant_id=tenant_id)
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.TENANT_DELETE,
    )
    tenant = _get_tenant_or_404(db, tenant_id)

    tenant.status = TenantStatus.DELETED

    tenant_memberships = db.execute(
        select(TenantMembership).where(TenantMembership.tenant_id == tenant_id)
    ).scalars().all()
    for membership in tenant_memberships:
        membership.status = MembershipStatus.DISABLED

    workspace_memberships = db.execute(
        select(WorkspaceMembership).where(WorkspaceMembership.tenant_id == tenant_id)
    ).scalars().all()
    for membership in workspace_memberships:
        membership.status = MembershipStatus.DISABLED

    workspaces = db.execute(select(Workspace).where(Workspace.tenant_id == tenant_id)).scalars().all()
    for workspace in workspaces:
        workspace.status = WorkspaceStatus.ARCHIVED

    kb_memberships = db.execute(
        select(KBMembership).where(KBMembership.tenant_id == tenant_id)
    ).scalars().all()
    for membership in kb_memberships:
        membership.status = MembershipStatus.DISABLED

    knowledge_bases = db.execute(select(KnowledgeBase).where(KnowledgeBase.tenant_id == tenant_id)).scalars().all()
    for kb in knowledge_bases:
        kb.status = KBStatus.ARCHIVED

    documents = db.execute(select(Document).where(Document.tenant_id == tenant_id)).scalars().all()
    for document in documents:
        document.status = DocumentStatus.DELETED

    audit_log(
        db=db,
        request=request,
        tenant_id=tenant_id,
        actor_user_id=ctx.user_id,
        action="tenant.delete",
        resource_type="tenant",
        resource_id=str(tenant_id),
        before_json={"status": TenantStatus.ACTIVE},
        after_json={"status": tenant.status},
    )
    db.commit()

    return success(
        request,
        {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "status": tenant.status,
            "role": ctx.tenant_role,
        },
    )

@router.get(
    "/{tenant_id}/members",
    summary="查询租户成员列表",
    description="返回目标租户的成员关系列表。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[TenantMemberData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_tenant_members(
    request: Request,
    tenant_id: UUID = Path(..., description="目标租户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询租户成员。"""
    _ensure_tenant_context(ctx=ctx, tenant_id=tenant_id)
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.TENANT_MEMBER_MANAGE,
    )
    _get_tenant_or_404(db, tenant_id)

    memberships = db.execute(
        select(TenantMembership).where(TenantMembership.tenant_id == tenant_id)
    ).scalars().all()
    user_ids = list({membership.user_id for membership in memberships})
    user_map: dict[UUID, User] = {}
    if user_ids:
        users = db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
        user_map = {user.id: user for user in users}

    data = [
        {
            "tenant_id": tenant_id,
            "user_id": membership.user_id,
            "email": user.email,
            "role": membership.role,
            "status": membership.status,
        }
        for membership in memberships
        if (user := user_map.get(membership.user_id)) is not None
    ]
    return success(request, data)


@router.post(
    "/{tenant_id}/invitations",
    summary="邀请租户成员",
    description="按邮箱发送租户邀请，创建或更新 invited 成员关系。适用于“被邀请用户确认加入”的标准流程。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantMemberData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def invite_tenant_member(
    payload: TenantMemberInviteRequest,
    request: Request,
    tenant_id: UUID = Path(..., description="目标租户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """邀请成员加入租户。"""
    _ensure_tenant_context(ctx=ctx, tenant_id=tenant_id)
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.TENANT_MEMBER_MANAGE,
    )
    _get_tenant_or_404(db, tenant_id)

    email = normalize_email(payload.email)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        user = User(
            id=uuid4(),
            email=email,
            display_name=email.split("@")[0],
            auth_provider="invite",
            external_subject=email,
        )
        db.add(user)
        db.flush()

    membership = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == tenant_id)
            .where(TenantMembership.user_id == user.id)
        )
        .scalar_one_or_none()
    )
    before = None
    if membership:
        if membership.status == MembershipStatus.ACTIVE:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="user already active in tenant")
        before = {"role": membership.role, "status": membership.status}
        membership.role = payload.role
        membership.status = MembershipStatus.INVITED
    else:
        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=user.id,
            role=payload.role,
            status=MembershipStatus.INVITED,
        )
        db.add(membership)
        db.flush()

    audit_log(
        db=db,
        request=request,
        tenant_id=tenant_id,
        actor_user_id=ctx.user_id,
        action="tenant.member.invite",
        resource_type="tenant_membership",
        resource_id=str(membership.id),
        before_json=before,
        after_json={"user_id": str(user.id), "role": membership.role, "status": membership.status},
    )
    db.commit()

    return success(
        request,
        {
            "tenant_id": tenant_id,
            "user_id": user.id,
            "email": user.email,
            "role": membership.role,
            "status": membership.status,
        },
    )


@router.post(
    "/{tenant_id}/members",
    summary="新增或更新租户成员",
    description="按邮箱直接新增/激活成员并同步角色，适用于管理员后台直接维护成员，不需要用户确认加入。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantMemberData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
def upsert_tenant_member(
    payload: TenantMemberUpsertRequest,
    request: Request,
    tenant_id: UUID = Path(..., description="目标租户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """维护租户成员关系，并自动激活禁用成员。"""
    _ensure_tenant_context(ctx=ctx, tenant_id=tenant_id)
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.TENANT_MEMBER_MANAGE,
    )
    _get_tenant_or_404(db, tenant_id)

    # 按邮箱查找目标用户；不存在时创建邀请态本地账号。
    email = normalize_email(payload.email)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user:
        user = User(
            id=uuid4(),
            email=email,
            display_name=email.split("@")[0],
            auth_provider="invite",
            external_subject=email,
        )
        db.add(user)
        db.flush()

    membership = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == tenant_id)
            .where(TenantMembership.user_id == user.id)
        )
        .scalar_one_or_none()
    )

    before = None
    if membership:
        before = {"role": membership.role, "status": membership.status}
        membership.role = payload.role
        membership.status = MembershipStatus.ACTIVE
    else:
        membership = TenantMembership(
            tenant_id=tenant_id,
            user_id=user.id,
            role=payload.role,
            status=MembershipStatus.ACTIVE,
        )
        db.add(membership)
        db.flush()

    sync_workspace_memberships_for_tenant_member(
        db,
        tenant_id=tenant_id,
        user_id=user.id,
        tenant_role=membership.role,
    )

    audit_log(
        db=db,
        request=request,
        tenant_id=tenant_id,
        actor_user_id=ctx.user_id,
        action="tenant.member.upsert",
        resource_type="tenant_membership",
        resource_id=str(membership.id),
        before_json=before,
        after_json={"user_id": str(user.id), "role": membership.role, "status": membership.status},
    )

    db.commit()

    return success(
        request,
        {
            "tenant_id": tenant_id,
            "user_id": user.id,
            "email": user.email,
            "role": membership.role,
            "status": membership.status,
        },
    )


@router.post(
    "/{tenant_id}/join",
    summary="加入租户",
    description="当前登录用户确认加入租户邀请（invited -> active）。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantMemberData],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def join_tenant(
    request: Request,
    tenant_id: UUID = Path(..., description="目标租户 ID。"),
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """当前用户加入他人租户。"""
    _get_tenant_or_404(db, tenant_id)
    membership = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == tenant_id)
            .where(TenantMembership.user_id == user.id)
        )
        .scalar_one_or_none()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="invitation not found")

    if membership.status == MembershipStatus.ACTIVE:
        sync_workspace_memberships_for_tenant_member(
            db,
            tenant_id=tenant_id,
            user_id=user.id,
            tenant_role=membership.role,
        )
        db.commit()
        return success(
            request,
            {
                "tenant_id": tenant_id,
                "user_id": user.id,
                "email": user.email,
                "role": membership.role,
                "status": membership.status,
            },
        )

    if membership.status != MembershipStatus.INVITED:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="membership is not invited")

    before = {"role": membership.role, "status": membership.status}
    membership.status = MembershipStatus.ACTIVE
    user.status = "active"
    sync_workspace_memberships_for_tenant_member(
        db,
        tenant_id=tenant_id,
        user_id=user.id,
        tenant_role=membership.role,
    )

    audit_log(
        db=db,
        request=request,
        tenant_id=tenant_id,
        actor_user_id=user.id,
        action="tenant.member.join",
        resource_type="tenant_membership",
        resource_id=str(membership.id),
        before_json=before,
        after_json={"role": membership.role, "status": membership.status},
    )
    db.commit()

    return success(
        request,
        {
            "tenant_id": tenant_id,
            "user_id": user.id,
            "email": user.email,
            "role": membership.role,
            "status": membership.status,
        },
    )


@router.put(
    "/{tenant_id}/members/{user_id}/role",
    summary="更新租户成员角色",
    description="按用户 ID 更新租户成员角色（用户-角色关系）。这是租户成员角色变更的推荐接口。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantMemberData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def update_tenant_member_role(
    payload: TenantMemberRoleUpdateRequest,
    request: Request,
    tenant_id: UUID = Path(..., description="目标租户 ID。"),
    user_id: UUID = Path(..., description="目标用户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """更新用户在租户内的角色。"""
    _ensure_tenant_context(ctx=ctx, tenant_id=tenant_id)
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.TENANT_MEMBER_MANAGE,
    )
    _get_tenant_or_404(db, tenant_id)

    membership = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == tenant_id)
            .where(TenantMembership.user_id == user_id)
        )
        .scalar_one_or_none()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membership not found")

    if membership.role == TenantRole.OWNER and payload.role != TenantRole.OWNER:
        owners = (
            db.execute(
                select(TenantMembership)
                .where(TenantMembership.tenant_id == tenant_id)
                .where(TenantMembership.role == TenantRole.OWNER)
                .where(TenantMembership.status == MembershipStatus.ACTIVE)
            )
            .scalars()
            .all()
        )
        if len(owners) <= 1:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cannot downgrade last owner")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    before = {"role": membership.role, "status": membership.status}
    membership.role = payload.role
    membership.status = MembershipStatus.ACTIVE
    sync_workspace_memberships_for_tenant_member(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
        tenant_role=membership.role,
    )

    audit_log(
        db=db,
        request=request,
        tenant_id=tenant_id,
        actor_user_id=ctx.user_id,
        action="tenant.member.role.update",
        resource_type="tenant_membership",
        resource_id=str(membership.id),
        before_json=before,
        after_json={"role": membership.role, "status": membership.status},
    )
    db.commit()

    return success(
        request,
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "email": user.email,
            "role": membership.role,
            "status": membership.status,
        },
    )


@router.delete(
    "/{tenant_id}/members/{user_id}",
    summary="移除租户成员",
    description="将目标用户的租户成员关系置为 disabled。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantMemberData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def remove_tenant_member(
    request: Request,
    tenant_id: UUID = Path(..., description="目标租户 ID。"),
    user_id: UUID = Path(..., description="目标用户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """移除租户成员。"""
    _ensure_tenant_context(ctx=ctx, tenant_id=tenant_id)
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.TENANT_MEMBER_MANAGE,
    )
    _get_tenant_or_404(db, tenant_id)

    membership = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == tenant_id)
            .where(TenantMembership.user_id == user_id)
        )
        .scalar_one_or_none()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membership not found")

    if membership.role == TenantRole.OWNER and membership.status == MembershipStatus.ACTIVE:
        owners = (
            db.execute(
                select(TenantMembership)
                .where(TenantMembership.tenant_id == tenant_id)
                .where(TenantMembership.role == TenantRole.OWNER)
                .where(TenantMembership.status == MembershipStatus.ACTIVE)
            )
            .scalars()
            .all()
        )
        if len(owners) <= 1:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cannot remove last owner")

    membership.status = MembershipStatus.DISABLED
    disable_workspace_memberships_for_tenant_member(
        db,
        tenant_id=tenant_id,
        user_id=user_id,
    )
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    audit_log(
        db=db,
        request=request,
        tenant_id=tenant_id,
        actor_user_id=ctx.user_id,
        action="tenant.member.remove",
        resource_type="tenant_membership",
        resource_id=str(membership.id),
        before_json={"role": membership.role, "status": MembershipStatus.ACTIVE},
        after_json={"role": membership.role, "status": membership.status},
    )
    db.commit()

    return success(
        request,
        {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "email": user.email,
            "role": membership.role,
            "status": membership.status,
        },
    )



__all__ = ["router"]
