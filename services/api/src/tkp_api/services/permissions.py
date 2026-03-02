"""统一权限动作框架（数据库驱动）。"""

from enum import StrEnum
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from tkp_api.models.enums import KBRole, TenantRole, WorkspaceRole
from tkp_api.models.permission import TenantRolePermission


class PermissionAction(StrEnum):
    """后端接口鉴权动作定义。"""

    TENANT_READ = "api.tenant.read"
    TENANT_UPDATE = "api.tenant.update"
    TENANT_DELETE = "api.tenant.delete"
    TENANT_MEMBER_MANAGE = "api.tenant.member.manage"

    USER_READ = "api.user.read"
    USER_UPDATE = "api.user.update"
    USER_DELETE = "api.user.delete"

    WORKSPACE_CREATE = "api.workspace.create"
    WORKSPACE_READ = "api.workspace.read"
    WORKSPACE_UPDATE = "api.workspace.update"
    WORKSPACE_DELETE = "api.workspace.delete"
    WORKSPACE_MEMBER_MANAGE = "api.workspace.member.manage"

    KB_CREATE = "api.kb.create"
    KB_READ = "api.kb.read"
    KB_UPDATE = "api.kb.update"
    KB_DELETE = "api.kb.delete"
    KB_MEMBER_MANAGE = "api.kb.member.manage"

    DOCUMENT_READ = "api.document.read"
    DOCUMENT_WRITE = "api.document.write"
    DOCUMENT_DELETE = "api.document.delete"

    RETRIEVAL_QUERY = "api.retrieval.query"
    CHAT_COMPLETION = "api.chat.completion"

    AGENT_RUN_CREATE = "api.agent.run.create"
    AGENT_RUN_READ = "api.agent.run.read"
    AGENT_RUN_CANCEL = "api.agent.run.cancel"


_ACTION_VALUES = {action.value for action in PermissionAction}
_LEGACY_TO_API_ACTIONS = {
    action.value.removeprefix("api."): action.value
    for action in PermissionAction
    if action.value.startswith("api.")
}


_OWNER_ACTIONS = {action.value for action in PermissionAction}
_ADMIN_ACTIONS = {
    PermissionAction.TENANT_READ.value,
    PermissionAction.TENANT_UPDATE.value,
    PermissionAction.TENANT_MEMBER_MANAGE.value,
    PermissionAction.USER_READ.value,
    PermissionAction.USER_UPDATE.value,
    PermissionAction.USER_DELETE.value,
    PermissionAction.WORKSPACE_CREATE.value,
    PermissionAction.WORKSPACE_READ.value,
    PermissionAction.WORKSPACE_UPDATE.value,
    PermissionAction.WORKSPACE_DELETE.value,
    PermissionAction.WORKSPACE_MEMBER_MANAGE.value,
    PermissionAction.KB_CREATE.value,
    PermissionAction.KB_READ.value,
    PermissionAction.KB_UPDATE.value,
    PermissionAction.KB_DELETE.value,
    PermissionAction.KB_MEMBER_MANAGE.value,
    PermissionAction.DOCUMENT_READ.value,
    PermissionAction.DOCUMENT_WRITE.value,
    PermissionAction.DOCUMENT_DELETE.value,
    PermissionAction.RETRIEVAL_QUERY.value,
    PermissionAction.CHAT_COMPLETION.value,
    PermissionAction.AGENT_RUN_CREATE.value,
    PermissionAction.AGENT_RUN_READ.value,
    PermissionAction.AGENT_RUN_CANCEL.value,
}
_MEMBER_ACTIONS = {
    PermissionAction.TENANT_READ.value,
    PermissionAction.WORKSPACE_CREATE.value,
    PermissionAction.WORKSPACE_READ.value,
    PermissionAction.KB_READ.value,
    PermissionAction.DOCUMENT_READ.value,
    PermissionAction.RETRIEVAL_QUERY.value,
    PermissionAction.CHAT_COMPLETION.value,
    PermissionAction.AGENT_RUN_CREATE.value,
    PermissionAction.AGENT_RUN_READ.value,
    PermissionAction.AGENT_RUN_CANCEL.value,
}
_VIEWER_ACTIONS = {
    PermissionAction.TENANT_READ.value,
    PermissionAction.WORKSPACE_READ.value,
    PermissionAction.KB_READ.value,
    PermissionAction.DOCUMENT_READ.value,
    PermissionAction.RETRIEVAL_QUERY.value,
    PermissionAction.CHAT_COMPLETION.value,
    PermissionAction.AGENT_RUN_CREATE.value,
    PermissionAction.AGENT_RUN_READ.value,
    PermissionAction.AGENT_RUN_CANCEL.value,
}

DEFAULT_UI_PERMISSIONS: list[str] = [
    "menu.tenant",
    "menu.workspace",
    "menu.kb",
    "menu.document",
    "menu.user",
    "button.tenant.update",
    "button.tenant.delete",
    "button.workspace.create",
    "button.workspace.update",
    "button.workspace.delete",
    "button.kb.create",
    "button.kb.update",
    "button.kb.delete",
    "button.document.upload",
    "button.document.update",
    "button.document.delete",
    "button.user.delete",
    "button.member.add",
    "button.member.remove",
    "feature.auth.permissions",
]
PERMISSION_UI_MANIFEST_VERSION = "2026-03-02"

PERMISSION_UI_MANIFEST: dict[str, list[dict[str, str | list[str]]]] = {
    "menus": [
        {"code": "menu.tenant", "name": "租户管理", "required_actions": [PermissionAction.TENANT_READ.value]},
        {"code": "menu.workspace", "name": "工作空间", "required_actions": [PermissionAction.WORKSPACE_READ.value]},
        {"code": "menu.kb", "name": "知识库", "required_actions": [PermissionAction.KB_READ.value]},
        {"code": "menu.document", "name": "文档中心", "required_actions": [PermissionAction.DOCUMENT_READ.value]},
        {"code": "menu.user", "name": "用户管理", "required_actions": [PermissionAction.USER_READ.value]},
    ],
    "buttons": [
        {"code": "button.tenant.update", "name": "编辑租户", "required_actions": [PermissionAction.TENANT_UPDATE.value]},
        {"code": "button.tenant.delete", "name": "删除租户", "required_actions": [PermissionAction.TENANT_DELETE.value]},
        {
            "code": "button.workspace.create",
            "name": "创建工作空间",
            "required_actions": [PermissionAction.WORKSPACE_CREATE.value],
        },
        {"code": "button.workspace.update", "name": "编辑工作空间", "required_actions": [PermissionAction.WORKSPACE_UPDATE.value]},
        {"code": "button.workspace.delete", "name": "删除工作空间", "required_actions": [PermissionAction.WORKSPACE_DELETE.value]},
        {"code": "button.kb.create", "name": "创建知识库", "required_actions": [PermissionAction.KB_CREATE.value]},
        {"code": "button.kb.update", "name": "编辑知识库", "required_actions": [PermissionAction.KB_UPDATE.value]},
        {"code": "button.kb.delete", "name": "删除知识库", "required_actions": [PermissionAction.KB_DELETE.value]},
        {"code": "button.document.upload", "name": "上传文档", "required_actions": [PermissionAction.DOCUMENT_WRITE.value]},
        {"code": "button.document.update", "name": "编辑文档", "required_actions": [PermissionAction.DOCUMENT_WRITE.value]},
        {"code": "button.document.delete", "name": "删除文档", "required_actions": [PermissionAction.DOCUMENT_DELETE.value]},
        {"code": "button.user.delete", "name": "删除用户", "required_actions": [PermissionAction.USER_DELETE.value]},
        {
            "code": "button.member.add",
            "name": "添加成员",
            "required_actions": [PermissionAction.TENANT_MEMBER_MANAGE.value],
        },
        {
            "code": "button.member.remove",
            "name": "移除成员",
            "required_actions": [PermissionAction.TENANT_MEMBER_MANAGE.value],
        },
    ],
    "features": [
        {
            "code": "feature.auth.permissions",
            "name": "权限配置中心",
            "required_actions": [PermissionAction.TENANT_MEMBER_MANAGE.value],
        },
    ],
}

_OWNER_UI_CODES = set(DEFAULT_UI_PERMISSIONS)
_ADMIN_UI_CODES = set(DEFAULT_UI_PERMISSIONS)
_MEMBER_UI_CODES = {
    "menu.workspace",
    "menu.kb",
    "menu.document",
    "button.document.upload",
    "button.document.update",
    "button.document.delete",
}
_VIEWER_UI_CODES = {
    "menu.workspace",
    "menu.kb",
    "menu.document",
}

DEFAULT_TENANT_ROLE_ACTIONS: dict[str, set[str]] = {
    TenantRole.OWNER: _OWNER_ACTIONS | _OWNER_UI_CODES,
    TenantRole.ADMIN: _ADMIN_ACTIONS | _ADMIN_UI_CODES,
    TenantRole.MEMBER: _MEMBER_ACTIONS | _MEMBER_UI_CODES,
    TenantRole.VIEWER: _VIEWER_ACTIONS | _VIEWER_UI_CODES,
}
DEFAULT_PERMISSION_TEMPLATE_KEY = "default"
DEFAULT_PERMISSION_TEMPLATE_VERSION = "2026-02-28"
_TEMPLATE_ROLES = (TenantRole.OWNER, TenantRole.ADMIN, TenantRole.MEMBER, TenantRole.VIEWER)


def _forbidden() -> HTTPException:
    """统一 403 异常。"""
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def permission_catalog() -> list[str]:
    """返回权限点目录（含 API 动作与推荐 UI 权限码）。"""
    api_codes = sorted(action.value for action in PermissionAction)
    return sorted(set(api_codes + DEFAULT_UI_PERMISSIONS))


def permission_ui_manifest(db: Session, *, tenant_id: UUID, tenant_role: str) -> dict[str, object]:
    """返回前端菜单/按钮/功能与后端动作权限的绑定结果。"""
    allowed_actions = list_tenant_actions(db, tenant_id=tenant_id, tenant_role=tenant_role)
    allowed_set = set(allowed_actions)

    def _resolve_items(items: list[dict[str, str | list[str]]]) -> list[dict[str, object]]:
        resolved: list[dict[str, object]] = []
        for item in items:
            code = str(item["code"])
            required_actions = [str(action) for action in item["required_actions"]]
            resolved.append(
                {
                    "code": code,
                    "name": str(item["name"]),
                    "required_actions": required_actions,
                    "allowed": code in allowed_set and all(action in allowed_set for action in required_actions),
                }
            )
        return resolved

    return {
        "version": PERMISSION_UI_MANIFEST_VERSION,
        "tenant_role": tenant_role,
        "allowed_actions": allowed_actions,
        "menus": _resolve_items(PERMISSION_UI_MANIFEST["menus"]),
        "buttons": _resolve_items(PERMISSION_UI_MANIFEST["buttons"]),
        "features": _resolve_items(PERMISSION_UI_MANIFEST["features"]),
    }


def _normalize_permission_code(code: str) -> str:
    """规范化权限编码。

    兼容历史权限码：`tenant.read` -> `api.tenant.read`。
    """
    normalized = code.strip()
    if not normalized:
        return normalized
    if normalized in _ACTION_VALUES:
        return normalized
    return _LEGACY_TO_API_ACTIONS.get(normalized, normalized)


def _load_role_permissions(db: Session, *, tenant_id: UUID, role: str) -> list[str]:
    """读取指定租户角色的权限点。"""
    rows = (
        db.execute(
            select(TenantRolePermission.permission_code)
            .where(TenantRolePermission.tenant_id == tenant_id)
            .where(TenantRolePermission.role == role)
        )
        .scalars()
        .all()
    )
    return rows


def _normalize_permission_codes(permission_codes: list[str]) -> list[str]:
    """规范化、去重权限编码。"""
    return sorted({_normalize_permission_code(code) for code in permission_codes if code.strip()})


def _validate_catalog_permission_codes(permission_codes: list[str]) -> list[str]:
    """校验权限编码是否在白名单目录中。"""
    normalized = _normalize_permission_codes(permission_codes)
    catalog_set = set(permission_catalog())
    invalid_codes = [code for code in normalized if code not in catalog_set]
    if invalid_codes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={"message": "invalid permission codes", "invalid_codes": invalid_codes},
        )
    return normalized


def list_tenant_actions(db: Session, *, tenant_id: UUID, tenant_role: str) -> list[str]:
    """返回当前租户角色可执行权限点。

    规则：
    1. 角色有租户级配置时，使用数据库配置。
    2. 未配置时，回退到内置默认映射。
    """
    configured = _load_role_permissions(db, tenant_id=tenant_id, role=tenant_role)
    if configured:
        catalog_set = set(permission_catalog())
        return sorted(
            {
                normalized
                for code in configured
                if code.strip()
                if (normalized := _normalize_permission_code(code)) in catalog_set
            }
        )
    return sorted(DEFAULT_TENANT_ROLE_ACTIONS.get(tenant_role, set()))


def list_tenant_role_permission_matrix(db: Session, *, tenant_id: UUID) -> dict[str, list[str]]:
    """返回当前租户所有角色权限映射。"""
    matrix: dict[str, list[str]] = {}
    for role in _TEMPLATE_ROLES:
        matrix[role] = list_tenant_actions(db, tenant_id=tenant_id, tenant_role=role)
    return matrix


def set_tenant_role_actions(
    db: Session,
    *,
    tenant_id: UUID,
    role: str,
    permission_codes: list[str],
) -> list[str]:
    """覆盖设置租户角色权限点。"""
    normalized = _validate_catalog_permission_codes(permission_codes)
    db.execute(
        delete(TenantRolePermission)
        .where(TenantRolePermission.tenant_id == tenant_id)
        .where(TenantRolePermission.role == role)
    )
    for code in normalized:
        db.add(TenantRolePermission(tenant_id=tenant_id, role=role, permission_code=code))
    db.flush()
    return normalized


def reset_tenant_role_actions(db: Session, *, tenant_id: UUID, role: str) -> list[str]:
    """重置为系统默认角色权限。"""
    db.execute(
        delete(TenantRolePermission)
        .where(TenantRolePermission.tenant_id == tenant_id)
        .where(TenantRolePermission.role == role)
    )
    db.flush()
    return sorted(DEFAULT_TENANT_ROLE_ACTIONS.get(role, set()))


def default_permission_template() -> dict[str, object]:
    """返回系统默认权限模板。"""
    role_permissions = {
        role: sorted(DEFAULT_TENANT_ROLE_ACTIONS.get(role, set()))
        for role in _TEMPLATE_ROLES
    }
    return {
        "template_key": DEFAULT_PERMISSION_TEMPLATE_KEY,
        "version": DEFAULT_PERMISSION_TEMPLATE_VERSION,
        "role_permissions": role_permissions,
        "catalog": permission_catalog(),
    }


def publish_default_permission_template(
    db: Session,
    *,
    tenant_id: UUID,
    overwrite_existing: bool = True,
) -> dict[str, list[str]]:
    """将默认权限模板发布到指定租户。"""
    template = default_permission_template()
    role_permissions: dict[str, list[str]] = template["role_permissions"]  # type: ignore[assignment]
    result: dict[str, list[str]] = {}
    for role in _TEMPLATE_ROLES:
        existing = _load_role_permissions(db, tenant_id=tenant_id, role=role)
        if existing and not overwrite_existing:
            result[role] = list_tenant_actions(db, tenant_id=tenant_id, tenant_role=role)
            continue
        result[role] = set_tenant_role_actions(
            db,
            tenant_id=tenant_id,
            role=role,
            permission_codes=role_permissions.get(role, []),
        )
    return result


def require_tenant_action(
    db: Session,
    *,
    tenant_id: UUID,
    tenant_role: str,
    action: PermissionAction,
) -> None:
    """要求当前租户角色具备指定动作权限。"""
    actions = set(list_tenant_actions(db, tenant_id=tenant_id, tenant_role=tenant_role))
    if action.value not in actions:
        raise _forbidden()


def can_manage_workspace_members(*, tenant_role: str, workspace_role: str | None) -> bool:
    """判断是否可管理工作空间成员。"""
    if tenant_role in {TenantRole.OWNER, TenantRole.ADMIN}:
        return True
    return workspace_role == WorkspaceRole.OWNER


def can_manage_kb_members(*, tenant_role: str, workspace_role: str | None, kb_role: str | None) -> bool:
    """判断是否可管理知识库成员。"""
    if tenant_role in {TenantRole.OWNER, TenantRole.ADMIN}:
        return True
    if workspace_role in {WorkspaceRole.OWNER, WorkspaceRole.EDITOR}:
        return True
    return kb_role == KBRole.OWNER
