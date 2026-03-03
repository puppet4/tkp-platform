"""运行态运维接口。"""

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from tkp_api.dependencies import require_tenant_roles
from tkp_api.db.session import get_db
from tkp_api.models.enums import TenantRole
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import IngestionOpsMetricsData
from tkp_api.services.ops_metrics import build_ingestion_metrics
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
