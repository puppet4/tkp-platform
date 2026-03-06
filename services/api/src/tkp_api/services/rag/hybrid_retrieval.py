"""混合检索服务模块。

结合向量检索、全文检索和 BM25，实现多策略融合检索。
"""

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

logger = logging.getLogger("tkp_api.rag.hybrid_retrieval")


class HybridRetriever:
    """混合检索器。"""

    def __init__(
        self,
        *,
        vector_retriever,
        elasticsearch_client=None,
        reranker=None,
        query_rewriter=None,
        vector_weight: float = 0.5,
        fulltext_weight: float = 0.5,
    ):
        """初始化混合检索器。

        Args:
            vector_retriever: 向量检索器
            elasticsearch_client: Elasticsearch 客户端（可选）
            reranker: 重排序器（可选）
            query_rewriter: 查询改写器（可选）
            vector_weight: 向量检索权重
            fulltext_weight: 全文检索权重
        """
        self.vector_retriever = vector_retriever
        self.elasticsearch_client = elasticsearch_client
        self.reranker = reranker
        self.query_rewriter = query_rewriter
        self.vector_weight = vector_weight
        self.fulltext_weight = fulltext_weight

        logger.info(
            "initialized hybrid retriever: vector_weight=%.2f, fulltext_weight=%.2f",
            vector_weight,
            fulltext_weight,
        )

    def retrieve(
        self,
        db: Session,
        *,
        query: str,
        tenant_id: UUID,
        kb_ids: list[UUID] | None = None,
        top_k: int = 5,
        strategy: str = "hybrid",
        enable_rerank: bool = True,
        enable_query_rewrite: bool = False,
    ) -> dict[str, Any]:
        """执行混合检索。

        Args:
            db: 数据库会话
            query: 查询文本
            tenant_id: 租户 ID
            kb_ids: 知识库 ID 列表
            top_k: 返回结果数
            strategy: 检索策略（vector/fulltext/hybrid）
            enable_rerank: 是否启用重排序
            enable_query_rewrite: 是否启用查询改写

        Returns:
            包含 hits、strategy、rerank_applied、query_rewrite 的字典
        """
        if not query.strip():
            return {
                "hits": [],
                "strategy": strategy,
                "rerank_applied": False,
                "query_rewrite": {
                    "original_query": query,
                    "rewritten_query": query,
                    "rewrite_applied": False,
                },
            }

        # 查询改写
        query_rewrite_info = {"original_query": query, "rewritten_query": query, "rewrite_applied": False}
        search_query = query

        if enable_query_rewrite and self.query_rewriter:
            try:
                rewrite_result = self.query_rewriter.rewrite(query)
                if rewrite_result["rewrite_applied"]:
                    # 使用第一个改写查询
                    search_query = rewrite_result["rewritten_queries"][0]
                    query_rewrite_info = {
                        "original_query": query,
                        "rewritten_query": search_query,
                        "rewrite_applied": True,
                        "all_queries": rewrite_result["rewritten_queries"],
                    }
                    logger.info("query rewritten: '%s' -> '%s'", query, search_query)
            except Exception as exc:
                logger.warning("query rewrite failed, using original: %s", exc)

        # 根据策略执行检索
        if strategy == "vector":
            hits = self._vector_search(db, search_query, tenant_id, kb_ids, top_k * 2)
        elif strategy == "fulltext":
            hits = self._fulltext_search(search_query, tenant_id, kb_ids, top_k * 2)
        elif strategy == "hybrid":
            hits = self._hybrid_search(db, search_query, tenant_id, kb_ids, top_k * 2)
        else:
            logger.warning("unknown strategy '%s', fallback to vector", strategy)
            hits = self._vector_search(db, search_query, tenant_id, kb_ids, top_k * 2)

        # 重排序
        rerank_applied = False
        if enable_rerank and self.reranker and len(hits) > 0:
            try:
                hits = self.reranker.rerank(query=query, documents=hits, top_n=top_k)
                rerank_applied = True
                logger.info("rerank applied: %d results", len(hits))
            except Exception as exc:
                logger.warning("rerank failed, using original order: %s", exc)
                hits = hits[:top_k]
        else:
            hits = hits[:top_k]

        return {
            "hits": hits,
            "strategy": strategy,
            "rerank_applied": rerank_applied,
            "query_rewrite": query_rewrite_info,
        }

    def _vector_search(
        self,
        db: Session,
        query: str,
        tenant_id: UUID,
        kb_ids: list[UUID] | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """纯向量检索。"""
        try:
            # Reuse the session-managed connection and do not close it here.
            # Closing it early can break later session commit/flush lifecycle.
            conn = db.connection()
            results = self.vector_retriever.retrieve(
                conn,
                query=query,
                tenant_id=tenant_id,
                kb_ids=kb_ids,
            )

            # 格式化结果
            hits = []
            for result in results[:top_k]:
                hits.append(
                    {
                        "chunk_id": result["chunk_id"],
                        "document_id": result["document_id"],
                        "document_version_id": result["document_version_id"],
                        "kb_id": result["kb_id"],
                        "kb_name": result["kb_name"],
                        "document_title": result["document_title"],
                        "chunk_no": result["chunk_no"],
                        "content": result["content"],
                        "score": result["similarity"],
                        "similarity": result["similarity"],
                        "metadata": result["metadata"],
                        "retrieval_method": "vector",
                    }
                )

            logger.info("vector search: %d results", len(hits))
            return hits
        except Exception as exc:
            logger.exception("vector search failed: %s", exc)
            return []

    def _fulltext_search(
        self,
        query: str,
        tenant_id: UUID,
        kb_ids: list[UUID] | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """纯全文检索。"""
        if not self.elasticsearch_client:
            logger.warning("elasticsearch not configured, fallback to empty results")
            return []

        try:
            results = self.elasticsearch_client.full_text_search(
                index_name="document_chunks",
                query_text=query,
                tenant_id=tenant_id,
                kb_ids=kb_ids,
                size=top_k,
            )

            # 格式化结果
            hits = []
            for result in results:
                hits.append(
                    {
                        "chunk_id": result["id"],
                        "document_id": result.get("document_id"),
                        "document_version_id": result.get("document_version_id"),
                        "kb_id": result.get("kb_id"),
                        "kb_name": result.get("kb_name", ""),
                        "document_title": result.get("document_title", ""),
                        "chunk_no": result.get("chunk_no", 0),
                        "content": result.get("content", ""),
                        "score": result["score"],
                        "similarity": result["score"] / 100.0,  # 归一化到 0-1
                        "metadata": result.get("metadata", {}),
                        "retrieval_method": "fulltext",
                    }
                )

            logger.info("fulltext search: %d results", len(hits))
            return hits
        except Exception as exc:
            logger.exception("fulltext search failed: %s", exc)
            return []

    def _hybrid_search(
        self,
        db: Session,
        query: str,
        tenant_id: UUID,
        kb_ids: list[UUID] | None,
        top_k: int,
    ) -> list[dict[str, Any]]:
        """混合检索：向量 + 全文。"""
        # 分别执行向量和全文检索
        vector_results = self._vector_search(db, query, tenant_id, kb_ids, top_k)
        fulltext_results = self._fulltext_search(query, tenant_id, kb_ids, top_k)

        # 合并结果（使用 RRF - Reciprocal Rank Fusion）
        merged = self._merge_results_rrf(vector_results, fulltext_results, top_k)

        logger.info(
            "hybrid search: vector=%d, fulltext=%d, merged=%d",
            len(vector_results),
            len(fulltext_results),
            len(merged),
        )
        return merged

    def _merge_results_rrf(
        self,
        vector_results: list[dict[str, Any]],
        fulltext_results: list[dict[str, Any]],
        top_k: int,
        k: int = 60,
    ) -> list[dict[str, Any]]:
        """使用 Reciprocal Rank Fusion 合并结果。

        RRF Score = sum(1 / (k + rank_i))
        """
        # 构建 chunk_id -> result 映射
        all_results = {}

        # 处理向量检索结果
        for rank, result in enumerate(vector_results, start=1):
            chunk_id = result["chunk_id"]
            if chunk_id not in all_results:
                all_results[chunk_id] = result.copy()
                all_results[chunk_id]["rrf_score"] = 0
                all_results[chunk_id]["vector_rank"] = None
                all_results[chunk_id]["fulltext_rank"] = None

            all_results[chunk_id]["rrf_score"] += self.vector_weight / (k + rank)
            all_results[chunk_id]["vector_rank"] = rank

        # 处理全文检索结果
        for rank, result in enumerate(fulltext_results, start=1):
            chunk_id = result["chunk_id"]
            if chunk_id not in all_results:
                all_results[chunk_id] = result.copy()
                all_results[chunk_id]["rrf_score"] = 0
                all_results[chunk_id]["vector_rank"] = None
                all_results[chunk_id]["fulltext_rank"] = None

            all_results[chunk_id]["rrf_score"] += self.fulltext_weight / (k + rank)
            all_results[chunk_id]["fulltext_rank"] = rank

        # 按 RRF 分数排序
        merged = sorted(all_results.values(), key=lambda x: x["rrf_score"], reverse=True)

        # 更新检索方法标记
        for result in merged:
            if result["vector_rank"] and result["fulltext_rank"]:
                result["retrieval_method"] = "hybrid"
            result["score"] = result["rrf_score"]

        return merged[:top_k]


def create_hybrid_retriever(
    *,
    vector_retriever,
    elasticsearch_client=None,
    reranker=None,
    query_rewriter=None,
    vector_weight: float = 0.5,
    fulltext_weight: float = 0.5,
) -> HybridRetriever:
    """创建混合检索器的工厂函数。"""
    return HybridRetriever(
        vector_retriever=vector_retriever,
        elasticsearch_client=elasticsearch_client,
        reranker=reranker,
        query_rewriter=query_rewriter,
        vector_weight=vector_weight,
        fulltext_weight=fulltext_weight,
    )
