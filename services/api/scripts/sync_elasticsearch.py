"""Elasticsearch 索引同步脚本。

用于将 PostgreSQL 中的文档切片同步到 Elasticsearch。
"""

import logging
import sys
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from tkp_api.core.config import get_settings
from tkp_api.db.session import get_db
from tkp_api.services.rag.elasticsearch_client import create_elasticsearch_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_chunks_index(es_client, index_name: str) -> bool:
    """创建文档切片索引。"""
    mappings = {
        "properties": {
            "chunk_id": {"type": "keyword"},
            "document_id": {"type": "keyword"},
            "document_version_id": {"type": "keyword"},
            "kb_id": {"type": "keyword"},
            "kb_name": {"type": "text"},
            "tenant_id": {"type": "keyword"},
            "document_title": {"type": "text"},
            "chunk_no": {"type": "integer"},
            "content": {
                "type": "text",
                "analyzer": "standard",
                "fields": {
                    "keyword": {"type": "keyword", "ignore_above": 256},
                },
            },
            "token_count": {"type": "integer"},
            "metadata": {"type": "object", "enabled": False},
            "created_at": {"type": "date"},
        }
    }

    return es_client.create_index(index_name=index_name, mappings=mappings)


def sync_chunks_to_elasticsearch(
    db: Session,
    es_client,
    index_name: str,
    tenant_id: UUID | None = None,
    batch_size: int = 100,
) -> tuple[int, int]:
    """同步文档切片到 Elasticsearch。

    Args:
        db: 数据库会话
        es_client: Elasticsearch 客户端
        index_name: 索引名称
        tenant_id: 租户 ID（可选，为空则同步所有）
        batch_size: 批次大小

    Returns:
        (成功数, 失败数)
    """
    # 构建查询
    query = """
        SELECT
            dc.id as chunk_id,
            dc.document_id,
            dc.document_version_id,
            dv.kb_id,
            kb.name as kb_name,
            kb.tenant_id,
            d.title as document_title,
            dc.chunk_no,
            dc.content,
            dc.token_count,
            dc.metadata,
            dc.created_at
        FROM document_chunks dc
        JOIN document_versions dv ON dc.document_version_id = dv.id
        JOIN documents d ON dv.document_id = d.id
        JOIN knowledge_bases kb ON dv.kb_id = kb.id
        WHERE dc.content IS NOT NULL
    """

    params = {}
    if tenant_id:
        query += " AND kb.tenant_id = :tenant_id"
        params["tenant_id"] = str(tenant_id)

    query += " ORDER BY dc.created_at"

    # 执行查询
    result = db.execute(text(query), params)
    rows = result.fetchall()

    logger.info("found %d chunks to sync", len(rows))

    # 批量索引
    total_success = 0
    total_failed = 0
    batch = []

    for row in rows:
        doc = {
            "_id": str(row.chunk_id),
            "chunk_id": str(row.chunk_id),
            "document_id": str(row.document_id),
            "document_version_id": str(row.document_version_id),
            "kb_id": str(row.kb_id),
            "kb_name": row.kb_name,
            "tenant_id": str(row.tenant_id),
            "document_title": row.document_title,
            "chunk_no": row.chunk_no,
            "content": row.content,
            "token_count": row.token_count,
            "metadata": row.metadata or {},
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        batch.append(doc)

        if len(batch) >= batch_size:
            success, failed = es_client.bulk_index(index_name=index_name, documents=batch)
            total_success += success
            total_failed += failed
            logger.info("synced batch: success=%d, failed=%d", success, failed)
            batch = []

    # 处理剩余的批次
    if batch:
        success, failed = es_client.bulk_index(index_name=index_name, documents=batch)
        total_success += success
        total_failed += failed
        logger.info("synced final batch: success=%d, failed=%d", success, failed)

    logger.info("sync completed: total_success=%d, total_failed=%d", total_success, total_failed)
    return total_success, total_failed


def main():
    """主函数。"""
    settings = get_settings()

    if not settings.elasticsearch_enabled:
        logger.error("Elasticsearch is not enabled in configuration")
        sys.exit(1)

    # 创建 Elasticsearch 客户端
    try:
        es_client = create_elasticsearch_client(
            hosts=settings.elasticsearch_hosts.split(","),
            api_key=settings.elasticsearch_api_key or None,
            username=settings.elasticsearch_username or None,
            password=settings.elasticsearch_password or None,
            verify_certs=settings.elasticsearch_verify_certs,
        )
        logger.info("elasticsearch client initialized")
    except Exception as exc:
        logger.exception("failed to initialize elasticsearch client: %s", exc)
        sys.exit(1)

    # 创建索引
    index_name = settings.elasticsearch_index_name
    if not create_chunks_index(es_client, index_name):
        logger.error("failed to create index: %s", index_name)
        sys.exit(1)

    logger.info("index ready: %s", index_name)

    # 同步数据
    db = next(get_db())
    try:
        success, failed = sync_chunks_to_elasticsearch(
            db=db,
            es_client=es_client,
            index_name=index_name,
            batch_size=100,
        )

        if failed > 0:
            logger.warning("sync completed with errors: success=%d, failed=%d", success, failed)
            sys.exit(1)
        else:
            logger.info("sync completed successfully: %d documents indexed", success)
            sys.exit(0)
    finally:
        db.close()


if __name__ == "__main__":
    main()
