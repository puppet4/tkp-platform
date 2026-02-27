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
    "button.member.add",
    "button.member.remove",
    "feature.auth.permissions",
]

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


def _forbidden() -> HTTPException:
    """统一 403 异常。"""
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden")


def permission_catalog() -> list[str]:
    """返回权限点目录（含 API 动作与推荐 UI 权限码）。"""
    api_codes = sorted(action.value for action in PermissionAction)
    return sorted(set(api_codes + DEFAULT_UI_PERMISSIONS))


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


def list_tenant_actions(db: Session, *, tenant_id: UUID, tenant_role: str) -> list[str]:
    """返回当前租户角色可执行权限点。

    规则：
    1. 角色有租户级配置时，使用数据库配置。
    2. 未配置时，回退到内置默认映射。
    """
    configured = _load_role_permissions(db, tenant_id=tenant_id, role=tenant_role)
    if configured:
        return sorted({_normalize_permission_code(code) for code in configured if code.strip()})
    return sorted(DEFAULT_TENANT_ROLE_ACTIONS.get(tenant_role, set()))


def list_tenant_role_permission_matrix(db: Session, *, tenant_id: UUID) -> dict[str, list[str]]:
    """返回当前租户所有角色权限映射。"""
    matrix: dict[str, list[str]] = {}
    for role in (TenantRole.OWNER, TenantRole.ADMIN, TenantRole.MEMBER, TenantRole.VIEWER):
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
    normalized = sorted({_normalize_permission_code(code) for code in permission_codes if code.strip()})
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
