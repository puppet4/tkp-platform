from uuid import uuid4

from tkp_rag.services.agent import build_plan


def test_build_plan_returns_structured_payload():
    payload = build_plan(
        tenant_id=uuid4(),
        user_id=uuid4(),
        task="整理文档",
        kb_ids=[uuid4()],
        conversation_id=None,
        tool_policy={"allow": ["retrieval"]},
    )
    assert payload["status"] == "queued"
    assert isinstance(payload["plan_json"], dict)
    assert payload["plan_json"]["source"] == "rag"
    assert isinstance(payload["plan_json"]["steps"], list)
    assert payload["plan_json"]["steps"][0]["name"] == "retrieve"
    assert payload["tool_calls"] == []

