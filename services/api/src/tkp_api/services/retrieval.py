"""RAG 服务封装（使用本地 RAG 模块，支持混合检索）。"""

from __future__ import annotations

import threading
import time
from functools import lru_cache
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from tkp_api.core.config import get_settings
from tkp_api.services.rag import search_chunks_improved, generate_answer_improved


# 线程安全的单例实现
class HybridRetrieverSingleton:
    """线程安全的混合检索器单例。"""

    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls):
        """获取混合检索器单例实例（线程安全）。"""
        if cls._instance is None:
            with cls._lock:
                # 双重检查锁定
                if cls._instance is None:
                    cls._instance = cls._create_retriever()
        return cls._instance

    @classmethod
    def _create_retriever(cls):
        """创建混合检索器实例。"""
        from tkp_api.services.rag.vector_retrieval import create_retriever
        from tkp_api.services.rag.embeddings import create_embedding_service
        from tkp_api.services.rag.hybrid_retrieval import create_hybrid_retriever

        settings = get_settings()

        # 创建向量检索器
        embedding_service = create_embedding_service(
            api_key=settings.openai_api_key.get_secret_value(),
            model=settings.openai_embedding_model,
        )
        vector_retriever = create_retriever(
            embedding_service=embedding_service,
            top_k=settings.retrieval_top_k,
            similarity_threshold=settings.retrieval_similarity_threshold,
        )

        # 创建 Elasticsearch 客户端（如果启用）
        elasticsearch_client = None
        if settings.elasticsearch_enabled:
            try:
                from tkp_api.services.rag.elasticsearch_client import create_elasticsearch_client

                elasticsearch_client = create_elasticsearch_client(
                    hosts=settings.elasticsearch_hosts.split(","),
                    api_key=settings.elasticsearch_api_key or None,
                    username=settings.elasticsearch_username or None,
                    password=settings.elasticsearch_password or None,
                    verify_certs=settings.elasticsearch_verify_certs,
                )
            except Exception as exc:
                import logging

                logging.warning("failed to initialize elasticsearch: %s", exc)

        # 创建重排序器（如果启用）
        reranker = None
        if settings.retrieval_enable_rerank and settings.rerank_api_key:
            try:
                from tkp_api.services.rag.reranker import create_reranker

                reranker = create_reranker(
                    provider=settings.rerank_provider,
                    api_key=settings.rerank_api_key,
                    model=settings.rerank_model or None,
                    top_n=settings.rerank_top_n,
                )
            except Exception as exc:
                import logging

                logging.warning("failed to initialize reranker: %s", exc)

        # 创建查询改写器（如果启用）
        query_rewriter = None
        if settings.retrieval_enable_query_rewrite:
            try:
                from tkp_api.services.rag.query_rewriter import create_query_rewriter

                query_rewriter = create_query_rewriter(
                    api_key=settings.openai_api_key.get_secret_value(),
                    model=settings.openai_chat_model,
                    strategy=settings.query_rewrite_strategy,
                )
            except Exception as exc:
                import logging

                logging.warning("failed to initialize query rewriter: %s", exc)

        # 创建混合检索器
        return create_hybrid_retriever(
            vector_retriever=vector_retriever,
            elasticsearch_client=elasticsearch_client,
            reranker=reranker,
            query_rewriter=query_rewriter,
            vector_weight=settings.retrieval_vector_weight,
            fulltext_weight=settings.retrieval_fulltext_weight,
        )

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例实例（主要用于测试）。"""
        with cls._lock:
            cls._instance = None


@lru_cache(maxsize=1)
def _get_hybrid_retriever():
    """获取混合检索器单例（使用 lru_cache 确保单例）。"""
    return HybridRetrieverSingleton.get_instance()


def _compose_answer(question: str, hits: list[dict[str, object]]) -> str:
    """根据命中结果组装可复现回答。"""
    if not hits:
        return f"未检索到与问题“{question}”相关的知识片段。"
    bullet_lines = [f"- {str(hit.get('snippet') or '')}" for hit in hits[:3]]
    return "基于知识库检索到以下信息:\n" + "\n".join(bullet_lines)


def query_chunks(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID],
    query: str,
    top_k: int,
    filters: dict[str, Any] | None = None,
    with_citations: bool = True,
    retrieval_strategy: str = "hybrid",
    min_score: int = 0,
) -> dict[str, Any]:
    """查询检索结果（支持混合检索）。"""
    start = time.perf_counter()
    settings = get_settings()

    # 使用配置的默认策略（如果未指定）
    if retrieval_strategy == "hybrid" and not settings.elasticsearch_enabled:
        retrieval_strategy = "vector"

    # 使用混合检索器
    try:
        hybrid_retriever = _get_hybrid_retriever()
        result = hybrid_retriever.retrieve(
            db,
            query=query,
            tenant_id=tenant_id,
            kb_ids=kb_ids,
            top_k=top_k,
            strategy=retrieval_strategy,
            enable_rerank=settings.retrieval_enable_rerank,
            enable_query_rewrite=settings.retrieval_enable_query_rewrite,
        )

        latency_ms = int((time.perf_counter() - start) * 1000)

        return {
            "hits": result["hits"],
            "latency_ms": latency_ms,
            "retrieval_strategy": result["strategy"],
            "query_rewrite": result["query_rewrite"],
            "effective_min_score": min_score,
            "rerank_applied": result["rerank_applied"],
        }
    except Exception as exc:
        import logging

        logging.exception("hybrid retrieval failed, fallback to simple vector search: %s", exc)

        # 回退到简单向量检索
        hits = search_chunks_improved(
            db,
            tenant_id=tenant_id,
            kb_ids=kb_ids,
            query=query,
            top_k=top_k,
        )

        latency_ms = int((time.perf_counter() - start) * 1000)

        return {
            "hits": hits,
            "latency_ms": latency_ms,
            "retrieval_strategy": "vector",
            "query_rewrite": {
                "original_query": query,
                "rewritten_query": query,
                "rewrite_applied": False,
            },
            "effective_min_score": min_score,
            "rerank_applied": False,
        }


def generate_chat_answer(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID],
    question: str,
    top_k: int = 6,
    context_messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """生成问答回复（使用本地 RAG 模块）。

    Args:
        db: 数据库会话
        tenant_id: 租户ID
        kb_ids: 知识库ID列表
        question: 用户问题
        top_k: 检索结果数量
        context_messages: 历史对话消息（用于上下文记忆）

    Returns:
        包含 answer、citations、usage 的字典
    """
    # 使用本地 RAG 模块生成答案
    result = generate_answer_improved(
        db,
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        question=question,
        top_k=top_k,
        history_messages=context_messages,
    )
    return result
