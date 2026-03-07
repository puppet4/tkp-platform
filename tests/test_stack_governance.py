from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
TEST_ENV_UP = REPO_ROOT / "scripts" / "test_env_up.sh"
TEST_ENV_RESET = REPO_ROOT / "scripts" / "test_env_reset_db.sh"
SQL_INIT = REPO_ROOT / "sql" / "init_all.sql"


def test_docker_compose_exists_and_contains_core_services():
    assert COMPOSE_FILE.exists(), "missing docker-compose.yml"
    content = COMPOSE_FILE.read_text(encoding="utf-8")
    for service_name in ("postgres", "redis", "api", "worker"):
        assert f"{service_name}:" in content


def test_test_env_scripts_exist_and_apply_sql_init():
    for script in (TEST_ENV_UP, TEST_ENV_RESET):
        assert script.exists(), f"missing {script.name}"
        content = script.read_text(encoding="utf-8")
        assert "sql/init_all.sql" in content


def test_sql_init_file_exists_for_local_bootstrap():
    assert SQL_INIT.exists(), "missing sql/init_all.sql"
