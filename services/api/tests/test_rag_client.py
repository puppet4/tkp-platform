from urllib import error as urlerror

import pytest
from fastapi import HTTPException

from tkp_api.services.rag_client import post_rag_json, reset_rag_circuit_breaker


class _Resp:
    def __init__(self, payload: str) -> None:
        self._payload = payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


def test_post_rag_json_forwards_internal_token(monkeypatch):
    captured = {"token": None}

    def fake_urlopen(request_obj, timeout=None, **_kwargs):  # noqa: ANN001
        header_items = {k.lower(): v for k, v in request_obj.header_items()}
        captured["token"] = header_items.get("x-internal-token")
        return _Resp('{"ok": true}')

    monkeypatch.setattr("tkp_api.services.rag_client.urlrequest.urlopen", fake_urlopen)
    reset_rag_circuit_breaker()
    data = post_rag_json(
        "http://rag.local",
        "/internal/test",
        payload={"hello": "world"},
        timeout_seconds=0.1,
        internal_token="internal-secret",
        max_retries=0,
        retry_backoff_seconds=0.0,
        circuit_fail_threshold=2,
        circuit_open_seconds=30,
    )
    assert data == {"ok": True}
    assert captured["token"] == "internal-secret"


def test_post_rag_json_opens_circuit_after_failures(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(_request_obj, timeout=None, **_kwargs):  # noqa: ANN001
        calls["count"] += 1
        raise urlerror.URLError("down")

    monkeypatch.setattr("tkp_api.services.rag_client.urlrequest.urlopen", fake_urlopen)
    reset_rag_circuit_breaker()

    with pytest.raises(HTTPException) as first:
        post_rag_json(
            "http://rag.local",
            "/internal/test",
            payload={"hello": "world"},
            timeout_seconds=0.1,
            internal_token=None,
            max_retries=0,
            retry_backoff_seconds=0.0,
            circuit_fail_threshold=1,
            circuit_open_seconds=60,
        )
    assert first.value.status_code == 503

    with pytest.raises(HTTPException) as second:
        post_rag_json(
            "http://rag.local",
            "/internal/test",
            payload={"hello": "world"},
            timeout_seconds=0.1,
            internal_token=None,
            max_retries=0,
            retry_backoff_seconds=0.0,
            circuit_fail_threshold=1,
            circuit_open_seconds=60,
        )
    assert second.value.status_code == 503
    assert isinstance(second.value.detail, dict)
    assert second.value.detail.get("code") == "RAG_CIRCUIT_OPEN"
    assert calls["count"] == 1
