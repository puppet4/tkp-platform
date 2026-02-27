"""健康检查接口。"""

from sqlalchemy import text
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, Request, status

from tkp_api.db.session import get_db
from tkp_api.utils.response import success
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import HealthStatusData

router = APIRouter(prefix="/health", tags=["health"])


@router.get(
    "/live",
    summary="存活探针",
    description="用于容器编排系统检测服务进程是否存活。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[HealthStatusData],
    responses={500: {"model": ErrorResponse}},
)
def live(request: Request):
    """仅表示进程存活，不校验外部依赖。"""
    return success(request, {"status": "ok"})


@router.get(
    "/ready",
    summary="就绪探针",
    description="通过数据库连通性检测服务是否具备对外提供能力。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[HealthStatusData],
    responses={500: {"model": ErrorResponse}},
)
def ready(request: Request, db: Session = Depends(get_db)):
    """执行轻量数据库探活语句验证数据库可用。"""
    # 仅执行最小查询，避免探针请求给数据库带来额外压力。
    db.execute(text("select 1"))
    return success(request, {"status": "ready"})
