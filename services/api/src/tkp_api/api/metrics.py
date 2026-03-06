"""Prometheus 指标导出端点。"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["metrics"])


@router.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    """导出 Prometheus 格式的指标。"""
    try:
        from prometheus_client import REGISTRY, generate_latest

        metrics = generate_latest(REGISTRY)
        return PlainTextResponse(content=metrics.decode("utf-8"))
    except ImportError:
        return PlainTextResponse(content="# Prometheus client not installed\n")
