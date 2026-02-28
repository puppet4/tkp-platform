"""应用异常处理注册。"""

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from tkp_api.utils.response import DEFAULT_ERROR_MESSAGE, error_payload


def _default_http_error_code(status_code: int) -> str:
    if status_code == status.HTTP_400_BAD_REQUEST:
        return "BAD_REQUEST"
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "UNAUTHORIZED"
    if status_code == status.HTTP_403_FORBIDDEN:
        return "FORBIDDEN"
    if status_code == status.HTTP_404_NOT_FOUND:
        return "NOT_FOUND"
    if status_code == status.HTTP_409_CONFLICT:
        return "CONFLICT"
    if status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
        return "VALIDATION_ERROR"
    return "HTTP_ERROR"


def _default_http_message(status_code: int) -> str:
    if status_code == status.HTTP_400_BAD_REQUEST:
        return "请求参数不合法。"
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "未登录或登录状态已失效。"
    if status_code == status.HTTP_403_FORBIDDEN:
        return "无权限访问该资源。"
    if status_code == status.HTTP_404_NOT_FOUND:
        return "请求资源不存在。"
    if status_code == status.HTTP_409_CONFLICT:
        return "请求与当前数据状态冲突。"
    if status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
        return "请求参数校验失败。"
    return "请求处理失败。"


def _default_http_suggestion(status_code: int) -> str:
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return "请重新登录并携带有效访问令牌。"
    if status_code == status.HTTP_403_FORBIDDEN:
        return "请确认当前账号权限及访问令牌中的租户上下文是否正确。"
    if status_code == status.HTTP_404_NOT_FOUND:
        return "请确认资源 ID 是否正确，或资源是否已被删除。"
    if status_code == status.HTTP_409_CONFLICT:
        return "请刷新页面获取最新数据后重试。"
    if status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
        return "请根据错误字段提示修正请求参数后重试。"
    return "请稍后重试，若持续失败请联系管理员。"


def _normalize_raw_detail_message(raw: str, status_code: int) -> str:
    normalized = raw.strip().lower()
    if normalized == "forbidden":
        return _default_http_message(status.HTTP_403_FORBIDDEN)
    if normalized in {"unauthorized", "invalid credentials"}:
        return _default_http_message(status.HTTP_401_UNAUTHORIZED)
    if normalized in {"x-tenant-id required", "invalid x-tenant-id"}:
        return "缺少或非法的租户上下文。"
    if normalized == "tenant not found":
        return "租户不存在或已删除。"
    return raw


def _parse_http_detail(detail: object, status_code: int) -> tuple[str, str, dict[str, object]]:
    code = _default_http_error_code(status_code)
    message = _default_http_message(status_code)
    details: dict[str, object] = {
        "status_code": status_code,
        "reason": code.lower(),
        "suggestion": _default_http_suggestion(status_code),
    }

    if isinstance(detail, dict):
        code = str(detail.get("code") or code)
        message = str(detail.get("message") or detail.get("detail") or message)
        raw_details = detail.get("details")
        if isinstance(raw_details, dict):
            details.update(raw_details)
        elif raw_details is not None:
            details["details"] = raw_details

        for key, value in detail.items():
            if key in {"code", "message", "details"}:
                continue
            details[key] = value
        return code, message, details

    if isinstance(detail, str):
        return code, _normalize_raw_detail_message(detail, status_code), details

    if detail is not None:
        details["detail"] = detail
    return code, message, details


async def http_exception_handler(request: Request, exc: HTTPException):
    """将协议异常统一包装为标准错误结构。"""
    code, message, details = _parse_http_detail(exc.detail, exc.status_code)
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(request, code=code, message=message, details=details),
    )


async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """统一处理请求参数校验错误。"""
    normalized_errors = [
        {
            "field": ".".join(str(item) for item in err.get("loc", []) if item != "body"),
            "message": err.get("msg"),
            "type": err.get("type"),
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content=error_payload(
            request,
            code="VALIDATION_ERROR",
            message="请求参数校验失败。",
            details={
                "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
                "reason": "validation_error",
                "suggestion": _default_http_suggestion(status.HTTP_422_UNPROCESSABLE_CONTENT),
                "errors": normalized_errors,
            },
        ),
    )


async def unexpected_exception_handler(request: Request, exc: Exception):
    """处理未捕获异常，避免内部细节泄露。"""
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=error_payload(
            request,
            code="INTERNAL_ERROR",
            message=DEFAULT_ERROR_MESSAGE,
            details={
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "reason": "unexpected_exception",
                "suggestion": "请稍后重试，若持续失败请联系管理员并提供 request_id。",
            },
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """集中注册异常处理器。"""
    app.exception_handler(HTTPException)(http_exception_handler)
    app.exception_handler(RequestValidationError)(validation_exception_handler)
    app.exception_handler(Exception)(unexpected_exception_handler)
