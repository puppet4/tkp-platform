"""检索接口。"""

import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from tkp_api.dependencies import get_request_context
from tkp_api.db.session import get_db
from tkp_api.models.knowledge import RetrievalLog
from tkp_api.utils.response import success
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import RetrievalQueryData
from tkp_api.schemas.retrieval import RetrievalQueryRequest
from tkp_api.services import PermissionAction, filter_readable_kb_ids, require_tenant_action, search_chunks

router = APIRouter(prefix="/retrieval", tags=["retrieval"])


@router.post(
    "/query",
    summary="检索知识切片",
    description="在当前用户可访问的知识库范围内执行检索。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[RetrievalQueryData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
def retrieval_query(
    payload: RetrievalQueryRequest,
    request: Request,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """执行检索并记录检索日志，便于追踪与回放。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.RETRIEVAL_QUERY,
    )
    start = time.perf_counter()

    # 计算当前用户真实可读知识库范围，防止前端直接传入越权 kb_id。
    readable_kb_ids = filter_readable_kb_ids(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        kb_ids=payload.kb_ids or None,
    )
    if payload.kb_ids and len(readable_kb_ids) != len(set(payload.kb_ids)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden kb scope")

    hits = search_chunks(
        db,
        tenant_id=ctx.tenant_id,
        kb_ids=readable_kb_ids,
        query=payload.query,
        top_k=payload.top_k,
    )

    # 记录端到端检索耗时，便于后续性能分析。
    latency_ms = int((time.perf_counter() - start) * 1000)

    # 将检索请求与结果快照写入日志表，用于审计、回放与质量分析。
    db.add(
        RetrievalLog(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            query_text=payload.query,
            kb_ids=[str(k) for k in readable_kb_ids],
            top_k=payload.top_k,
            filter_json=payload.filters,
            result_chunks=hits,
            latency_ms=latency_ms,
        )
    )
    db.commit()

    return success(request, {"hits": hits, "latency_ms": latency_ms})
