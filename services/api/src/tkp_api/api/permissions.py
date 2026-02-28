"""权限管理接口。"""

from fastapi import APIRouter, Depends, HTTPException, Path, Request, status
from sqlalchemy.orm import Session

from tkp_api.dependencies import get_request_context
from tkp_api.db.session import get_db
from tkp_api.models.enums import TenantRole
from tkp_api.utils.response import success
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.permission import PermissionTemplatePublishRequest, RolePermissionUpdateRequest
from tkp_api.schemas.responses import (
    PermissionCatalogData,
    PermissionSnapshotData,
    PermissionTemplateData,
    PermissionTemplatePublishData,
    TenantRolePermissionData,
)
from tkp_api.services import (
    DEFAULT_PERMISSION_TEMPLATE_KEY,
    audit_log,
    default_permission_template,
    list_tenant_role_permission_matrix,
    list_tenant_actions,
    permission_catalog,
    publish_default_permission_template,
    reset_tenant_role_actions,
    set_tenant_role_actions,
)

router = APIRouter(prefix="/permissions")
_PERMISSION_RUNTIME_TAG = ["permissions-runtime"]
_PERMISSION_CONFIG_TAG = ["permissions-config"]

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
    "/me",
    tags=_PERMISSION_RUNTIME_TAG,
    summary="运行时权限快照（前端鉴权入口）",
    description="返回“当前用户 + 当前租户”的最终生效权限集合。该接口只读、无副作用，推荐前端只依赖本接口控制菜单、按钮和功能开关。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[PermissionSnapshotData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def my_permission_snapshot(
    request: Request,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """返回当前租户上下文下的权限快照。"""
    return success(
        request,
        {
            "tenant_role": ctx.tenant_role,
            "allowed_actions": list_tenant_actions(db, tenant_id=ctx.tenant_id, tenant_role=ctx.tenant_role),
        },
    )


@router.get(
    "/catalog",
    tags=_PERMISSION_CONFIG_TAG,
    summary="配置基线：权限点目录",
    description="返回系统可配置的权限码白名单全集。用于后台权限配置页面，不用于运行时鉴权。",
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
    tags=_PERMISSION_CONFIG_TAG,
    summary="配置基线：默认权限模板（只读）",
    description="返回系统内置的角色权限预设（role -> permission_codes）。该接口只查看模板，不会改动租户配置。",
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
    tags=_PERMISSION_CONFIG_TAG,
    summary="配置动作：发布默认权限模板（写入）",
    description="将默认模板真正写入当前租户角色权限。`overwrite_existing=true` 会覆盖现有配置；`false` 仅填充未配置角色。",
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
    tags=_PERMISSION_CONFIG_TAG,
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
    tags=_PERMISSION_CONFIG_TAG,
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
    tags=_PERMISSION_CONFIG_TAG,
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
