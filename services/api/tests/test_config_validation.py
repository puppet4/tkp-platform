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


def test_api_settings_support_split_openai_chat_and_embedding(monkeypatch):
    monkeypatch.setenv("OPENAI_CHAT_API_KEY", "sk-chat-key")
    monkeypatch.setenv("OPENAI_CHAT_BASE_URL", "https://chat.example.com/v1")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "sk-embed-key")
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://embed.example.com/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")

    cfg = Settings()

    assert cfg.resolved_openai_chat_api_key == "sk-chat-key"
    assert cfg.resolved_openai_chat_base_url == "https://chat.example.com/v1"
    assert cfg.openai_chat_model == "gpt-4.1-mini"
    assert cfg.resolved_openai_embedding_api_key == "sk-embed-key"
    assert cfg.resolved_openai_embedding_base_url == "https://embed.example.com/v1"
    assert cfg.openai_embedding_model == "text-embedding-3-large"


def test_api_settings_chat_model_prefers_chat_specific_env(monkeypatch):
    monkeypatch.setenv("OPENAI_MODEL", "legacy-model-should-be-ignored")
    monkeypatch.setenv("OPENAI_CHAT_MODEL", "gpt-4.1-mini")

    cfg = Settings()

    assert cfg.openai_chat_model == "gpt-4.1-mini"


def test_api_settings_does_not_fallback_to_legacy_shared_openai_env(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-shared-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://shared.example.com/v1")
    monkeypatch.delenv("OPENAI_CHAT_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_CHAT_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setenv("AUTH_JWT_SECRET", "test-secret-at-least-32-bytes-long")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "test-internal-token")

    cfg = Settings(_env_file=None)

    assert cfg.resolved_openai_chat_api_key == ""
    assert cfg.resolved_openai_chat_base_url is None
    assert cfg.resolved_openai_embedding_api_key == ""
    assert cfg.resolved_openai_embedding_base_url is None
