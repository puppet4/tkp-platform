"""运行态运维接口。"""

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from tkp_api.dependencies import require_tenant_roles
from tkp_api.db.session import get_db
from tkp_api.models.enums import TenantRole
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import IngestionOpsAlertsData, IngestionOpsMetricsData
from tkp_api.services.ops_metrics import build_ingestion_alerts, build_ingestion_metrics
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
