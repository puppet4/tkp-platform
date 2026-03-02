import re
from pathlib import Path

from tkp_api.models.enums import TenantRole
from tkp_api.services.permissions import DEFAULT_TENANT_ROLE_ACTIONS, PermissionAction, permission_catalog


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


def test_sql_permission_seed_covers_runtime_catalog():
    repo_root = Path(__file__).resolve().parents[3]
    sql_files = [
        repo_root / "infra/sql/040_seed_permissions.sql",
        *sorted((repo_root / "infra/sql/migrations").glob("*.sql")),
    ]

    sql_codes: set[str] = set()
    code_pattern = re.compile(r"'((?:api|menu|button|feature)\.[a-z0-9_.]+)'")
    for path in sql_files:
        sql_codes.update(code_pattern.findall(path.read_text(encoding="utf-8")))

    missing = sorted(set(permission_catalog()) - sql_codes)
    assert missing == [], f"permission codes missing in SQL seed/migrations: {missing}"


def test_test_env_scripts_must_apply_sql_migrations():
    repo_root = Path(__file__).resolve().parents[3]
    up_content = (repo_root / "scripts/test_env_up.sh").read_text(encoding="utf-8")
    reset_content = (repo_root / "scripts/test_env_reset_db.sh").read_text(encoding="utf-8")

    assert "infra/sql/migrations" in up_content, "test_env_up.sh must apply incremental migrations"
    assert "infra/sql/migrations" in reset_content, "test_env_reset_db.sh must apply incremental migrations"
