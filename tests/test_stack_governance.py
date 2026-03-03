from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "infra" / "podman-compose.yml"
STACK_UP = REPO_ROOT / "scripts" / "stack_up.sh"
STACK_DOWN = REPO_ROOT / "scripts" / "stack_down.sh"
STACK_LOGS = REPO_ROOT / "scripts" / "stack_logs.sh"
DEV_ENV = REPO_ROOT / "infra" / "env" / "dev.env"


def test_podman_compose_file_exists_and_contains_full_stack_services():
    assert COMPOSE_FILE.exists(), "missing infra/podman-compose.yml"
    content = COMPOSE_FILE.read_text(encoding="utf-8")
    for service_name in ("postgres", "redis", "minio", "api", "rag", "worker"):
        assert f"{service_name}:" in content


def test_stack_scripts_exist_and_use_podman_compose():
    for script in (STACK_UP, STACK_DOWN, STACK_LOGS):
        assert script.exists(), f"missing {script.name}"
        content = script.read_text(encoding="utf-8")
        assert "podman compose" in content


def test_dev_env_exists_for_stack_layering():
    assert DEV_ENV.exists(), "missing infra/env/dev.env"
    content = DEV_ENV.read_text(encoding="utf-8")
    for key in ("KD_DATABASE_URL=", "KD_REDIS_URL=", "KD_STORAGE_ENDPOINT=", "KD_RAG_BASE_URL="):
        assert key in content
