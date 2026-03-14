"""应用中间件注册。"""

import json
import logging
import uuid
from time import perf_counter

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from tkp_api.core.config import get_settings
from tkp_api.core.rate_limit import limiter
from tkp_api.core.rate_limit_handler import _rate_limit_exceeded_handler
from tkp_api.middleware.request_size_limit import RequestSizeLimitMiddleware
from tkp_api.middleware.transaction import TransactionMiddleware
from tkp_api.utils.masking import default_masker

logger = logging.getLogger(__name__)
settings = get_settings()

# 慢请求阈值（毫秒）
SLOW_REQUEST_THRESHOLD_MS = 1000


async def _rate_limit_exception_handler(request: Request, exc: Exception) -> Response:
    """为 FastAPI 提供通用异常签名的限流处理器。"""
    if isinstance(exc, RateLimitExceeded):
        return await _rate_limit_exceeded_handler(request, exc)
    return Response(
        content='{"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "请求过于频繁，请稍后再试"}}',
        status_code=429,
        media_type="application/json",
    )


async def request_id_middleware(request: Request, call_next):
    """注入请求追踪 ID，并通过响应头返回。"""
    request.state.request_id = str(uuid.uuid4())
    request.state.request_started_at = perf_counter()

    # 跳过健康检查、指标端点和高频轮询接口的日志记录（避免日志噪音）
    skip_logging = request.url.path in [
        "/health/live",
        "/health/ready",
        "/metrics",
        "/api/health/live",
        "/api/health/ready",
        "/api/metrics",
        "/api/auth/me",
        "/api/permissions/me",
        "/api/permissions/ui-manifest",
    ]

    if not skip_logging:
        logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra={
                "request_id": request.state.request_id,
                "method": request.method,
                "path": request.url.path,
            }
        )

    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    elapsed = perf_counter() - request.state.request_started_at
    elapsed_ms = round(elapsed * 1000, 2)
    response.headers["X-Process-Time-Ms"] = str(elapsed_ms)

    # 慢请求告警
    is_slow = elapsed_ms > SLOW_REQUEST_THRESHOLD_MS

    if not skip_logging:
        log_level = logging.WARNING if is_slow else logging.INFO
        logger.log(
            log_level,
            f"Request completed: {request.method} {request.url.path} - {response.status_code}"
            + (f" [SLOW REQUEST]" if is_slow else ""),
            extra={
                "request_id": request.state.request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": elapsed_ms,
                "slow_request": is_slow,
            }
        )

    return response


class SensitiveDataMaskingMiddleware(BaseHTTPMiddleware):
    """敏感数据脱敏中间件。

    在响应中脱敏敏感信息，防止泄露。
    """

    async def dispatch(self, request: Request, call_next):
        """处理请求并脱敏响应。"""
        response = await call_next(request)

        # 只处理 JSON 响应
        if response.headers.get("content-type", "").startswith("application/json"):
            # 读取响应体
            body = b""
            async for chunk in response.body_iterator:
                body += chunk

            try:
                # 解析 JSON
                data = json.loads(body.decode())

                # 脱敏数据
                masked_data = default_masker.mask_dict(data, recursive=True)

                # 重新编码
                masked_body = json.dumps(masked_data, ensure_ascii=False).encode()

                # 创建新响应
                return Response(
                    content=masked_body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )
            except (json.JSONDecodeError, UnicodeDecodeError):
                # 解析失败，返回原响应
                return Response(
                    content=body,
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    media_type=response.media_type,
                )

        return response


def register_middlewares(app: FastAPI) -> None:
    """集中注册中间件。"""

    # 1. CORS 中间件（必须最先注册）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "X-Process-Time-Ms"],
    )

    # 2. 请求大小限制中间件（安全防护）
    app.add_middleware(RequestSizeLimitMiddleware, max_size=settings.request_max_size_bytes)

    # 3. 事务管理中间件（在业务逻辑之前）
    app.add_middleware(TransactionMiddleware)

    # 4. 敏感数据脱敏中间件
    # 注意：响应脱敏会改变 API 契约（例如 access_token/email），破坏前端登录等核心流程。
    # 这里不再挂载响应级脱敏中间件，敏感信息保护应通过日志脱敏与字段最小化实现。

    # 5. 请求 ID 和计时中间件
    app.middleware("http")(request_id_middleware)

    # 6. API 限流（生产环境启用，避免本地/测试因外部存储不可用导致阻断）
    if settings.app_env in {"prod", "production"}:
        app.state.limiter = limiter
        app.add_exception_handler(RateLimitExceeded, _rate_limit_exception_handler)
        app.add_middleware(SlowAPIMiddleware)
