"""认证辅助接口。"""

from datetime import datetime, timezone
from uuid import UUID
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.exc import DataError, IntegrityError, SQLAlchemyError
from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.dependencies import get_current_principal, get_current_user, get_request_context
from tkp_api.core.config import get_settings
from tkp_api.core.security import AuthenticatedPrincipal, activate_user_session, clear_user_session, revoke_token_jti
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
    AuthSwitchTenantRequest,
)
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import AuthMeData
from tkp_api.services.membership_sync import normalize_email
from tkp_api.services.local_auth import hash_password, issue_access_token, verify_password
from tkp_api.services import build_unique_tenant_slug, create_tenant_with_owner

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()


def _invalid_credentials() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={
            "code": "LOGIN_INVALID_CREDENTIALS",
            "message": "登录失败：账号或密码错误。",
            "details": {
                "reason": "invalid_credentials",
                "suggestion": "请检查邮箱和密码后重试，或使用找回密码流程。",
            },
        },
    )


def _register_error(*, status_code: int, code: str, message: str, reason: str, suggestion: str) -> HTTPException:
    """构造注册场景的结构化错误。"""
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "details": {
                "reason": reason,
                "suggestion": suggestion,
            },
        },
    )


def _login_error(*, status_code: int, code: str, message: str, reason: str, suggestion: str) -> HTTPException:
    """构造登录场景的结构化错误。"""
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "details": {
                "reason": reason,
                "suggestion": suggestion,
            },
        },
    )


def _resolve_user_default_tenant_id(db: Session, *, user_id: UUID) -> UUID | None:
    """为登录用户选择默认租户（仅 active 且租户未删除）。"""
    memberships = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.user_id == user_id)
            .where(TenantMembership.status == MembershipStatus.ACTIVE)
        )
        .scalars()
        .all()
    )
    if not memberships:
        return None
    tenant_ids = list({membership.tenant_id for membership in memberships})
    tenant_map: dict[UUID, Tenant] = {}
    if tenant_ids:
        tenants = db.execute(select(Tenant).where(Tenant.id.in_(tenant_ids))).scalars().all()
        tenant_map = {tenant.id: tenant for tenant in tenants}
    for membership in memberships:
        tenant = tenant_map.get(membership.tenant_id)
        if tenant is not None and tenant.status != TenantStatus.DELETED:
            return tenant.id
    return None


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
    if payload.display_name is not None and not display_name:
        raise _register_error(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="REGISTER_INVALID_DISPLAY_NAME",
            message="注册失败：展示名不能为空白字符。",
            reason="invalid_display_name",
            suggestion="请填写有效的展示名，或不传该字段使用默认昵称。",
        )

    try:
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
            raise _register_error(
                status_code=status.HTTP_409_CONFLICT,
                code="REGISTER_EXTERNAL_PROVIDER_ACCOUNT",
                message="注册失败：该邮箱已绑定外部身份登录。",
                reason="account_managed_by_external_provider",
                suggestion="请使用原登录方式（如 SSO/OAuth）登录，或更换邮箱。",
            )

        credential = db.execute(select(UserCredential).where(UserCredential.user_id == user.id)).scalar_one_or_none()
        if credential and credential.status == "active":
            raise _register_error(
                status_code=status.HTTP_409_CONFLICT,
                code="REGISTER_CREDENTIAL_EXISTS",
                message="注册失败：该邮箱已完成注册，请直接登录。",
                reason="credential_already_exists",
                suggestion="使用登录接口获取访问令牌，或使用找回密码流程。",
            )

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
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise _register_error(
            status_code=status.HTTP_409_CONFLICT,
            code="REGISTER_DATA_CONFLICT",
            message="注册失败：账号信息冲突。",
            reason="database_unique_conflict",
            suggestion="请检查邮箱是否已存在，或稍后重试。",
        ) from exc
    except DataError as exc:
        db.rollback()
        raise _register_error(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            code="REGISTER_INVALID_DATA",
            message="注册失败：输入数据不符合系统限制。",
            reason="database_data_validation_failed",
            suggestion="请检查邮箱、展示名长度和格式后重试。",
        ) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise _register_error(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="REGISTER_DB_ERROR",
            message="注册失败：数据库操作异常，请稍后重试。",
            reason="database_operation_failed",
            suggestion="若多次失败，请联系管理员排查数据库连接与约束。",
        ) from exc

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
    try:
        email = normalize_email(payload.email)
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if not user:
            raise _invalid_credentials()
        if user.status != "active":
            raise _login_error(
                status_code=status.HTTP_403_FORBIDDEN,
                code="LOGIN_USER_DISABLED",
                message="登录失败：账号已被禁用。",
                reason="user_disabled",
                suggestion="请联系管理员恢复账号状态，或确认是否在正确租户环境下。",
            )

        credential = db.execute(select(UserCredential).where(UserCredential.user_id == user.id)).scalar_one_or_none()
        if not credential:
            raise _login_error(
                status_code=status.HTTP_403_FORBIDDEN,
                code="LOGIN_CREDENTIAL_NOT_FOUND",
                message="登录失败：账号未配置本地登录凭据。",
                reason="credential_not_found",
                suggestion="请先完成注册流程，或使用外部身份登录方式。",
            )
        if credential.status != "active":
            raise _login_error(
                status_code=status.HTTP_403_FORBIDDEN,
                code="LOGIN_CREDENTIAL_DISABLED",
                message="登录失败：登录凭据已被禁用。",
                reason="credential_disabled",
                suggestion="请联系管理员恢复凭据状态或重置密码。",
            )
        if not verify_password(payload.password, credential.password_hash):
            raise _invalid_credentials()

        default_tenant_id = _resolve_user_default_tenant_id(db, user_id=user.id)
        token, exp_ts, expires_at, jti = issue_access_token(user, tenant_id=default_tenant_id)
        user.last_login_at = datetime.now(timezone.utc)
        db.commit()
        activate_user_session(user_session_id=str(user.id), jti=jti, exp_ts=exp_ts)
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise _login_error(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            code="LOGIN_DB_ERROR",
            message="登录失败：数据库操作异常，请稍后重试。",
            reason="database_operation_failed",
            suggestion="若多次失败，请联系管理员排查数据库连接与账户状态。",
        ) from exc

    return success(
        request,
        {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": expires_at,
            "expires_in": max(0, exp_ts - int(datetime.now(timezone.utc).timestamp())),
            "tenant_id": default_tenant_id,
        },
    )


@router.post(
    "/switch-tenant",
    summary="切换当前租户上下文",
    description="校验用户在目标租户内的 active 成员关系，并签发绑定该租户的新访问令牌。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[AuthLoginData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def switch_tenant(
    payload: AuthSwitchTenantRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """切换租户并签发绑定租户的新 token。"""
    tenant = db.get(Tenant, payload.tenant_id)
    if not tenant or tenant.status == TenantStatus.DELETED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "SWITCH_TENANT_NOT_FOUND",
                "message": "切换租户失败：目标租户不存在或已删除。",
                "details": {
                    "reason": "tenant_not_found",
                    "suggestion": "请确认租户 ID 是否正确，或重新获取可访问租户列表。",
                },
            },
        )

    membership = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == payload.tenant_id)
            .where(TenantMembership.user_id == user.id)
            .where(TenantMembership.status == MembershipStatus.ACTIVE)
        )
        .scalar_one_or_none()
    )
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "SWITCH_TENANT_FORBIDDEN",
                "message": "切换租户失败：当前用户不在目标租户的有效成员列表中。",
                "details": {
                    "reason": "tenant_membership_not_active",
                    "suggestion": "请确认是否已加入该租户，或联系租户管理员开通权限。",
                },
            },
        )

    token, exp_ts, expires_at, jti = issue_access_token(user, tenant_id=payload.tenant_id)
    user.last_login_at = datetime.now(timezone.utc)
    db.commit()
    activate_user_session(user_session_id=str(user.id), jti=jti, exp_ts=exp_ts)
    return success(
        request,
        {
            "access_token": token,
            "token_type": "bearer",
            "expires_at": expires_at,
            "expires_in": max(0, exp_ts - int(datetime.now(timezone.utc).timestamp())),
            "tenant_id": payload.tenant_id,
        },
        meta={"message": "租户切换成功，请在后续请求中使用新的访问令牌。"},
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
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
):
    """登出并拉黑当前访问令牌。"""
    jti = principal.claims.get("jti")
    exp = principal.claims.get("exp")
    session_uid = principal.claims.get("tkp_uid")
    revoked = False
    if isinstance(jti, str) and jti and isinstance(exp, int):
        revoke_token_jti(jti, exp)
        revoked = True
    if isinstance(session_uid, str) and session_uid and isinstance(jti, str) and jti:
        clear_user_session(user_session_id=session_uid, jti=jti)

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

