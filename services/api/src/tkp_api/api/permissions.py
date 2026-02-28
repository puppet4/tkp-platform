"""权限管理接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.dependencies import get_request_context
from tkp_api.db.session import get_db
from tkp_api.models.enums import MembershipStatus, TenantRole
from tkp_api.models.tenant import TenantMembership, User
from tkp_api.utils.response import success
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.permission import PermissionTemplatePublishRequest, RolePermissionUpdateRequest
from tkp_api.schemas.responses import (
    PermissionCatalogData,
    PermissionTemplateData,
    PermissionTemplatePublishData,
    RoleUserBindingData,
    TenantRolePermissionData,
)
from tkp_api.services.membership_sync import sync_workspace_memberships_for_tenant_member
from tkp_api.services import (
    DEFAULT_PERMISSION_TEMPLATE_KEY,
    audit_log,
    default_permission_template,
    list_tenant_role_permission_matrix,
    permission_catalog,
    publish_default_permission_template,
    reset_tenant_role_actions,
    set_tenant_role_actions,
)

router = APIRouter(prefix="/permissions", tags=["permissions"])

_PERMISSION_ADMIN_ROLES = {TenantRole.OWNER, TenantRole.ADMIN}
_TENANT_ROLES = {TenantRole.OWNER, TenantRole.ADMIN, TenantRole.MEMBER, TenantRole.VIEWER}


def _ensure_permission_admin(role: str) -> None:
    """权限管理接口入口校验。"""
    if role not in _PERMISSION_ADMIN_ROLES:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def _normalize_role(role: str) -> str:
    """规范化并校验角色参数。"""
    role_value = role.strip()
    if role_value not in _TENANT_ROLES:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid role")
    return role_value


@router.get(
    "/catalog",
    summary="查询权限点目录",
    description="返回系统内可用权限点编码列表，供前端菜单/按钮/功能/API 绑定。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[PermissionCatalogData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def get_permission_catalog(
    request: Request,
    ctx=Depends(get_request_context),
):
    """返回权限点目录。"""
    _ensure_permission_admin(ctx.tenant_role)
    return success(request, {"permission_codes": permission_catalog()})


@router.get(
    "/templates/default",
    summary="查询默认权限模板",
    description="返回系统内置的角色权限模板（可用于菜单/按钮/功能/API 一体化发布）。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[PermissionTemplateData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def get_default_template(
    request: Request,
    ctx=Depends(get_request_context),
):
    """查询默认权限模板。"""
    _ensure_permission_admin(ctx.tenant_role)
    template = default_permission_template()
    role_permissions = [
        {"role": role, "permission_codes": codes}
        for role, codes in template["role_permissions"].items()
    ]
    return success(
        request,
        {
            "template_key": template["template_key"],
            "version": template["version"],
            "catalog": template["catalog"],
            "role_permissions": role_permissions,
        },
    )


@router.post(
    "/templates/default/publish",
    summary="发布默认权限模板",
    description="将默认模板发布到当前租户（可覆盖已有配置或仅填充未配置角色）。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[PermissionTemplatePublishData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def publish_default_template(
    payload: PermissionTemplatePublishRequest,
    request: Request,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """发布默认权限模板到当前租户。"""
    _ensure_permission_admin(ctx.tenant_role)
    matrix = publish_default_permission_template(
        db,
        tenant_id=ctx.tenant_id,
        overwrite_existing=payload.overwrite_existing,
    )
    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="permission.template.publish",
        resource_type="tenant_role_permission",
        resource_id=str(ctx.tenant_id),
        after_json={
            "template_key": DEFAULT_PERMISSION_TEMPLATE_KEY,
            "overwrite_existing": payload.overwrite_existing,
            "roles": {role: codes for role, codes in matrix.items()},
        },
    )
    db.commit()
    return success(
        request,
        {
            "template_key": DEFAULT_PERMISSION_TEMPLATE_KEY,
            "version": default_permission_template()["version"],
            "overwrite_existing": payload.overwrite_existing,
            "role_permissions": [{"role": role, "permission_codes": codes} for role, codes in matrix.items()],
        },
    )


@router.get(
    "/roles",
    summary="查询租户角色权限矩阵",
    description="返回当前租户的角色权限映射，用于权限配置页面展示。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[TenantRolePermissionData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def list_role_permissions(
    request: Request,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询当前租户角色权限映射。"""
    _ensure_permission_admin(ctx.tenant_role)
    matrix = list_tenant_role_permission_matrix(db, tenant_id=ctx.tenant_id)
    data = [{"role": role, "permission_codes": codes} for role, codes in matrix.items()]
    return success(request, data)


@router.put(
    "/roles/{role}",
    summary="更新租户角色权限",
    description="覆盖更新当前租户某角色的权限点编码集合。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantRolePermissionData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def update_role_permissions(
    payload: RolePermissionUpdateRequest,
    request: Request,
    role: str = Path(..., description="角色标识（owner/admin/member/viewer）。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """更新指定角色权限。"""
    _ensure_permission_admin(ctx.tenant_role)
    role_value = _normalize_role(role)

    before = list_tenant_role_permission_matrix(db, tenant_id=ctx.tenant_id).get(role_value, [])
    current = set_tenant_role_actions(
        db,
        tenant_id=ctx.tenant_id,
        role=role_value,
        permission_codes=payload.permission_codes,
    )
    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="permission.role.update",
        resource_type="tenant_role_permission",
        resource_id=f"{ctx.tenant_id}:{role_value}",
        before_json={"permission_codes": before},
        after_json={"permission_codes": current},
    )
    db.commit()
    return success(request, {"role": role_value, "permission_codes": current})


@router.delete(
    "/roles/{role}",
    summary="重置角色权限为默认值",
    description="清空当前租户自定义配置，恢复指定角色的系统默认权限集合。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[TenantRolePermissionData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def reset_role_permissions(
    request: Request,
    role: str = Path(..., description="角色标识（owner/admin/member/viewer）。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """重置指定角色权限。"""
    _ensure_permission_admin(ctx.tenant_role)
    role_value = _normalize_role(role)

    before = list_tenant_role_permission_matrix(db, tenant_id=ctx.tenant_id).get(role_value, [])
    current = reset_tenant_role_actions(db, tenant_id=ctx.tenant_id, role=role_value)
    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="permission.role.reset",
        resource_type="tenant_role_permission",
        resource_id=f"{ctx.tenant_id}:{role_value}",
        before_json={"permission_codes": before},
        after_json={"permission_codes": current},
    )
    db.commit()
    return success(request, {"role": role_value, "permission_codes": current})


@router.get(
    "/roles/{role}/users",
    summary="查询角色绑定用户",
    description="返回当前租户内指定角色绑定的用户列表（用户-角色关系）。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[RoleUserBindingData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def list_role_users(
    request: Request,
    role: str = Path(..., description="角色标识（owner/admin/member/viewer）。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询角色绑定用户。"""
    _ensure_permission_admin(ctx.tenant_role)
    role_value = _normalize_role(role)

    memberships = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == ctx.tenant_id)
            .where(TenantMembership.role == role_value)
        )
        .scalars()
        .all()
    )
    user_ids = list({membership.user_id for membership in memberships})
    user_map: dict[UUID, User] = {}
    if user_ids:
        users = db.execute(select(User).where(User.id.in_(user_ids))).scalars().all()
        user_map = {user.id: user for user in users}

    data = [
        {
            "role": role_value,
            "tenant_id": ctx.tenant_id,
            "user_id": membership.user_id,
            "email": user.email,
            "display_name": user.display_name,
            "membership_status": membership.status,
        }
        for membership in memberships
        if (user := user_map.get(membership.user_id)) is not None
    ]
    return success(request, data)


@router.put(
    "/roles/{role}/users/{user_id}",
    summary="绑定用户到角色",
    description="将当前租户内指定用户绑定到目标角色。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[RoleUserBindingData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def bind_role_user(
    request: Request,
    role: str = Path(..., description="角色标识（owner/admin/member/viewer）。"),
    user_id: UUID = Path(..., description="目标用户 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """绑定用户到角色。"""
    _ensure_permission_admin(ctx.tenant_role)
    role_value = _normalize_role(role)

    membership = (
        db.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == ctx.tenant_id)
            .where(TenantMembership.user_id == user_id)
        )
        .scalar_one_or_none()
    )
    if not membership:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="membership not found")

    if membership.role == TenantRole.OWNER and role_value != TenantRole.OWNER:
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
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="cannot downgrade last owner")

    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="user not found")

    before = {"role": membership.role, "status": membership.status}
    membership.role = role_value
    membership.status = MembershipStatus.ACTIVE
    sync_workspace_memberships_for_tenant_member(
        db,
        tenant_id=ctx.tenant_id,
        user_id=user_id,
        tenant_role=membership.role,
    )

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="permission.role.user.bind",
        resource_type="tenant_membership",
        resource_id=str(membership.id),
        before_json=before,
        after_json={"role": membership.role, "status": membership.status},
    )
    db.commit()

    return success(
        request,
        {
            "role": role_value,
            "tenant_id": ctx.tenant_id,
            "user_id": user.id,
            "email": user.email,
            "display_name": user.display_name,
            "membership_status": membership.status,
        },
    )
