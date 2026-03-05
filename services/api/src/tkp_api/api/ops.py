"""运行态运维接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from tkp_api.dependencies import require_tenant_roles
from tkp_api.db.session import get_db
from tkp_api.models.enums import TenantRole
from tkp_api.schemas.ops import RetrievalEvalRequest, RetrievalEvalRunCreateRequest
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import (
    IngestionOpsAlertsData,
    IngestionOpsMetricsData,
    MVPSLOSummaryData,
    RetrievalEvalCompareData,
    RetrievalEvalRunData,
    RetrievalEvalRunDetailData,
    RetrievalEvalSummaryData,
    RetrievalQualityMetricsData,
)
from tkp_api.services import filter_readable_kb_ids
from tkp_api.services.ops_metrics import (
    build_ingestion_alerts,
    build_ingestion_metrics,
    build_mvp_slo_summary,
    build_retrieval_eval_summary,
    build_retrieval_quality_metrics,
)
from tkp_api.services.retrieval_eval import (
    compare_retrieval_eval_runs,
    create_retrieval_eval_run,
    get_retrieval_eval_run_detail,
    list_retrieval_eval_runs,
)
from tkp_api.utils.response import success

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get(
    "/ingestion/metrics",
    summary="查询入库运行指标",
    description="返回当前租户入库任务的积压、失败率、耗时与卡住任务指标。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[IngestionOpsMetricsData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_ingestion_metrics(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168, description="统计时间窗（小时）。"),
    stale_seconds: int = Query(default=120, ge=30, le=3600, description="processing 心跳超时阈值（秒）。"),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """按租户聚合入库任务运行态指标。"""
    data = build_ingestion_metrics(
        db,
        tenant_id=ctx.tenant_id,
        window_hours=window_hours,
        stale_seconds=stale_seconds,
    )
    return success(request, data)


@router.get(
    "/ingestion/alerts",
    summary="查询入库告警状态",
    description="基于入库指标返回规则级告警状态，便于监控系统直接接入。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[IngestionOpsAlertsData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_ingestion_alerts(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168, description="统计时间窗（小时）。"),
    stale_seconds: int = Query(default=120, ge=30, le=3600, description="processing 心跳超时阈值（秒）。"),
    backlog_warn: int = Query(default=20, ge=0, le=50000, description="积压告警阈值。"),
    backlog_critical: int = Query(default=50, ge=0, le=50000, description="积压严重告警阈值。"),
    failure_rate_warn: float = Query(default=0.05, ge=0.0, le=1.0, description="失败率告警阈值。"),
    failure_rate_critical: float = Query(default=0.2, ge=0.0, le=1.0, description="失败率严重告警阈值。"),
    stale_warn: int = Query(default=1, ge=0, le=10000, description="卡住任务告警阈值。"),
    stale_critical: int = Query(default=3, ge=0, le=10000, description="卡住任务严重告警阈值。"),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """按租户输出入库告警状态。"""
    metrics = build_ingestion_metrics(
        db,
        tenant_id=ctx.tenant_id,
        window_hours=window_hours,
        stale_seconds=stale_seconds,
    )
    alerts = build_ingestion_alerts(
        metrics,
        backlog_warn=backlog_warn,
        backlog_critical=backlog_critical,
        failure_rate_warn=failure_rate_warn,
        failure_rate_critical=failure_rate_critical,
        stale_warn=stale_warn,
        stale_critical=stale_critical,
    )
    return success(request, alerts)


@router.get(
    "/retrieval/quality",
    summary="查询检索质量指标",
    description="返回检索零命中率、引用覆盖率和延迟分位等质量指标。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[RetrievalQualityMetricsData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_retrieval_quality_metrics(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168, description="统计时间窗（小时）。"),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """按租户聚合检索质量指标。"""
    data = build_retrieval_quality_metrics(
        db,
        tenant_id=ctx.tenant_id,
        window_hours=window_hours,
    )
    return success(request, data)


@router.get(
    "/slo/mvp-summary",
    summary="查询 MVP SLO 摘要",
    description="汇总入库与检索关键指标，并返回 MVP 阶段的达标状态。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[MVPSLOSummaryData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_mvp_slo_summary(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168, description="统计时间窗（小时）。"),
    ingestion_failure_rate_target: float = Query(default=0.10, ge=0.0, le=1.0, description="入库失败率目标上限。"),
    ingestion_p95_latency_target_ms: int = Query(default=300000, ge=1, le=86400000, description="入库 p95 耗时目标上限（毫秒）。"),
    retrieval_zero_hit_rate_target: float = Query(default=0.30, ge=0.0, le=1.0, description="检索零命中率目标上限。"),
    retrieval_p95_latency_target_ms: int = Query(default=3000, ge=1, le=600000, description="检索 p95 耗时目标上限（毫秒）。"),
    retrieval_citation_coverage_target: float = Query(default=0.95, ge=0.0, le=1.0, description="检索引用覆盖率目标下限。"),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """输出 MVP 阶段 SLO 达标摘要。"""
    data = build_mvp_slo_summary(
        db,
        tenant_id=ctx.tenant_id,
        window_hours=window_hours,
        ingestion_failure_rate_target=ingestion_failure_rate_target,
        ingestion_p95_latency_target_ms=ingestion_p95_latency_target_ms,
        retrieval_zero_hit_rate_target=retrieval_zero_hit_rate_target,
        retrieval_p95_latency_target_ms=retrieval_p95_latency_target_ms,
        retrieval_citation_coverage_target=retrieval_citation_coverage_target,
    )
    return success(request, data)


@router.post(
    "/retrieval/evaluate",
    summary="执行检索评测",
    description="按样本批量执行检索并返回 hit@k、引用覆盖率和耗时汇总。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[RetrievalEvalSummaryData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def evaluate_retrieval(
    payload: RetrievalEvalRequest,
    request: Request,
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """执行最小检索评测闭环。"""
    readable_kb_ids = filter_readable_kb_ids(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        kb_ids=payload.kb_ids or None,
    )
    if payload.kb_ids and len(readable_kb_ids) != len(set(payload.kb_ids)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden kb scope")

    data = build_retrieval_eval_summary(
        db,
        tenant_id=ctx.tenant_id,
        kb_ids=readable_kb_ids,
        top_k=payload.top_k,
        samples=[{"query": item.query, "expected_terms": item.expected_terms} for item in payload.samples],
    )
    return success(request, data)


@router.post(
    "/retrieval/evaluate/runs",
    summary="创建检索评测运行记录",
    description="执行检索评测并将结果持久化为可追踪运行记录。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[RetrievalEvalRunDetailData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def create_retrieval_eval(
    payload: RetrievalEvalRunCreateRequest,
    request: Request,
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """创建评测运行并返回详情。"""
    readable_kb_ids = filter_readable_kb_ids(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        kb_ids=payload.kb_ids or None,
    )
    if payload.kb_ids and len(readable_kb_ids) != len(set(payload.kb_ids)):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="forbidden kb scope")

    data = create_retrieval_eval_run(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        name=payload.name,
        kb_ids=readable_kb_ids,
        top_k=payload.top_k,
        samples=[{"query": item.query, "expected_terms": item.expected_terms} for item in payload.samples],
    )
    data["status"] = "completed"
    return success(request, data)


@router.get(
    "/retrieval/evaluate/runs",
    summary="查询检索评测运行列表",
    description="按时间倒序返回评测运行记录。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[RetrievalEvalRunData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_retrieval_eval_runs(
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """分页查询评测运行。"""
    data = list_retrieval_eval_runs(db, tenant_id=ctx.tenant_id, limit=limit, offset=offset)
    return success(request, data)


@router.get(
    "/retrieval/evaluate/runs/{run_id}",
    summary="查询检索评测运行详情",
    description="返回单次评测运行详情及样本结果。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[RetrievalEvalRunDetailData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_retrieval_eval_run(
    request: Request,
    run_id: UUID,
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """查询单次评测详情。"""
    data = get_retrieval_eval_run_detail(db, tenant_id=ctx.tenant_id, run_id=run_id)
    return success(request, data)


@router.get(
    "/retrieval/evaluate/compare",
    summary="对比两次检索评测",
    description="按运行 ID 对比评测结果差异。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[RetrievalEvalCompareData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def compare_retrieval_eval(
    request: Request,
    baseline_run_id: UUID = Query(..., description="基线运行 ID。"),
    current_run_id: UUID = Query(..., description="当前运行 ID。"),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """执行评测结果对比。"""
    data = compare_retrieval_eval_runs(
        db,
        tenant_id=ctx.tenant_id,
        baseline_run_id=baseline_run_id,
        current_run_id=current_run_id,
    )
    return success(request, data)
