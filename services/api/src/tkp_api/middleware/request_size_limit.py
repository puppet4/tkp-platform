"""请求大小限制中间件。

防止恶意用户发送超大请求导致内存耗尽。
"""

import logging

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """请求大小限制中间件。

    限制请求体大小，防止 DoS 攻击。
    """

    def __init__(self, app, max_size: int = 10 * 1024 * 1024):
        """初始化中间件。

        Args:
            app: FastAPI 应用实例
            max_size: 最大请求体大小（字节），默认 10MB
        """
        super().__init__(app)
        self.max_size = max_size

    async def dispatch(self, request: Request, call_next):
        """检查请求大小。"""
        # 跳过 GET/HEAD/OPTIONS 请求（没有请求体）
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return await call_next(request)

        # 先检查 Content-Length 头（若提供则快速失败）。
        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                size = int(content_length)
                if size > self.max_size:
                    return self._reject_too_large(request, size=size)
            except ValueError:
                # 头非法时不信任该值，进入实际体积校验。
                ...

        # 读取真实请求体再兜底校验，避免缺失/伪造 Content-Length 绕过。
        body = await request.body()
        if len(body) > self.max_size:
            return self._reject_too_large(request, size=len(body))

        return await call_next(request)

    def _reject_too_large(self, request: Request, *, size: int) -> Response:
        logger.warning(
            f"Request body too large: {size} bytes (max: {self.max_size})",
            extra={
                "path": request.url.path,
                "method": request.method,
                "size": size,
            },
        )
        return JSONResponse(
            content={"error": {"code": "REQUEST_TOO_LARGE", "message": "请求体过大"}},
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        )
