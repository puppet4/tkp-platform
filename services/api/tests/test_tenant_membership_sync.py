from tkp_api.models.enums import TenantRole, WorkspaceRole
from tkp_api.services.membership_sync import normalize_email, workspace_role_from_tenant_role


def test_normalize_email():
    assert normalize_email("  Alice@Example.COM ") == "alice@example.com"


def test_workspace_role_from_tenant_role():
    assert workspace_role_from_tenant_role(TenantRole.OWNER) == WorkspaceRole.OWNER
    assert workspace_role_from_tenant_role(TenantRole.ADMIN) == WorkspaceRole.EDITOR
    assert workspace_role_from_tenant_role(TenantRole.MEMBER) == WorkspaceRole.VIEWER
    assert workspace_role_from_tenant_role(TenantRole.VIEWER) == WorkspaceRole.VIEWER
