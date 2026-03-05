"""运行态运维接口。"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from tkp_api.dependencies import require_tenant_roles
from tkp_api.db.session import get_db
from tkp_api.models.enums import TenantRole
from tkp_api.schemas.ops import (
    AlertDispatchRequest,
    AlertWebhookUpsertRequest,
    IncidentTicketCreateRequest,
    IncidentTicketUpdateRequest,
    QuotaPolicyUpsertRequest,
    RetrievalEvalRequest,
    RetrievalEvalRunCreateRequest,
)
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import (
    CostSummaryData,
    CostLeaderboardItemData,
    AlertDispatchResultData,
    AlertWebhookData,
    IncidentDiagnosisItemData,
    IncidentTicketData,
    IngestionOpsAlertsData,
    IngestionOpsMetricsData,
    MVPSLOSummaryData,
    OpsOverviewData,
    QuotaAlertData,
    QuotaPolicyData,
    RetrievalEvalCompareData,
    RetrievalEvalRunData,
    RetrievalEvalRunDetailData,
    RetrievalEvalSummaryData,
    RetrievalQualityMetricsData,
    TenantHealthItemData,
)
from tkp_api.services import filter_readable_kb_ids
from tkp_api.services.ops_metrics import (
    build_ingestion_alerts,
    build_ingestion_metrics,
    build_mvp_slo_summary,
    build_retrieval_eval_summary,
    build_retrieval_quality_metrics,
)
from tkp_api.services.cost import build_tenant_cost_summary
from tkp_api.services.quota import list_quota_alerts, list_quota_policies, upsert_quota_policy
from tkp_api.services.ops_center import (
    build_cost_leaderboard,
    build_incident_diagnosis,
    build_ops_overview,
    build_tenant_health,
    create_incident_ticket,
    dispatch_alerts,
    list_alert_webhooks,
    list_incident_tickets,
    update_incident_ticket,
    upsert_alert_webhook,
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


@router.put(
    "/quotas",
    summary="创建或更新配额策略",
    description="配置租户/工作空间配额策略，超限时返回 QUOTA_EXCEEDED。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[QuotaPolicyData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def put_quota_policy(
    payload: QuotaPolicyUpsertRequest,
    request: Request,
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """创建或更新配额策略。"""
    data = upsert_quota_policy(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        metric_code=payload.metric_code,
        scope_type=payload.scope_type,
        scope_id=payload.scope_id,
        limit_value=payload.limit_value,
        window_minutes=payload.window_minutes,
        enabled=payload.enabled,
    )
    db.commit()
    return success(request, data)


@router.get(
    "/quotas",
    summary="查询配额策略列表",
    description="返回当前租户生效与未生效的配额策略。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[QuotaPolicyData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_quota_policies(
    request: Request,
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """查询配额策略列表。"""
    return success(request, list_quota_policies(db, tenant_id=ctx.tenant_id))


@router.get(
    "/quotas/alerts",
    summary="查询配额超限告警",
    description="返回窗口内 QUOTA_EXCEEDED 事件，便于运维系统消费。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[QuotaAlertData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_quota_alerts(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168, description="告警查询时间窗（小时）。"),
    limit: int = Query(default=20, ge=1, le=200, description="返回条数上限。"),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """查询配额超限告警。"""
    return success(
        request,
        list_quota_alerts(
            db,
            tenant_id=ctx.tenant_id,
            limit=limit,
            window_hours=window_hours,
        ),
    )


@router.get(
    "/cost/summary",
    summary="查询租户成本汇总",
    description="按租户汇总检索请求、chat token、agent run 与估算成本。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[CostSummaryData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_cost_summary(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168, description="统计时间窗（小时）。"),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """查询租户成本汇总。"""
    return success(
        request,
        build_tenant_cost_summary(db, tenant_id=ctx.tenant_id, window_hours=window_hours),
    )


@router.get(
    "/overview",
    summary="查询运营后台概览",
    description="聚合入库健康、检索质量、工单与成本视图。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[OpsOverviewData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_ops_overview(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168, description="统计时间窗（小时）。"),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """查询运营后台概览。"""
    return success(
        request,
        build_ops_overview(db, tenant_id=ctx.tenant_id, window_hours=window_hours),
    )


@router.get(
    "/tenant-health",
    summary="查询租户健康分项",
    description="按工作空间输出文档可用性与检索健康状态。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[TenantHealthItemData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_tenant_health(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168, description="统计时间窗（小时）。"),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """查询租户健康分项。"""
    return success(
        request,
        build_tenant_health(db, tenant_id=ctx.tenant_id, window_hours=window_hours),
    )


@router.get(
    "/cost/leaderboard",
    summary="查询租户成本榜单",
    description="按用户聚合检索、chat token 与 agent 成本。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[CostLeaderboardItemData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_cost_leaderboard(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168, description="统计时间窗（小时）。"),
    limit: int = Query(default=10, ge=1, le=100, description="返回榜单条数。"),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """查询租户成本榜单。"""
    return success(
        request,
        build_cost_leaderboard(db, tenant_id=ctx.tenant_id, window_hours=window_hours, limit=limit),
    )


@router.get(
    "/incidents/diagnosis",
    summary="查询异常诊断",
    description="输出 dead-letter 与失败率等关键异常诊断项。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[IncidentDiagnosisItemData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_incident_diagnosis(
    request: Request,
    window_hours: int = Query(default=24, ge=1, le=168, description="统计时间窗（小时）。"),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """查询异常诊断。"""
    return success(
        request,
        build_incident_diagnosis(db, tenant_id=ctx.tenant_id, window_hours=window_hours),
    )


@router.post(
    "/incidents/tickets",
    summary="创建异常工单",
    description="将诊断结果工单化，进入排障闭环。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[IncidentTicketData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def post_incident_ticket(
    payload: IncidentTicketCreateRequest,
    request: Request,
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """创建异常工单。"""
    data = create_incident_ticket(
        db,
        tenant_id=ctx.tenant_id,
        user_id=ctx.user_id,
        source_code=payload.source_code,
        severity=payload.severity,
        title=payload.title,
        summary=payload.summary,
        diagnosis=payload.diagnosis,
        context=payload.context,
    )
    db.commit()
    return success(request, data)


@router.get(
    "/incidents/tickets",
    summary="查询异常工单列表",
    description="按状态与严重级别筛选租户工单。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[IncidentTicketData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_incident_tickets(
    request: Request,
    status_filter: str | None = Query(default=None, alias="status", description="状态筛选。"),
    severity: str | None = Query(default=None, description="严重级别筛选。"),
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """查询异常工单列表。"""
    return success(
        request,
        list_incident_tickets(
            db,
            tenant_id=ctx.tenant_id,
            status=status_filter,
            severity=severity,
            limit=limit,
            offset=offset,
        ),
    )


@router.patch(
    "/incidents/tickets/{ticket_id}",
    summary="更新异常工单",
    description="更新工单状态、处理人或处理结论。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[IncidentTicketData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def patch_incident_ticket(
    ticket_id: UUID,
    payload: IncidentTicketUpdateRequest,
    request: Request,
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """更新异常工单。"""
    data = update_incident_ticket(
        db,
        tenant_id=ctx.tenant_id,
        ticket_id=ticket_id,
        status=payload.status,
        assignee_user_id=payload.assignee_user_id,
        resolution_note=payload.resolution_note,
    )
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="incident ticket not found")
    db.commit()
    return success(request, data)


@router.put(
    "/alerts/webhooks",
    summary="创建或更新告警 webhook",
    description="按名称维护 webhook 通知通道。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[AlertWebhookData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def put_alert_webhook(
    payload: AlertWebhookUpsertRequest,
    request: Request,
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """创建或更新告警 webhook。"""
    data = upsert_alert_webhook(
        db,
        tenant_id=ctx.tenant_id,
        name=payload.name,
        url=payload.url,
        secret=payload.secret,
        enabled=payload.enabled,
        event_types=payload.event_types,
        timeout_seconds=payload.timeout_seconds,
    )
    db.commit()
    return success(request, data)


@router.get(
    "/alerts/webhooks",
    summary="查询告警 webhook 列表",
    description="返回当前租户的 webhook 订阅配置。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[AlertWebhookData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
def get_alert_webhooks(
    request: Request,
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """查询告警 webhook 列表。"""
    return success(request, list_alert_webhooks(db, tenant_id=ctx.tenant_id))


@router.post(
    "/alerts/dispatch",
    summary="执行告警分发",
    description="按事件类型匹配 webhook 并分发告警，支持 dry-run 演练。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[AlertDispatchResultData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
def post_alert_dispatch(
    payload: AlertDispatchRequest,
    request: Request,
    ctx=Depends(require_tenant_roles(TenantRole.OWNER, TenantRole.ADMIN)),
    db: Session = Depends(get_db),
):
    """执行告警分发。"""
    data = dispatch_alerts(
        db,
        tenant_id=ctx.tenant_id,
        event_type=payload.event_type,
        severity=payload.severity,
        title=payload.title,
        message=payload.message,
        attributes=payload.attributes,
        dry_run=payload.dry_run,
    )
    db.commit()
    return success(request, data)
