"""API 限流配置。

提供灵活的限流策略配置。
"""

from slowapi import Limiter
from slowapi.util import get_remote_address

from tkp_api.core.config import get_settings

settings = get_settings()


def get_rate_limit_key(request):
    """获取限流键（支持多种策略）。"""
    # 优先使用用户ID（如果已认证）
    if hasattr(request.state, "user_id"):
        return f"user:{request.state.user_id}"

    # 回退到IP地址
    return f"ip:{get_remote_address(request)}"


# 创建限流器
limiter = Limiter(
    key_func=get_rate_limit_key,
    default_limits=[settings.rate_limit_default],
    storage_uri=settings.redis_url if settings.redis_url else "memory://",
)


# 不同端点的限流策略
RATE_LIMITS = {
    # 认证相关（更严格）
    "auth": "10/minute",
    "login": "5/minute",

    # 文档上传（限制较严）
    "upload": "20/minute",

    # 查询接口（相对宽松）
    "query": "100/minute",

    # 管理接口（中等）
    "admin": "50/minute",
}


def get_rate_limit(endpoint_type: str) -> str:
    """获取指定端点类型的限流策略。

    Args:
        endpoint_type: 端点类型（auth/upload/query/admin）

    Returns:
        限流字符串（如 "10/minute"）
    """
    return RATE_LIMITS.get(endpoint_type, settings.rate_limit_default)
