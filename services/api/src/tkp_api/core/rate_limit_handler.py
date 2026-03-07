"""slowapi 限流异常处理器。"""

from fastapi import Request, Response, status
from slowapi.errors import RateLimitExceeded


async def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> Response:
    """处理限流异常。"""
    return Response(
        content='{"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "请求过于频繁，请稍后再试"}}',
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        media_type="application/json",
        headers={"Retry-After": "60"},
    )
