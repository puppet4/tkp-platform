"""RAG 服务封装 — 瘦 facade，委托给统一管线。"""

from __future__ import annotations

import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from tkp_api.services.pipeline.pipeline import PipelineSingleton
from tkp_api.services.pipeline.scoring import api_min_score_to_internal, score_to_api
from tkp_api.services.pipeline.types import GenerationConfig, RetrievalRequest

logger = logging.getLogger("tkp_api.services.retrieval")


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
    """查询检索结果 — 保持原有函数签名不变，内部委托给 Pipeline。"""
    request = RetrievalRequest(
        query=query,
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        top_k=top_k,
        strategy=retrieval_strategy,
        min_score=api_min_score_to_internal(min_score),
        filters=filters or {},
        skip_intent_classification=True,  # retrieval API 不做意图识别
    )

    pipeline = PipelineSingleton.get_instance()
    result = pipeline.retrieve(db, request)

    # 转换为兼容现有 API 的格式
    formatted_hits = []
    for hit in result.hits:
        display_score = score_to_api(hit.final_score)
        formatted_hits.append({
            "chunk_id": hit.chunk_id,
            "document_id": hit.document_id,
            "document_version_id": hit.document_version_id,
            "kb_id": hit.kb_id,
            "chunk_no": hit.chunk_no,
            "title_path": hit.document_title,
            "score": display_score,
            "match_type": hit.retrieval_method,
            "snippet": hit.content[:200],
            "metadata": hit.metadata,
            "citation": None,
            "reason": f"相似度: {hit.final_score:.2%}",
            "matched_terms": [],
            "score_breakdown": {
                "vector_score": score_to_api(hit.vector_score),
                "keyword_score": score_to_api(hit.keyword_score),
                "rerank_bonus": 0,
                "final_score": display_score,
            },
        })

    return {
        "hits": formatted_hits,
        "latency_ms": result.latency_ms,
        "retrieval_strategy": result.strategy,
        "query_rewrite": result.query_rewrite,
        "effective_min_score": min_score,
        "rerank_applied": result.rerank_applied,
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
    """生成问答回复 — 保持原有函数签名不变。"""
    request = RetrievalRequest(
        query=question,
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        top_k=top_k,
        history_messages=context_messages,
        generation_config=GenerationConfig(),
        skip_intent_classification=False,
    )

    pipeline = PipelineSingleton.get_instance()
    result = pipeline.generate(db, request)

    return {
        "answer": result.answer,
        "citations": result.citations,
        "usage": result.usage,
        "confidence_score": result.confidence,
        "rejected": result.rejected,
    }
