"""应用异常处理注册。"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from tkp_api.utils.response import DEFAULT_ERROR_MESSAGE, error_payload


async def http_exception_handler(request: Request, exc: HTTPException):
    """将协议异常统一包装为标准错误结构。"""
    code = "FORBIDDEN" if exc.status_code == status.HTTP_403_FORBIDDEN else "HTTP_ERROR"
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(request, code=code, message=str(exc.detail)),
    )


async def unexpected_exception_handler(request: Request, exc: Exception):
    """处理未捕获异常，避免内部细节泄露。"""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_payload(request, code="INTERNAL_ERROR", message=DEFAULT_ERROR_MESSAGE),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """集中注册异常处理器。"""
    app.exception_handler(HTTPException)(http_exception_handler)
    app.exception_handler(Exception)(unexpected_exception_handler)
