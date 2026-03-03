"""RAG 内部接口。"""

import time

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from tkp_rag.dependencies import require_internal_token
from tkp_rag.db.session import get_db
from tkp_rag.schemas.internal import (
    AgentPlanInternalRequest,
    AgentPlanInternalResponse,
    ChatGenerateInternalRequest,
    ChatGenerateInternalResponse,
    RetrievalQueryInternalRequest,
    RetrievalQueryInternalResponse,
)
from tkp_rag.services.agent import build_plan
from tkp_rag.services.retrieval import generate_answer, search_chunks_detailed

router = APIRouter(prefix="/internal", tags=["internal-rag"], dependencies=[Depends(require_internal_token)])


@router.post(
    "/retrieval/query",
    summary="内部检索查询",
    description="由 API 服务调用，执行向量优先检索并返回命中列表。",
    response_model=RetrievalQueryInternalResponse,
)
def retrieval_query(payload: RetrievalQueryInternalRequest, db: Session = Depends(get_db)):
    start = time.perf_counter()
    retrieval = search_chunks_detailed(
        db,
        tenant_id=payload.tenant_id,
        kb_ids=payload.kb_ids,
        query=payload.query,
        top_k=payload.top_k,
        filters=payload.filters,
        with_citations=payload.with_citations,
        retrieval_strategy=payload.retrieval_strategy,
        min_score=payload.min_score,
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    return {
        "hits": retrieval["hits"],
        "latency_ms": latency_ms,
        "retrieval_strategy": payload.retrieval_strategy,
        "query_rewrite": retrieval["query_rewrite"],
        "effective_min_score": retrieval["effective_min_score"],
        "rerank_applied": retrieval["rerank_applied"],
    }


@router.post(
    "/chat/generate",
    summary="内部问答生成",
    description="由 API 服务调用，检索后返回回答、引用与 token 统计。",
    response_model=ChatGenerateInternalResponse,
)
def chat_generate(payload: ChatGenerateInternalRequest, db: Session = Depends(get_db)):
    start = time.perf_counter()
    result = generate_answer(
        db,
        tenant_id=payload.tenant_id,
        kb_ids=payload.kb_ids,
        question=payload.question,
        top_k=payload.top_k,
        filters=payload.filters,
        with_citations=payload.with_citations,
    )
    latency_ms = int((time.perf_counter() - start) * 1000)
    return {
        "answer": result["answer"],
        "citations": result["citations"],
        "usage": result["usage"],
        "latency_ms": latency_ms,
    }


@router.post(
    "/agent/plan",
    summary="内部智能体规划",
    description="由 API 服务调用，返回智能体运行计划与初始状态。",
    response_model=AgentPlanInternalResponse,
)
def agent_plan(payload: AgentPlanInternalRequest):
    return build_plan(
        tenant_id=payload.tenant_id,
        user_id=payload.user_id,
        task=payload.task,
        kb_ids=payload.kb_ids,
        conversation_id=payload.conversation_id,
        tool_policy=payload.tool_policy,
    )
