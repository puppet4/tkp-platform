"""统一响应结构工具。"""

from typing import Any

from fastapi import Request

DEFAULT_ERROR_MESSAGE = "internal server error"


def success(request: Request, data: Any, meta: dict[str, Any] | None = None) -> dict[str, Any]:
    """构造统一成功响应结构。"""
    return {
        "request_id": request.state.request_id,
        "data": data,
        "meta": meta or {},
    }


def error_payload(
    request: Request,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """构造统一错误响应结构。"""
    return {
        "request_id": request.state.request_id,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
    }
