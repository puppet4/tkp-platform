"""RAG 服务的向量检索模块。

实现基于 pgvector 的语义检索。
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger("tkp_api.rag.vector_retrieval")


class VectorRetriever:
    """向量检索器。"""

    def __init__(
        self,
        *,
        embedding_service,
        top_k: int = 5,
        similarity_threshold: float = 0.7,
    ):
        """初始化检索器。

        Args:
            embedding_service: 嵌入服务实例
            top_k: 返回的最大结果数
            similarity_threshold: 相似度阈值（0-1）
        """
        self.embedding_service = embedding_service
        self.top_k = top_k
        self.similarity_threshold = similarity_threshold
        logger.info("initialized retriever: top_k=%d, threshold=%.2f", top_k, similarity_threshold)

    def retrieve(
        self,
        conn: Connection,
        *,
        query: str,
        tenant_id: UUID,
        kb_ids: list[UUID] | None = None,
    ) -> list[dict[str, Any]]:
        """执行语义检索。

        Args:
            conn: 数据库连接
            query: 查询文本
            tenant_id: 租户ID
            kb_ids: 知识库ID列表（可选，为空则检索租户下所有知识库）

        Returns:
            检索结果列表，每个结果包含 chunk 内容、相似度、元数据等
        """
        if not query.strip():
            return []

        # 生成查询向量
        try:
            query_embedding = self.embedding_service.embed_text(query)
        except Exception as exc:
            logger.exception("failed to generate query embedding: %s", exc)
            return []

        # 验证向量数据类型安全
        if not isinstance(query_embedding, (list, tuple)):
            logger.error("invalid embedding type: %s", type(query_embedding))
            return []

        if not all(isinstance(v, (int, float)) for v in query_embedding):
            logger.error("embedding contains non-numeric values")
            return []

        # 安全地构建向量字面量（仅包含数字）
        vector_literal = "[" + ",".join(f"{float(v):.6f}" for v in query_embedding) + "]"

        # 构建 SQL 查询
        if kb_ids:
            kb_filter = "AND dc.kb_id = ANY(:kb_ids)"
            params = {
                "tenant_id": str(tenant_id),
                "kb_ids": [str(kb_id) for kb_id in kb_ids],
                "query_vector": vector_literal,
                "top_k": self.top_k,
                "similarity_threshold": self.similarity_threshold,
            }
        else:
            kb_filter = ""
            params = {
                "tenant_id": str(tenant_id),
                "query_vector": vector_literal,
                "top_k": self.top_k,
                "similarity_threshold": self.similarity_threshold,
            }

        stmt = text(
            f"""
            SELECT
                dc.id AS chunk_id,
                dc.document_id,
                dc.document_version_id,
                dc.kb_id,
                dc.chunk_no,
                dc.content,
                dc.metadata,
                dc.embedding_model,
                dc.parent_chunk_id,
                d.title AS document_title,
                kb.name AS kb_name,
                1 - (dc.embedding <=> CAST(:query_vector AS vector)) AS similarity
            FROM document_chunks dc
            JOIN documents d ON d.id = dc.document_id
            JOIN knowledge_bases kb ON kb.id = dc.kb_id
            WHERE dc.tenant_id = :tenant_id
              AND dc.embedding IS NOT NULL
              {kb_filter}
              AND 1 - (dc.embedding <=> CAST(:query_vector AS vector)) >= :similarity_threshold
            ORDER BY dc.embedding <=> CAST(:query_vector AS vector)
            LIMIT :top_k
            """
        )

        rows = conn.execute(stmt, params).mappings().all()

        results = []
        for row in rows:
            results.append(
                {
                    "chunk_id": str(row["chunk_id"]),
                    "document_id": str(row["document_id"]),
                    "document_version_id": str(row["document_version_id"]),
                    "kb_id": str(row["kb_id"]),
                    "kb_name": row["kb_name"],
                    "document_title": row["document_title"],
                    "chunk_no": row["chunk_no"],
                    "content": row["content"],
                    "similarity": float(row["similarity"]),
                    "metadata": row["metadata"],
                    "embedding_model": row["embedding_model"],
                    "parent_chunk_id": str(row["parent_chunk_id"]) if row["parent_chunk_id"] else None,
                }
            )

        logger.info("retrieved %d chunks for query: %s", len(results), query[:50])
        return results


def create_retriever(*, embedding_service, top_k: int = 5, similarity_threshold: float = 0.7) -> VectorRetriever:
    """创建检索器的工厂函数。"""
    return VectorRetriever(
        embedding_service=embedding_service,
        top_k=top_k,
        similarity_threshold=similarity_threshold,
    )