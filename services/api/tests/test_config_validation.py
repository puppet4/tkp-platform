import pytest
from pydantic import ValidationError

from tkp_api.core.config import Settings


def test_api_settings_reject_short_secret_when_jwks_not_set():
    with pytest.raises(ValidationError):
        Settings(auth_jwt_secret="short-secret", auth_jwks_url=None)


def test_api_settings_reject_minio_without_required_fields():
    with pytest.raises(ValidationError):
        Settings(
            storage_backend="minio",
            storage_endpoint=None,
            storage_access_key=None,
            storage_secret_key=None,
        )


def test_api_settings_reject_invalid_rag_base_url():
    with pytest.raises(ValidationError):
        Settings(rag_base_url="rag-service:8010")


def test_api_settings_accept_valid_minio_and_rag_config():
    cfg = Settings(
        auth_jwt_secret="local-dev-secret-key-at-least-32-bytes",
        storage_backend="minio",
        storage_endpoint="127.0.0.1:9000",
        storage_access_key="minioadmin",
        storage_secret_key="minioadmin",
        rag_base_url="http://127.0.0.1:8010",
        internal_service_token="internal-token-123",
    )
    assert cfg.storage_backend == "minio"
    assert cfg.rag_base_url == "http://127.0.0.1:8010"


def test_api_settings_reject_empty_agent_allowed_tools():
    with pytest.raises(ValidationError):
        Settings(agent_allowed_tools="  ,   ")


def test_api_settings_accept_standard_openai_env_names(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-standard-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")

    cfg = Settings()

    assert cfg.openai_api_key.get_secret_value() == "sk-standard-key"
    assert cfg.openai_api_base == "https://api.openai.com/v1"
    assert cfg.openai_chat_model == "gpt-4.1-mini"
    assert cfg.openai_embedding_model == "text-embedding-3-large"
