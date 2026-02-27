"""认证辅助接口。"""

from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.dependencies import get_current_user, get_request_context
from tkp_api.core.config import get_settings
from tkp_api.core.security import parse_authorization_header, revoke_token_jti
from tkp_api.db.session import get_db
from tkp_api.models.enums import MembershipStatus, TenantRole, TenantStatus, WorkspaceRole
from tkp_api.models.auth import UserCredential
from tkp_api.models.tenant import Tenant, TenantMembership, User
from tkp_api.models.workspace import Workspace, WorkspaceMembership
from tkp_api.utils.response import success
from tkp_api.schemas.auth import (
    AuthLoginData,
    AuthLoginRequest,
    AuthLogoutData,
    AuthRegisterData,
    AuthRegisterRequest,
)
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import AuthMeData, PermissionSnapshotData
from tkp_api.services.membership_sync import normalize_email
from tkp_api.services.local_auth import hash_password, issue_access_token, verify_password
from tkp_api.services import build_unique_tenant_slug, create_tenant_with_owner, list_tenant_actions

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _invalid_credentials() -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid credentials")


@router.post(
    "/register",
    summary="注册本地账号",
    description="创建本地账号凭据（邮箱+密码），用于后续登录换取访问令牌。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[AuthRegisterData],
    responses={409: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def register(
    payload: AuthRegisterRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """注册本地账号。"""
    email = normalize_email(payload.email)
    display_name = payload.display_name.strip() if payload.display_name else email.split("@")[0]

    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if not user:
        user = User(
            id=uuid4(),
            email=email,
            display_name=display_name,
            status="active",
            auth_provider=settings.auth_local_issuer,
            external_subject=email,
            last_login_at=None,
        )
        db.add(user)
        db.flush()
    elif user.auth_provider == "invite":
        # 邀请态用户完成注册后，切换为本地认证主体。
        user.auth_provider = settings.auth_local_issuer
        user.external_subject = email
        user.display_name = display_name
    elif user.auth_provider != settings.auth_local_issuer:
        # 外部身份主体不允许通过本地注册补绑密码，避免账号接管。
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="account managed by external provider")

    credential = db.execute(select(UserCredential).where(UserCredential.user_id == user.id)).scalar_one_or_none()
    if credential and credential.status == "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="credential already exists")

    password_hash = hash_password(payload.password)
    if not credential:
        credential = UserCredential(
            id=uuid4(),
            user_id=user.id,
            password_hash=password_hash,
            status="active",
            password_updated_at=now,
        )
        db.add(credential)
    else:
        credential.password_hash = password_hash
        credential.status = "active"
        credential.password_updated_at = now

    personal_tenant = None
    owner_memberships = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.user_id == user.id)
            .where(TenantMembership.role == TenantRole.OWNER)
            .where(TenantMembership.status == MembershipStatus.ACTIVE)
        )
        .scalars()
        .all()
    )
    owner_tenant_ids = list({membership.tenant_id for membership in owner_memberships})
    if owner_tenant_ids:
        tenants = (
            db.execute(select(Tenant).where(Tenant.id.in_(owner_tenant_ids)))
            .scalars()
            .all()
        )
        for tenant in tenants:
            if tenant.status != TenantStatus.DELETED:
                personal_tenant = tenant
                break

    default_workspace = None
    if personal_tenant is None:
        tenant_slug = build_unique_tenant_slug(db, base_slug=f"{email.split('@')[0]}-personal")
        personal_tenant, default_workspace = create_tenant_with_owner(
            db,
            owner_user_id=user.id,
            tenant_name=f"{display_name} 的个人空间",
            tenant_slug=tenant_slug,
            default_workspace_name="个人默认空间",
            default_workspace_slug="default",
            default_workspace_description="注册时自动创建的个人空间",
        )
    else:
        default_workspace = (
            db.execute(
                select(Workspace)
                .where(Workspace.tenant_id == personal_tenant.id)
                .where(Workspace.slug == "default")
            )
            .scalar_one_or_none()
        )
        if default_workspace is None:
            default_workspace = (
                db.execute(select(Workspace).where(Workspace.tenant_id == personal_tenant.id))
                .scalars()
                .first()
            )
        if default_workspace is None:
            # 兼容历史数据：若租户意外缺少工作空间，则补建默认空间与成员关系。
            default_workspace = Workspace(
                tenant_id=personal_tenant.id,
                name="默认工作空间",
                slug="default",
                description="历史数据补齐的默认工作空间",
            )
            db.add(default_workspace)
            db.flush()
            db.add(
                WorkspaceMembership(
                    tenant_id=personal_tenant.id,
                    workspace_id=default_workspace.id,
                    user_id=user.id,
                    role=WorkspaceRole.OWNER,
                    status=MembershipStatus.ACTIVE,
                )
            )

    db.commit()
    return success(
        request,
        {
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "auth_provider": user.auth_provider,
            "personal_tenant_id": personal_tenant.id,
            "personal_tenant_slug": personal_tenant.slug,
            "personal_tenant_name": personal_tenant.name,
            "default_workspace_id": default_workspace.id,
        },
    )


@router.post(
    "/login",
    summary="本地账号登录",
    description="使用邮箱密码登录，返回 Bearer 访问令牌。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[AuthLoginData],
    responses={401: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def login(
    payload: AuthLoginRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """本地账号登录并签发访问令牌。"""
    email = normalize_email(payload.email)
    user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if not user or user.status != "active":
        raise _invalid_credentials()

    credential = (
        db.execute(
            select(UserCredential)
            .where(UserCredential.user_id == user.id)
            .where(UserCredential.status == "active")
        )
        .scalar_one_or_none()
    )
    if not credential or not verify_password(payload.password, credential.password_hash):
        raise _invalid_credentials()

    token, exp_ts, expires_at = issue_access_token(user)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()

    return success(
        request,
        {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": expires_at,
            "expires_in": max(0, exp_ts - int(datetime.now(timezone.utc).timestamp())),
        },
    )


@router.post(
    "/logout",
    summary="登出",
    description="将当前访问令牌加入黑名单（优先 Redis），已登出的 token 立即失效。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[AuthLogoutData],
    responses={401: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def logout(
    request: Request,
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    """登出并拉黑当前访问令牌。"""
    principal = parse_authorization_header(authorization)
    jti = principal.claims.get("jti")
    exp = principal.claims.get("exp")
    revoked = False
    if isinstance(jti, str) and jti and isinstance(exp, int):
        revoke_token_jti(jti, exp)
        revoked = True

    return success(request, {"logged_out": True, "revoked": revoked})


@router.get(
    "/me",
    summary="获取当前身份",
    description="返回当前用户资料，以及可访问的租户与工作空间列表。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[AuthMeData],
    responses={401: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
def me(
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """查询当前登录用户的租户与工作空间访问视图。"""
    # 先查租户成员关系，再按租户 ID 逻辑关联租户实体。
    tenant_memberships = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.user_id == user.id)
            .where(TenantMembership.status == MembershipStatus.ACTIVE)
        )
        .scalars()
        .all()
    )
    tenant_ids = list({membership.tenant_id for membership in tenant_memberships})
    tenant_map = {}
    if tenant_ids:
        tenants = db.execute(select(Tenant).where(Tenant.id.in_(tenant_ids))).scalars().all()
        tenant_map = {tenant.id: tenant for tenant in tenants}

    tenants = [
        {
            "tenant_id": tenant.id,
            "name": tenant.name,
            "slug": tenant.slug,
            "role": membership.role,
            "status": membership.status,
        }
        for membership in tenant_memberships
        if (tenant := tenant_map.get(membership.tenant_id)) is not None
    ]

    # 先查工作空间成员关系，再按工作空间 ID 逻辑关联工作空间实体。
    workspace_memberships = (
        db.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.user_id == user.id)
            .where(WorkspaceMembership.status == MembershipStatus.ACTIVE)
        )
        .scalars()
        .all()
    )
    workspace_ids = list({membership.workspace_id for membership in workspace_memberships})
    workspace_map = {}
    if workspace_ids:
        workspaces_data = db.execute(select(Workspace).where(Workspace.id.in_(workspace_ids))).scalars().all()
        workspace_map = {workspace.id: workspace for workspace in workspaces_data}

    workspaces = [
        {
            "workspace_id": workspace.id,
            "tenant_id": workspace.tenant_id,
            "name": workspace.name,
            "slug": workspace.slug,
            "role": membership.role,
            "status": membership.status,
        }
        for membership in workspace_memberships
        if (workspace := workspace_map.get(membership.workspace_id)) is not None
    ]

    # 汇总成前端常用的“用户 + 可访问范围”结构。
    data = {
        "user": {
            "id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "status": user.status,
            "auth_provider": user.auth_provider,
            "external_subject": user.external_subject,
            "last_login_at": user.last_login_at,
        },
        "tenants": tenants,
        "workspaces": workspaces,
    }
    return success(request, data)


@router.get(
    "/permissions",
    summary="查询当前权限快照",
    description="返回当前用户在请求租户下的角色与可执行动作集合。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[PermissionSnapshotData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def my_permissions(
    request: Request,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """返回当前租户上下文下的权限动作快照。"""
    return success(
        request,
        {
            "tenant_role": ctx.tenant_role,
            "allowed_actions": list_tenant_actions(db, tenant_id=ctx.tenant_id, tenant_role=ctx.tenant_role),
        },
    )
