import pytest
from pydantic import ValidationError

from tkp_worker.config import Settings


def test_worker_settings_reject_minio_without_required_fields():
    with pytest.raises(ValidationError):
        Settings(storage_backend="minio", storage_endpoint=None, storage_access_key=None, storage_secret_key=None)


def test_worker_settings_accept_valid_minio_config():
    cfg = Settings(
        storage_backend="minio",
        storage_endpoint="127.0.0.1:9000",
        storage_access_key="minioadmin",
        storage_secret_key="minioadmin",
        openai_embedding_api_key="test-key",
    )
    assert cfg.storage_backend == "minio"


def test_worker_settings_support_split_embedding_openai_env_names(monkeypatch):
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "sk-embed-key")
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://embed.example.com/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")

    cfg = Settings()

    assert cfg.resolved_openai_embedding_api_key == "sk-embed-key"
    assert cfg.resolved_openai_embedding_base_url == "https://embed.example.com/v1"
    assert cfg.openai_embedding_model == "text-embedding-3-large"


def test_worker_settings_reject_legacy_shared_openai_env_without_embedding_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-shared-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://shared.example.com/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "")

    with pytest.raises(ValidationError):
        Settings(openai_embedding_api_key="")
