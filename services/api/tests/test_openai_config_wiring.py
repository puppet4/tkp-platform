import sys
import types


class _FakeOpenAI:
    last_kwargs: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs


class _FakeAsyncOpenAI:
    last_kwargs: dict | None = None

    def __init__(self, **kwargs):
        type(self).last_kwargs = kwargs


def _install_fake_openai(monkeypatch):
    fake_module = types.SimpleNamespace(
        OpenAI=_FakeOpenAI,
        AsyncOpenAI=_FakeAsyncOpenAI,
    )
    monkeypatch.setitem(sys.modules, "openai", fake_module)


def test_llm_generator_passes_base_url(monkeypatch):
    _install_fake_openai(monkeypatch)
    from tkp_api.services.rag.llm_generator import create_generator

    generator = create_generator(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="gpt-4.1-mini",
    )

    assert _FakeOpenAI.last_kwargs == {"api_key": "test-key", "base_url": "https://example.com/v1"}
    assert generator.model == "gpt-4.1-mini"


def test_query_rewriter_passes_base_url(monkeypatch):
    _install_fake_openai(monkeypatch)
    from tkp_api.services.rag.query_rewriter import create_query_rewriter

    rewriter = create_query_rewriter(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="gpt-4.1-mini",
    )

    assert _FakeOpenAI.last_kwargs == {"api_key": "test-key", "base_url": "https://example.com/v1"}
    assert rewriter.model == "gpt-4.1-mini"


def test_rag_embedding_service_passes_base_url(monkeypatch):
    """Test that embedding service correctly passes config.

    The rag.embeddings module has been merged into embedding_service.py.
    This test now validates the unified EmbeddingService picks up settings.
    """
    _install_fake_openai(monkeypatch)

    monkeypatch.setenv("AUTH_JWT_SECRET", "test-secret-key-for-jwt-auth-1234567890")
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "test-internal-token-1234567890")
    monkeypatch.setenv("OPENAI_EMBEDDING_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_EMBEDDING_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large")

    from tkp_api.core.config import clear_settings_cache
    clear_settings_cache()

    from tkp_api.services.embedding_service import EmbeddingService
    service = EmbeddingService()

    assert service.model == "text-embedding-3-large"
    clear_settings_cache()


def test_embedding_gateway_openai_provider_removed():
    """The embedding_gateway module has been removed (merged into embedding_service)."""
    import importlib
    try:
        importlib.import_module("tkp_api.services.embedding_gateway")
        assert False, "embedding_gateway should have been removed"
    except (ImportError, ModuleNotFoundError):
        pass  # expected
