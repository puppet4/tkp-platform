"""RAG 服务封装（使用本地 RAG 模块）。"""

from __future__ import annotations

import time
from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from tkp_api.core.config import get_settings
from tkp_api.services.rag import search_chunks_improved, generate_answer_improved


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
    """查询检索结果（使用本地 RAG 模块）。"""
    start = time.perf_counter()

    # 使用本地 RAG 模块进行检索
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
) -> dict[str, Any]:
    """生成问答回复（使用本地 RAG 模块）。"""
    # 使用本地 RAG 模块生成答案
    result = generate_answer_improved(
        db,
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        question=question,
        top_k=top_k,
    )
    return result
