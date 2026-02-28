"""请求上下文依赖。

职责:
1. 解析并校验访问令牌。
2. 将认证主体映射为本地 User。
3. 仅校验 JWT 中的 tenant_id 作为租户上下文。
4. 生成后续路由统一使用的 RequestContext。
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from uuid import UUID, uuid4

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.core.security import AuthenticatedPrincipal, parse_authorization_header
from tkp_api.db.session import get_db
from tkp_api.models.enums import MembershipStatus, TenantRole
from tkp_api.models.tenant import TenantMembership, User
from tkp_api.services.membership_sync import normalize_email

bearer_scheme = HTTPBearer(auto_error=False)


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
    # 认证主体原始信息（来自 JWT）。
    principal: AuthenticatedPrincipal


def _build_display_name(principal: AuthenticatedPrincipal) -> str:
    """构造用户展示名。"""
    if principal.display_name:
        candidate = principal.display_name.strip()
    elif principal.email:
        candidate = principal.email.split("@")[0]
    else:
        candidate = f"user-{principal.subject[:8]}"

    if candidate:
        return candidate[:128]
    return "user"


def _normalize_external_subject(subject: str) -> str:
    """标准化 external_subject，防止写库超长。"""
    normalized = subject.strip()
    if not normalized:
        normalized = "anonymous"
    if len(normalized) <= 256:
        return normalized
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"hash:{digest}"


def _normalize_fallback_email(email: str | None, *, subject: str) -> str:
    """构造安全可落库的兜底邮箱。"""
    if email:
        normalized_email = normalize_email(email)
        if len(normalized_email) <= 256:
            return normalized_email

    local_subject = subject
    if len(local_subject) > 192:
        local_subject = hashlib.sha256(local_subject.encode("utf-8")).hexdigest()[:48]
    fallback = f"{local_subject}@local.dev"
    if len(fallback) <= 256:
        return fallback
    return f"user-{hashlib.sha256(subject.encode('utf-8')).hexdigest()[:32]}@local.dev"


def _extract_tenant_id_from_claims(principal: AuthenticatedPrincipal) -> UUID | None:
    """从认证声明中提取租户上下文。"""
    for key in ("tenant_id", "tid"):
        value = principal.claims.get(key)
        if not isinstance(value, str):
            continue
        try:
            return UUID(value)
        except ValueError:
            continue
    return None


def ensure_user(db: Session, principal: AuthenticatedPrincipal) -> User:
    """确保认证主体在本地存在对应用户记录。"""
    normalized_subject = _normalize_external_subject(principal.subject)
    # 先按外部身份(认证提供方 + 主体标识)查找，保证与外部身份系统一一对应。
    stmt = select(User).where(User.auth_provider == principal.provider).where(
        User.external_subject == normalized_subject
    )
    user = db.execute(stmt).scalar_one_or_none()
    now = datetime.now(timezone.utc)

    if user:
        # 允许用户资料随外部身份系统变更自动刷新。
        if principal.email:
            normalized_email = normalize_email(principal.email)
            if len(normalized_email) <= 256 and user.email != normalized_email:
                user.email = normalized_email
        user.display_name = _build_display_name(principal)
        user.last_login_at = now
        db.flush()
        return user

    fallback_email = _normalize_fallback_email(principal.email, subject=normalized_subject)
    existing = db.execute(select(User).where(User.email == fallback_email)).scalar_one_or_none()
    if existing:
        # 历史用户通过邮箱兜底关联到外部身份。
        existing.auth_provider = principal.provider
        existing.external_subject = normalized_subject
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
        external_subject=normalized_subject,
        last_login_at=now,
    )
    db.add(user)
    db.flush()
    return user


def get_current_principal(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> AuthenticatedPrincipal:
    """提取并解析当前请求认证主体。"""
    authorization = None
    if credentials is not None and credentials.credentials:
        authorization = f"{credentials.scheme} {credentials.credentials}"
    return parse_authorization_header(authorization)


def get_current_user(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> User:
    """仅做认证，不绑定租户上下文。"""
    user = ensure_user(db, principal)
    db.commit()
    db.refresh(user)
    return user


def get_current_user_id(user: User = Depends(get_current_user)) -> UUID:
    """返回当前用户 ID，便于轻量依赖注入。"""
    return user.id


def get_request_context(
    principal: AuthenticatedPrincipal = Depends(get_current_principal),
    db: Session = Depends(get_db),
) -> RequestContext:
    """同时完成认证与租户成员关系授权。"""
    user = ensure_user(db, principal)
    tenant_id = _extract_tenant_id_from_claims(principal)
    if tenant_id is None:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "TENANT_CONTEXT_REQUIRED",
                "message": "缺少租户上下文。",
                "details": {
                    "reason": "missing_tenant_context",
                    "suggestion": "请先登录获取已绑定 tenant_id 的访问令牌，或调用 /api/auth/switch-tenant 切换租户后重试。",
                },
            },
        )

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
