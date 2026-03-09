from types import SimpleNamespace
from uuid import uuid4

from tkp_worker import main as worker_main


class _FakeSelectResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _FakeConn:
    def __init__(self, row):
        self._row = row
        self.executed: list[tuple[str, dict]] = []

    def execute(self, stmt, params=None):
        sql = str(stmt)
        if "SELECT d.tenant_id, d.workspace_id, d.kb_id" in sql:
            return _FakeSelectResult(self._row)
        self.executed.append((sql, params or {}))
        return None


class _FakeEmbeddingService:
    def embed_batch(self, chunks):
        return [[0.1] * 1536 for _ in chunks]

    def count_tokens(self, text):
        return max(1, len(text) // 4)


class _FakeChunker:
    def chunk_text(self, _text):
        return ["chunk-1"]


class _FakeParserRegistry:
    def parse(self, _file_bytes, _filename):
        return "hello world"


def test_process_job_writes_chunk_embeddings(monkeypatch):
    tenant_id = uuid4()
    workspace_id = uuid4()
    kb_id = uuid4()
    document_id = uuid4()
    document_version_id = uuid4()
    job_id = uuid4()

    fake_row = {
        "tenant_id": tenant_id,
        "workspace_id": workspace_id,
        "kb_id": kb_id,
        "document_metadata": {},
        "object_key": "tenant/a/doc.md",
        "filename": "doc.md",
    }
    conn = _FakeConn(fake_row)

    monkeypatch.setattr(worker_main, "_read_object_bytes_from_storage", lambda **_kwargs: b"# test")
    monkeypatch.setattr(worker_main, "default_parser_registry", _FakeParserRegistry())

    settings = SimpleNamespace(
        storage_backend="local",
        storage_root="./.storage",
        storage_bucket="tkp-documents",
        storage_endpoint=None,
        storage_access_key=None,
        storage_secret_key=None,
        storage_secure=False,
        storage_region=None,
        openai_embedding_model="text-embedding-3-large",
    )

    worker_main._process_job_with_real_embeddings(
        conn,
        {
            "id": job_id,
            "document_id": document_id,
            "document_version_id": document_version_id,
        },
        settings=settings,
        embedding_service=_FakeEmbeddingService(),
        chunker=_FakeChunker(),
        worker_id="worker-test",
    )

    all_sql = "\n".join(sql for sql, _ in conn.executed)
    assert "INSERT INTO document_chunks" in all_sql
    assert "INSERT INTO chunk_embeddings" in all_sql
