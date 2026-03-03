"""RAG 客户端封装（API -> RAG 服务）。"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from tkp_api.core.config import get_settings
from tkp_api.services.rag_client import post_rag_json
from tkp_api.services.retrieval_local import search_chunks


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
    """查询检索结果。"""
    settings = get_settings()
    normalized_filters = filters or {}

    if settings.rag_base_url:
        remote_data = post_rag_json(
            settings.rag_base_url,
            "/internal/retrieval/query",
            payload={
                "tenant_id": str(tenant_id),
                "kb_ids": [str(kb_id) for kb_id in kb_ids],
                "query": query,
                "top_k": top_k,
                "filters": normalized_filters,
                "with_citations": with_citations,
                "retrieval_strategy": retrieval_strategy,
                "min_score": min_score,
            },
            timeout_seconds=settings.rag_timeout_seconds,
            internal_token=settings.internal_service_token,
            max_retries=settings.rag_max_retries,
            retry_backoff_seconds=settings.rag_retry_backoff_seconds,
            circuit_fail_threshold=settings.rag_circuit_breaker_fail_threshold,
            circuit_open_seconds=settings.rag_circuit_breaker_open_seconds,
        )
        hits = remote_data.get("hits", [])
        latency_ms = int(remote_data.get("latency_ms") or 0)
        effective_strategy = str(remote_data.get("retrieval_strategy") or retrieval_strategy)
        if not isinstance(hits, list):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "RAG_UPSTREAM_INVALID_RESPONSE",
                    "message": "检索服务返回结构缺少 hits 数组。",
                    "details": {"reason": "invalid_hits", "path": "/internal/retrieval/query"},
                },
            )
        return {
            "hits": hits,
            "latency_ms": latency_ms,
            "retrieval_strategy": effective_strategy,
        }

    start = time.perf_counter()
    hits = search_chunks(
        db,
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        query=query,
        top_k=top_k,
        filters=normalized_filters,
        with_citations=with_citations,
        retrieval_strategy=retrieval_strategy,
        min_score=min_score,
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    return {
        "hits": hits,
        "latency_ms": latency_ms,
        "retrieval_strategy": retrieval_strategy,
    }


def generate_chat_answer(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID],
    question: str,
    top_k: int = 6,
) -> dict[str, Any]:
    """生成问答回复（检索 + 回答组装）。"""
    settings = get_settings()

    if settings.rag_base_url:
        remote_data = post_rag_json(
            settings.rag_base_url,
            "/internal/chat/generate",
            payload={
                "tenant_id": str(tenant_id),
                "kb_ids": [str(kb_id) for kb_id in kb_ids],
                "question": question,
                "top_k": top_k,
                "filters": {},
                "with_citations": True,
            },
            timeout_seconds=settings.rag_timeout_seconds,
            internal_token=settings.internal_service_token,
            max_retries=settings.rag_max_retries,
            retry_backoff_seconds=settings.rag_retry_backoff_seconds,
            circuit_fail_threshold=settings.rag_circuit_breaker_fail_threshold,
            circuit_open_seconds=settings.rag_circuit_breaker_open_seconds,
        )
        answer = str(remote_data.get("answer") or "")
        citations = remote_data.get("citations", [])
        usage = remote_data.get("usage", {})
        if not isinstance(citations, list) or not isinstance(usage, dict):
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "RAG_UPSTREAM_INVALID_RESPONSE",
                    "message": "检索服务返回结构不完整。",
                    "details": {"reason": "invalid_chat_payload", "path": "/internal/chat/generate"},
                },
            )
        return {"answer": answer, "citations": citations, "usage": usage}

    hits = search_chunks(
        db,
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        query=question,
        top_k=top_k,
        filters={},
        with_citations=True,
    )
    answer_text = _compose_answer(question, hits)
    prompt_tokens = max(1, len(question.split()))
    completion_tokens = max(1, len(answer_text.split()))
    citations = [
        {
            "document_id": hit["document_id"],
            "chunk_id": hit["chunk_id"],
            "document_version_id": hit["document_version_id"],
        }
        for hit in hits
    ]
    return {
        "answer": answer_text,
        "citations": citations,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }
