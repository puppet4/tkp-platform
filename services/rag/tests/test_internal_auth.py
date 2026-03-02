from fastapi.testclient import TestClient

from tkp_rag.app import app
from tkp_rag.core.config import get_settings


def test_internal_endpoint_requires_token_when_configured(monkeypatch):
    monkeypatch.setenv("KD_INTERNAL_SERVICE_TOKEN", "internal-secret")
    get_settings.cache_clear()

    with TestClient(app) as client:
        resp = client.post(
            "/internal/agent/plan",
            json={
                "tenant_id": "11111111-1111-1111-1111-111111111111",
                "user_id": "22222222-2222-2222-2222-222222222222",
                "task": "plan",
                "kb_ids": [],
                "conversation_id": None,
                "tool_policy": {},
            },
        )
    assert resp.status_code == 401

