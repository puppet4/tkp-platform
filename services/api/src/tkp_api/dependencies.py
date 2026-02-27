"""请求上下文依赖。

职责:
1. 解析并校验 Authorization。
2. 将认证主体映射为本地 User。
3. 校验 X-Tenant-Id 对应的租户成员关系。
4. 生成后续路由统一使用的 RequestContext。
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.core.security import AuthenticatedPrincipal, parse_authorization_header
from tkp_api.db.session import get_db
from tkp_api.models.enums import MembershipStatus, TenantRole
from tkp_api.models.tenant import TenantMembership, User
from tkp_api.services.membership_sync import normalize_email


@dataclass
class RequestContext:
    """请求上下文。

    该对象在路由层作为统一输入，避免每个接口重复解析用户与租户关系。
    """

    # 当前请求用户 ID。
    user_id: UUID
    # 当前请求租户 ID。
    tenant_id: UUID
    # 当前用户在该租户内的角色。
    tenant_role: str
    # 认证主体原始信息（来自 JWT/开发模式令牌）。
    principal: AuthenticatedPrincipal


def _build_display_name(principal: AuthenticatedPrincipal) -> str:
    """构造用户展示名。"""
    if principal.display_name:
        return principal.display_name
    if principal.email:
        return principal.email.split("@")[0]
    return f"user-{principal.subject[:8]}"


def ensure_user(db: Session, principal: AuthenticatedPrincipal) -> User:
    """确保认证主体在本地存在对应用户记录。"""
    # 先按外部身份(认证提供方 + 主体标识)查找，保证与外部身份系统一一对应。
    stmt = select(User).where(User.auth_provider == principal.provider).where(
        User.external_subject == principal.subject
    )
    user = db.execute(stmt).scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if user:
        # 允许用户资料随外部身份系统变更自动刷新。
        if principal.email:
            normalized_email = normalize_email(principal.email)
            if user.email != normalized_email:
                user.email = normalized_email
        user.display_name = _build_display_name(principal)
        user.last_login_at = now
        db.flush()
        return user

    fallback_email = normalize_email(principal.email) if principal.email else f"{principal.subject}@local.dev"
    existing = db.execute(select(User).where(User.email == fallback_email)).scalar_one_or_none()
    if existing:
        # 历史用户通过邮箱兜底关联到外部身份。
        existing.auth_provider = principal.provider
        existing.external_subject = principal.subject
        existing.display_name = _build_display_name(principal)
        existing.last_login_at = now
        db.flush()
        return existing

    # 首次登录：创建本地用户。
    user = User(
        id=uuid4(),
        email=fallback_email,
        display_name=_build_display_name(principal),
        auth_provider=principal.provider,
        external_subject=principal.subject,
        last_login_at=now,
    )
    db.add(user)
    db.flush()
    return user


def get_current_user(
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> User:
    """仅做认证，不绑定租户上下文。"""
    principal = parse_authorization_header(authorization)
    user = ensure_user(db, principal)
    db.commit()
    db.refresh(user)
    return user


def get_current_user_id(user: User = Depends(get_current_user)) -> UUID:
    """返回当前用户 ID，便于轻量依赖注入。"""
    return user.id


def get_request_context(
    tenant_id_header: str | None = Header(default=None, alias="X-Tenant-Id"),
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: Session = Depends(get_db),
) -> RequestContext:
    """同时完成认证与租户成员关系授权。"""
    if not tenant_id_header:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="X-Tenant-Id required")

    try:
        tenant_id = UUID(tenant_id_header)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid X-Tenant-Id") from exc

    principal = parse_authorization_header(authorization)
    user = ensure_user(db, principal)

    # 所有租户内读写都依赖成员关系授权，拒绝“仅登录即可访问租户”。
    stmt = (
        select(TenantMembership)
        .where(TenantMembership.tenant_id == tenant_id)
        .where(TenantMembership.user_id == user.id)
        .where(TenantMembership.status == MembershipStatus.ACTIVE)
    )
    membership = db.execute(stmt).scalar_one_or_none()
    if not membership:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    db.commit()

    return RequestContext(
        user_id=user.id,
        tenant_id=tenant_id,
        tenant_role=membership.role,
        principal=principal,
    )


def require_tenant_roles(*allowed_roles: str):
    """按租户角色做路由级权限限制。"""

    def _dep(ctx: RequestContext = Depends(get_request_context)) -> RequestContext:
        if ctx.tenant_role not in allowed_roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")
        return ctx

    return _dep


# 租户层可写角色（可创建工作空间等）。
TENANT_EDITOR_ROLES = (TenantRole.OWNER, TenantRole.ADMIN, TenantRole.MEMBER)
# 租户管理角色（可变更成员角色等）。
TENANT_ADMIN_ROLES = (TenantRole.OWNER, TenantRole.ADMIN)
