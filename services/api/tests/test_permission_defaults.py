from tkp_api.models.enums import TenantRole
from tkp_api.services.permissions import DEFAULT_TENANT_ROLE_ACTIONS, PermissionAction


def test_default_role_actions_include_retrieval_chat_agent():
    required_actions = {
        PermissionAction.RETRIEVAL_QUERY.value,
        PermissionAction.CHAT_COMPLETION.value,
        PermissionAction.AGENT_RUN_CREATE.value,
        PermissionAction.AGENT_RUN_READ.value,
        PermissionAction.AGENT_RUN_CANCEL.value,
    }

    for role in (TenantRole.OWNER, TenantRole.ADMIN, TenantRole.MEMBER, TenantRole.VIEWER):
        role_actions = DEFAULT_TENANT_ROLE_ACTIONS[role]
        assert required_actions.issubset(role_actions)
