"""权限检查工具函数。"""

from tkp_api.dependencies import RequestContext
from tkp_api.models.enums import TenantRole


def is_admin_role(ctx: RequestContext) -> bool:
    """检查用户是否为管理员角色（Owner或Admin）。

    Args:
        ctx: 请求上下文

    Returns:
        True 如果用户是 Owner 或 Admin，否则 False
    """
    return ctx.tenant_role in {
        TenantRole.OWNER,
        TenantRole.ADMIN,
        TenantRole.OWNER.value,
        TenantRole.ADMIN.value,
    }


def is_owner_role(ctx: RequestContext) -> bool:
    """检查用户是否为所有者角色。

    Args:
        ctx: 请求上下文

    Returns:
        True 如果用户是 Owner，否则 False
    """
    return ctx.tenant_role in {TenantRole.OWNER, TenantRole.OWNER.value}
