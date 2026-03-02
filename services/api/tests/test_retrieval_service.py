from uuid import uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from tkp_api.models.enums import DocumentStatus, SourceType
from tkp_api.models.knowledge import Document, DocumentChunk
from tkp_api.services.retrieval import search_chunks


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type_, _compiler, **_kwargs):
    return "JSON"


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(_type_, _compiler, **_kwargs):
    return "BLOB"


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
