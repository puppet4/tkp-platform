from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from tkp_api.services.rag.vector_retrieval import VectorRetriever


@dataclass
class _FakeResult:
    rows: list[dict]

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict]:
        return self.rows


class _FakeConn:
    def __init__(self, row_batches: list[list[dict]]) -> None:
        self._row_batches = list(row_batches)
        self.calls: list[dict] = []
        self.stmts: list[str] = []

    def execute(self, _stmt, params: dict) -> _FakeResult:  # noqa: ANN001
        self.stmts.append(str(_stmt))
        self.calls.append(params)
        rows = self._row_batches.pop(0) if self._row_batches else []
        return _FakeResult(rows)


class _FakeEmbeddingService:
    def embed_text(self, _query: str) -> list[float]:
        return [0.11, 0.22, 0.33]


def test_vector_retriever_retries_with_relaxed_threshold_when_no_hits():
    tenant_id = uuid4()
    kb_id = uuid4()
    chunk_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()

    conn = _FakeConn(
        row_batches=[
            [],
            [
                {
                    "chunk_id": chunk_id,
                    "document_id": document_id,
                    "document_version_id": version_id,
                    "kb_id": kb_id,
                    "chunk_no": 1,
                    "content": "退款请先提交工单",
                    "metadata": {"lang": "zh"},
                    "embedding_model": "text-embedding-3-small",
                    "parent_chunk_id": None,
                    "document_title": "退款手册",
                    "kb_name": "帮助中心",
                    "similarity": 0.32,
                }
            ],
        ]
    )
    retriever = VectorRetriever(embedding_service=_FakeEmbeddingService(), top_k=5, similarity_threshold=0.7)

    hits = retriever.retrieve(conn, query="退款流程", tenant_id=tenant_id, kb_ids=[kb_id])

    assert len(hits) == 1
    assert hits[0]["chunk_id"] == str(chunk_id)
    assert len(conn.calls) == 2
    assert conn.calls[0]["similarity_threshold"] == 0.7
    assert conn.calls[1]["similarity_threshold"] == 0.0


def test_vector_retriever_does_not_retry_when_threshold_already_zero():
    conn = _FakeConn(row_batches=[[]])
    retriever = VectorRetriever(embedding_service=_FakeEmbeddingService(), top_k=5, similarity_threshold=0.0)

    hits = retriever.retrieve(conn, query="test", tenant_id=uuid4(), kb_ids=None)

    assert hits == []
    assert len(conn.calls) == 1
    assert conn.calls[0]["similarity_threshold"] == 0.0


def test_vector_retriever_queries_chunk_embeddings_table():
    conn = _FakeConn(row_batches=[[]])
    retriever = VectorRetriever(embedding_service=_FakeEmbeddingService(), top_k=3, similarity_threshold=0.5)

    retriever.retrieve(conn, query="退款流程", tenant_id=uuid4(), kb_ids=None)

    assert conn.stmts, "expected at least one SQL statement"
    sql_text = conn.stmts[0]
    assert "FROM document_chunks dc" in sql_text
    assert "JOIN chunk_embeddings e ON e.chunk_id = dc.id" in sql_text
    assert "e.vector" in sql_text
