"""RAG 依赖注入。"""

from fastapi import Header, HTTPException, status

from tkp_rag.core.config import get_settings


def require_internal_token(x_internal_token: str | None = Header(default=None, alias="X-Internal-Token")) -> None:
    """校验内部服务调用令牌。"""
    expected = get_settings().internal_service_token
    if not expected:
        return
    if x_internal_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "INTERNAL_AUTH_FAILED",
                "message": "内部服务鉴权失败。",
                "details": {"reason": "invalid_internal_token"},
            },
        )

