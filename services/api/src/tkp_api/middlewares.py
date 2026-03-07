"""应用中间件注册。"""

import json
from time import perf_counter
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.middleware.base import BaseHTTPMiddleware

from tkp_api.core.config import get_settings
from tkp_api.utils.masking import default_masker

settings = get_settings()

# 创建限流器
limiter = Limiter(key_func=get_remote_address, default_limits=["100/minute"])


async def request_id_middleware(request: Request, call_next):
    """注入请求追踪 ID，并通过响应头返回。"""
    request.state.request_id = str(uuid.uuid4())
    request.state.request_started_at = perf_counter()
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    elapsed = perf_counter() - request.state.request_started_at
    response.headers["X-Process-Time-Ms"] = str(round(elapsed * 1000, 2))
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

    # 2. 敏感数据脱敏中间件
    if not settings.app_debug:  # 仅在生产环境启用
        app.add_middleware(SensitiveDataMaskingMiddleware)

    # 3. 请求 ID 和计时中间件
    app.middleware("http")(request_id_middleware)

    # 4. API 限流
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
