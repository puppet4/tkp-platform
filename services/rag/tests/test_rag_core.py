from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from tkp_rag.app import app
from tkp_rag.core.config import get_settings
from tkp_rag.services.agent import build_plan
from tkp_rag.services.retrieval import generate_answer, search_chunks


def test_smoke() -> None:
    assert True


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


def _init_sqlite_schema(db: Session) -> None:
    db.execute(
        text(
            """
            CREATE TABLE documents (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                kb_id TEXT NOT NULL,
                status TEXT NOT NULL
            )
            """
        )
    )
    db.execute(
        text(
            """
            CREATE TABLE document_chunks (
                id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL,
                workspace_id TEXT NOT NULL,
                kb_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                document_version_id TEXT NOT NULL,
                chunk_no INTEGER NOT NULL,
                title_path TEXT,
                content TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
    )
    db.commit()


def test_search_chunks_supports_metadata_filters_and_citations():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    db = Session(engine, autoflush=False, autocommit=False)
    tenant_id = uuid4()
    kb_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()
    try:
        _init_sqlite_schema(db)
        db.execute(
            text(
                """
                INSERT INTO documents (id, tenant_id, workspace_id, kb_id, status)
                VALUES (:id, :tenant_id, :workspace_id, :kb_id, :status)
                """
            ),
            {
                "id": str(document_id),
                "tenant_id": str(tenant_id),
                "workspace_id": str(workspace_id),
                "kb_id": str(kb_id),
                "status": "ready",
            },
        )
        db.execute(
            text(
                """
                INSERT INTO document_chunks (
                    id, tenant_id, workspace_id, kb_id, document_id, document_version_id,
                    chunk_no, title_path, content, metadata
                ) VALUES
                    (:id1, :tenant_id, :workspace_id, :kb_id, :document_id, :version_id, 1, :title1, :content1, :meta1),
                    (:id2, :tenant_id, :workspace_id, :kb_id, :document_id, :version_id, 2, :title2, :content2, :meta2)
                """
            ),
            {
                "id1": str(uuid4()),
                "id2": str(uuid4()),
                "tenant_id": str(tenant_id),
                "workspace_id": str(workspace_id),
                "kb_id": str(kb_id),
                "document_id": str(document_id),
                "version_id": str(version_id),
                "title1": "手册/退款",
                "title2": "manual/refund",
                "content1": "退款流程需要先提交工单。",
                "content2": "Refund process starts with a ticket.",
                "meta1": '{"lang":"zh","source":"policy"}',
                "meta2": '{"lang":"en","source":"policy"}',
            },
        )
        db.commit()

        hits = search_chunks(
            db,
            tenant_id=tenant_id,
            kb_ids=[kb_id],
            query="退款流程",
            top_k=5,
            filters={"lang": "zh"},
        )
        assert len(hits) == 1
        hit = hits[0]
        assert hit["chunk_no"] == 1
        assert hit["metadata"]["lang"] == "zh"
        assert hit["citation"]["chunk_no"] == 1
        assert hit["citation"]["title_path"] == "手册/退款"

        answer_payload = generate_answer(
            db,
            tenant_id=tenant_id,
            kb_ids=[kb_id],
            question="退款流程是什么？",
            top_k=3,
        )
        assert "answer" in answer_payload and isinstance(answer_payload["answer"], str)
        assert isinstance(answer_payload["citations"], list)
        assert isinstance(answer_payload["usage"], dict)
        assert answer_payload["usage"]["total_tokens"] >= 2
    finally:
        db.close()
