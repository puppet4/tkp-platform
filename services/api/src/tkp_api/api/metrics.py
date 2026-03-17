"""Prometheus 指标导出端点。"""

import os

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["metrics"])

_METRICS_TOKEN = os.getenv("METRICS_TOKEN", "")


@router.get("/metrics", response_class=PlainTextResponse)
def prometheus_metrics(request: Request):
    """导出 Prometheus 格式的指标。"""
    if _METRICS_TOKEN:
        auth = request.headers.get("Authorization", "")
        if auth != f"Bearer {_METRICS_TOKEN}":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    try:
        from prometheus_client import REGISTRY, generate_latest

        metrics = generate_latest(REGISTRY)
        return PlainTextResponse(content=metrics.decode("utf-8"))
    except ImportError:
        return PlainTextResponse(content="# Prometheus client not installed\n")
