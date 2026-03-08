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
    _install_fake_openai(monkeypatch)
    from tkp_api.services.rag.embeddings import create_embedding_service

    service = create_embedding_service(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="text-embedding-3-large",
    )

    assert _FakeOpenAI.last_kwargs == {"api_key": "test-key", "base_url": "https://example.com/v1"}
    assert _FakeAsyncOpenAI.last_kwargs == {"api_key": "test-key", "base_url": "https://example.com/v1"}
    assert service.model == "text-embedding-3-large"


def test_embedding_gateway_openai_provider_passes_base_url(monkeypatch):
    _install_fake_openai(monkeypatch)
    from tkp_api.services.embedding_gateway import OpenAIEmbeddingProvider

    provider = OpenAIEmbeddingProvider(
        api_key="test-key",
        base_url="https://example.com/v1",
        model="text-embedding-3-large",
    )

    assert _FakeOpenAI.last_kwargs == {"api_key": "test-key", "base_url": "https://example.com/v1"}
    assert provider.model == "text-embedding-3-large"
