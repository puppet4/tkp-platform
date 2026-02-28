"""统一响应结构工具。"""

from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from fastapi import Request

DEFAULT_ERROR_MESSAGE = "internal server error"

_SUCCESS_MESSAGE_BY_METHOD = {
    "GET": "查询成功。",
    "POST": "操作成功。",
    "PUT": "更新成功。",
    "PATCH": "更新成功。",
    "DELETE": "删除成功。",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _default_success_meta(request: Request) -> dict[str, Any]:
    elapsed_ms = None
    started_at = getattr(request.state, "request_started_at", None)
    if isinstance(started_at, float):
        elapsed_ms = int((perf_counter() - started_at) * 1000)
    return {
        "message": _SUCCESS_MESSAGE_BY_METHOD.get(request.method.upper(), "操作成功。"),
        "method": request.method.upper(),
        "path": request.url.path,
        "timestamp": _utc_now_iso(),
        "process_ms": elapsed_ms,
    }


def success(request: Request, data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """构造统一成功响应结构。"""
    final_meta = _default_success_meta(request)
    if meta:
        final_meta.update(meta)
    return {
        "request_id": request.state.request_id,
        "data": data,
        "meta": final_meta,
    }


def error_payload(
    request: Request,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一错误响应结构。"""
    final_details = {
        "method": request.method.upper(),
        "path": request.url.path,
        "timestamp": _utc_now_iso(),
    }
    if details:
        final_details.update(details)
    return {
        "request_id": request.state.request_id,
        "error": {
            "code": code,
            "message": message,
            "details": final_details,
        },
    }
