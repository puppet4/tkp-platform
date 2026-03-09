"""用户管理接口。"""

import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from tkp_api.db.session import get_db
from tkp_api.dependencies import get_request_context
from tkp_api.models.enums import MembershipStatus, TenantRole
from tkp_api.models.knowledge import KBMembership
from tkp_api.models.tenant import TenantMembership, User
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import TenantUserData
from tkp_api.schemas.user import UserUpdateRequest
from tkp_api.services import PermissionAction, audit_log, require_tenant_action
from tkp_api.services.membership_sync import disable_workspace_memberships_for_tenant_member
from tkp_api.utils.response import success
from tkp_api.utils.permissions import is_admin_role

router = APIRouter(prefix="/users", tags=["users"])


class UserPreferencesUpsertRequest(BaseModel):
    """用户偏好设置请求体。"""

    theme: str = Field(default="light", description="主题（light/dark）。")
    language: str = Field(default="zh-CN", description="界面语言。")
    timezone: str = Field(default="Asia/Shanghai", description="时区。")
    notifications: dict[str, bool] = Field(default_factory=dict, description="通知偏好。")
    security: dict[str, bool] = Field(default_factory=dict, description="安全偏好。")


def _ensure_user_preferences_table(db: Session) -> None:
    """确保用户偏好表存在（兼容本地未跑迁移环境）。"""
    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS user_preferences (
                tenant_id VARCHAR(36) NOT NULL,
                user_id VARCHAR(36) NOT NULL,
                payload TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (tenant_id, user_id)
            )
            """
        )
    )
    db.commit()


def _can_access_preferences(*, ctx, user_id: UUID) -> bool:
    return ctx.user_id == user_id or is_admin_role(ctx)


@router.get(
    "",
    summary="查询租户用户列表",
    description="返回当前租户下的用户及其成员关系。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[TenantUserData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def list_users(
    request: Request,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询当前租户用户列表。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.USER_READ,
    )

    memberships = db.execute(
        select(TenantMembership).where(TenantMembership.tenant_id == ctx.tenant_id)
    ).scalars().all()
    user_ids = list({membership.user_id for membership in memberships})

    users: list[User] = []
    if user_ids:
        users = list(db.execute(select(User).where(User.id.in_(user_ids))).scalars().all())
    user_map = {user.id: user for user in users}

    data = [
        {
            "user_id": membership.user_id,
            "email": user.email,
            "display_name": user.display_name,
            "user_status": user.status,
            "tenant_role": membership.role,
            "membership_status": membership.status,
        }
        for membership in memberships
        if (user := user_map.get(membership.user_id)) is not None
    ]
    return success(request, data)


@router.get(
    "/{user_id}",
    summary="查询租户用户详情",
    description="返回目标用户在当前租户下的角色与状态。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantUserData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_user(
    request: Request,
    user_id: UUID = Path(..., description="目标用户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询单个租户用户详情。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.USER_READ,
    )

    membership = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == ctx.tenant_id)
            .where(TenantMembership.user_id == user_id)
        )
        .scalar_one_or_none()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not in tenant")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    return success(
        request,
        {
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "user_status": user.status,
            "tenant_role": membership.role,
            "membership_status": membership.status,
        },
    )


@router.patch(
    "/{user_id}",
    summary="更新用户资料",
    description="更新用户展示名或状态（仅限租户管理员）。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantUserData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_user(
    payload: UserUpdateRequest,
    request: Request,
    user_id: UUID = Path(..., description="目标用户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """更新用户资料。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.USER_UPDATE,
    )

    membership = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == ctx.tenant_id)
            .where(TenantMembership.user_id == user_id)
        )
        .scalar_one_or_none()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not in tenant")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    before = {"display_name": user.display_name, "status": user.status}
    if payload.display_name is not None:
        user.display_name = payload.display_name
    if payload.status is not None:
        user.status = payload.status

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="user.update",
        resource_type="user",
        resource_id=str(user.id),
        before_json=before,
        after_json={"display_name": user.display_name, "status": user.status},
    )
    db.commit()

    return success(
        request,
        {
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "user_status": user.status,
            "tenant_role": membership.role,
            "membership_status": membership.status,
        },
    )


@router.delete(
    "/{user_id}",
    summary="移除租户用户",
    description="将目标用户在当前租户的成员关系置为 disabled，必要时禁用用户状态。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantUserData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def remove_user(
    request: Request,
    user_id: UUID = Path(..., description="目标用户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """移除当前租户中的用户成员关系。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.USER_DELETE,
    )

    membership = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == ctx.tenant_id)
            .where(TenantMembership.user_id == user_id)
        )
        .scalar_one_or_none()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not in tenant")

    if membership.role == TenantRole.OWNER and membership.status == MembershipStatus.ACTIVE:
        owners = (
            db.execute(
                select(TenantMembership)
                .where(TenantMembership.tenant_id == ctx.tenant_id)
                .where(TenantMembership.role == TenantRole.OWNER)
                .where(TenantMembership.status == MembershipStatus.ACTIVE)
            )
            .scalars()
            .all()
        )
        if len(owners) <= 1:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cannot remove last owner")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    before = {"user_status": user.status, "membership_status": membership.status}
    membership.status = MembershipStatus.DISABLED
    disable_workspace_memberships_for_tenant_member(
        db,
        tenant_id=ctx.tenant_id,
        user_id=user_id,
    )
    kb_memberships = (
        db.execute(
            select(KBMembership)
            .where(KBMembership.tenant_id == ctx.tenant_id)
            .where(KBMembership.user_id == user_id)
        )
        .scalars()
        .all()
    )
    for kb_membership in kb_memberships:
        kb_membership.status = MembershipStatus.DISABLED

    # 当前会话默认 autoflush=False，先手动 flush 再查询，避免读到旧状态。
    db.flush()
    active_memberships = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.user_id == user_id)
            .where(TenantMembership.status == MembershipStatus.ACTIVE)
        )
        .scalars()
        .all()
    )
    if not active_memberships:
        user.status = "disabled"

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="user.remove",
        resource_type="tenant_membership",
        resource_id=str(membership.id),
        before_json=before,
        after_json={"user_status": user.status, "membership_status": membership.status},
    )
    db.commit()

    return success(
        request,
        {
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "user_status": user.status,
            "tenant_role": membership.role,
            "membership_status": membership.status,
        },
    )


@router.get(
    "/{user_id}/preferences",
    summary="查询用户偏好设置",
    description="返回指定用户在当前租户下的界面与通知偏好。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_user_preferences(
    request: Request,
    user_id: UUID = Path(..., description="目标用户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询用户偏好设置。"""
    if not _can_access_preferences(ctx=ctx, user_id=user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    _ensure_user_preferences_table(db)
    row = db.execute(
        text(
            """
            SELECT payload
            FROM user_preferences
            WHERE tenant_id = :tenant_id
              AND user_id = :user_id
            """
        ),
        {"tenant_id": str(ctx.tenant_id), "user_id": str(user_id)},
    ).fetchone()
    payload: dict = {}
    if row and isinstance(row.payload, str):
        try:
            parsed = json.loads(row.payload)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}

    return success(
        request,
        {
            "theme": payload.get("theme", "light"),
            "language": payload.get("language", "zh-CN"),
            "timezone": payload.get("timezone", "Asia/Shanghai"),
            "notifications": payload.get(
                "notifications",
                {"email": True, "browser": True, "alerts": True},
            ),
            "security": payload.get(
                "security",
                {"password_reset_email": True, "two_factor_enabled": False},
            ),
        },
    )


@router.put(
    "/{user_id}/preferences",
    summary="更新用户偏好设置",
    description="更新指定用户在当前租户下的界面与通知偏好。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse,
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def upsert_user_preferences(
    payload: UserPreferencesUpsertRequest,
    request: Request,
    user_id: UUID = Path(..., description="目标用户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """更新用户偏好设置。"""
    if not _can_access_preferences(ctx=ctx, user_id=user_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")

    _ensure_user_preferences_table(db)
    encoded_payload = json.dumps(
        {
            "theme": payload.theme,
            "language": payload.language,
            "timezone": payload.timezone,
            "notifications": payload.notifications,
            "security": payload.security,
        },
        ensure_ascii=False,
    )
    update_result = db.execute(
        text(
            """
            UPDATE user_preferences
            SET payload = :payload, updated_at = CURRENT_TIMESTAMP
            WHERE tenant_id = :tenant_id
              AND user_id = :user_id
            """
        ),
        {"payload": encoded_payload, "tenant_id": str(ctx.tenant_id), "user_id": str(user_id)},
    )
    if int(getattr(update_result, "rowcount", 0) or 0) == 0:
        db.execute(
            text(
                """
                INSERT INTO user_preferences (tenant_id, user_id, payload)
                VALUES (:tenant_id, :user_id, :payload)
                """
            ),
            {"tenant_id": str(ctx.tenant_id), "user_id": str(user_id), "payload": encoded_payload},
        )
    db.commit()
    return success(
        request,
        {
            "theme": payload.theme,
            "language": payload.language,
            "timezone": payload.timezone,
            "notifications": payload.notifications,
            "security": payload.security,
        },
    )
