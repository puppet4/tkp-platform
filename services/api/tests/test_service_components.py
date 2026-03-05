from urllib import error as urlerror
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from tkp_api.core.config import get_settings
from tkp_api.models.enums import DocumentStatus, SourceType
from tkp_api.models.knowledge import Document, DocumentChunk
from tkp_api.services import rag_client
from tkp_api.services import storage as storage_service
from tkp_api.services.agent_planner import normalize_agent_tool_policy
from tkp_api.services.rag_client import post_rag_json, reset_rag_circuit_breaker
from tkp_api.services.retrieval_local import search_chunks


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type_, _compiler, **_kwargs):
    return "JSON"


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(_type_, _compiler, **_kwargs):
    return "BLOB"


class _Resp:
    def __init__(self, payload: str) -> None:
        self._payload = payload.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._payload


class _FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def put_object(self, bucket_name: str, object_name: str, data, length: int, content_type: str):
        self.objects[(bucket_name, object_name)] = data.read(length)


def test_persist_upload_local_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("KD_STORAGE_BACKEND", "local")
    monkeypatch.setenv("KD_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("KD_STORAGE_KEY_PREFIX", "unit-test")
    get_settings.cache_clear()

    key = storage_service.persist_upload(
        tenant_id=uuid4(),
        kb_id=uuid4(),
        document_id=uuid4(),
        version=1,
        filename="../../hello.txt",
        content=b"hello-local",
    )

    assert key.startswith("unit-test/")
    assert (tmp_path / key).read_bytes() == b"hello-local"
    get_settings.cache_clear()


def test_persist_upload_minio_backend(tmp_path, monkeypatch):
    fake_client = _FakeMinio()

    monkeypatch.setenv("KD_STORAGE_BACKEND", "minio")
    monkeypatch.setenv("KD_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("KD_STORAGE_BUCKET", "tkp-unit")
    monkeypatch.setenv("KD_STORAGE_KEY_PREFIX", "ingestion")
    get_settings.cache_clear()

    monkeypatch.setattr(storage_service, "_build_minio_client", lambda _settings: fake_client)

    key = storage_service.persist_upload(
        tenant_id=uuid4(),
        kb_id=uuid4(),
        document_id=uuid4(),
        version=2,
        filename="doc.md",
        content=b"hello-minio",
    )

    assert key.startswith("ingestion/")
    assert fake_client.objects[("tkp-unit", key)] == b"hello-minio"
    get_settings.cache_clear()


def test_search_chunks_supports_metadata_filters_and_citations():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Document.__table__.create(engine)
    DocumentChunk.__table__.create(engine)
    db_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)

    tenant_id = uuid4()
    kb_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()

    db = db_factory()
    try:
        db.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                kb_id=kb_id,
                title="doc",
                source_type=SourceType.UPLOAD,
                source_uri="doc.txt",
                current_version=1,
                status=DocumentStatus.READY,
                metadata_={},
                created_by=None,
            )
        )
        db.add_all(
            [
                DocumentChunk(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    kb_id=kb_id,
                    document_id=document_id,
                    document_version_id=version_id,
                    chunk_no=1,
                    parent_chunk_id=None,
                    title_path="手册/退款",
                    content="退款流程需要先提交工单。",
                    token_count=12,
                    metadata_={"lang": "zh", "source": "policy"},
                ),
                DocumentChunk(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    kb_id=kb_id,
                    document_id=document_id,
                    document_version_id=version_id,
                    chunk_no=2,
                    parent_chunk_id=None,
                    title_path="manual/refund",
                    content="Refund process starts with a ticket.",
                    token_count=8,
                    metadata_={"lang": "en", "source": "policy"},
                ),
            ]
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
    finally:
        db.close()

    assert len(hits) == 1
    hit = hits[0]
    assert hit["chunk_no"] == 1
    assert hit["metadata"]["lang"] == "zh"
    assert hit["citation"]["chunk_no"] == 1
    assert hit["citation"]["title_path"] == "手册/退款"
    assert hit["citation"]["chunk_id"] == hit["chunk_id"]
    assert isinstance(hit.get("reason"), str) and hit["reason"]
    assert isinstance(hit.get("matched_terms"), list)
    assert isinstance(hit.get("score_breakdown"), dict)
    assert hit["score_breakdown"]["final_score"] == hit["score"]


def test_search_chunks_supports_strategy_and_min_score():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Document.__table__.create(engine)
    DocumentChunk.__table__.create(engine)
    db_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)

    tenant_id = uuid4()
    kb_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    version_id = uuid4()

    db = db_factory()
    try:
        db.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                kb_id=kb_id,
                title="doc",
                source_type=SourceType.UPLOAD,
                source_uri="doc.txt",
                current_version=1,
                status=DocumentStatus.READY,
                metadata_={},
                created_by=None,
            )
        )
        db.add_all(
            [
                DocumentChunk(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    kb_id=kb_id,
                    document_id=document_id,
                    document_version_id=version_id,
                    chunk_no=1,
                    parent_chunk_id=None,
                    title_path="指南/退款",
                    content="退款流程需要提交工单。",
                    token_count=12,
                    metadata_={"lang": "zh"},
                ),
                DocumentChunk(
                    id=uuid4(),
                    tenant_id=tenant_id,
                    workspace_id=workspace_id,
                    kb_id=kb_id,
                    document_id=document_id,
                    document_version_id=version_id,
                    chunk_no=2,
                    parent_chunk_id=None,
                    title_path="指南/其他",
                    content="其他流程信息。",
                    token_count=8,
                    metadata_={"lang": "zh"},
                ),
            ]
        )
        db.commit()

        hits = search_chunks(
            db,
            tenant_id=tenant_id,
            kb_ids=[kb_id],
            query="退款流程",
            top_k=5,
            filters={},
            with_citations=True,
            retrieval_strategy="keyword",
            min_score=800,
        )
    finally:
        db.close()

    assert len(hits) == 1
    assert hits[0]["match_type"] in {"keyword", "hybrid"}
    assert hits[0]["score"] >= 800
    assert isinstance(hits[0].get("reason"), str) and hits[0]["reason"]
    assert isinstance(hits[0].get("matched_terms"), list)
    assert isinstance(hits[0].get("score_breakdown"), dict)
    assert hits[0]["score_breakdown"]["final_score"] == hits[0]["score"]


def test_normalize_agent_tool_policy_rejects_forbidden_tools():
    with pytest.raises(HTTPException) as exc_info:
        normalize_agent_tool_policy({"allow": ["retrieval", "web_search"]}, allowed_tools=["retrieval"])

    exc = exc_info.value
    assert exc.status_code == 422
    assert exc.detail["code"] == "AGENT_TOOL_NOT_ALLOWED"


def test_normalize_agent_tool_policy_defaults_to_allowlist():
    normalized = normalize_agent_tool_policy({}, allowed_tools=["retrieval"])
    assert normalized["allow"] == ["retrieval"]
    assert normalized["validated"] is True


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


def test_post_rag_json_circuit_recovers_after_open_window(monkeypatch):
    calls = {"count": 0}
    now = {"value": 1000.0}
    is_down = {"value": True}

    def fake_time():
        return now["value"]

    def fake_urlopen(_request_obj, timeout=None, **_kwargs):  # noqa: ANN001
        calls["count"] += 1
        if is_down["value"]:
            raise urlerror.URLError("down")
        return _Resp('{"ok": true}')

    monkeypatch.setattr(rag_client.time, "time", fake_time)
    monkeypatch.setattr("tkp_api.services.rag_client.urlrequest.urlopen", fake_urlopen)
    reset_rag_circuit_breaker()

    with pytest.raises(HTTPException):
        post_rag_json(
            "http://rag.local",
            "/internal/test",
            payload={"hello": "world"},
            timeout_seconds=0.1,
            internal_token=None,
            max_retries=0,
            retry_backoff_seconds=0.0,
            circuit_fail_threshold=1,
            circuit_open_seconds=5,
        )

    with pytest.raises(HTTPException) as open_err:
        post_rag_json(
            "http://rag.local",
            "/internal/test",
            payload={"hello": "world"},
            timeout_seconds=0.1,
            internal_token=None,
            max_retries=0,
            retry_backoff_seconds=0.0,
            circuit_fail_threshold=1,
            circuit_open_seconds=5,
        )
    assert open_err.value.detail["code"] == "RAG_CIRCUIT_OPEN"

    now["value"] = 1006.0
    is_down["value"] = False
    data = post_rag_json(
        "http://rag.local",
        "/internal/test",
        payload={"hello": "world"},
        timeout_seconds=0.1,
        internal_token=None,
        max_retries=0,
        retry_backoff_seconds=0.0,
        circuit_fail_threshold=1,
        circuit_open_seconds=5,
    )
    assert data == {"ok": True}
    assert calls["count"] == 2
