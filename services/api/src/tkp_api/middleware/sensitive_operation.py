"""敏感操作装饰器。

提供 API 端点的敏感操作保护。
"""

import logging
from functools import wraps
from typing import Any, Callable

from fastapi import HTTPException, status

from tkp_api.services.sensitive_operation import SensitiveOperationService

logger = logging.getLogger("tkp_api.sensitive_decorator")


def require_confirmation(
    operation_type: str,
    *,
    require_code: bool = True,
    extract_operation_data: Callable[[Any], dict[str, Any]] | None = None,
):
    """敏感操作确认装饰器。

    用法：
    @require_confirmation("delete_kb", require_code=True)
    def delete_knowledge_base(...):
        ...

    Args:
        operation_type: 操作类型
        require_code: 是否需要确认码
        extract_operation_data: 从请求中提取操作数据的函数
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # 获取请求参数
            request = kwargs.get("request")
            ctx = kwargs.get("ctx")
            payload = kwargs.get("payload")

            if not request or not ctx:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="missing request or context",
                )

            # 检查是否提供了确认信息
            confirmation_id = None
            confirmation_code = None

            # 从 header 或 payload 中获取确认信息
            if payload is not None and hasattr(payload, "confirmation_id"):
                confirmation_id = payload.confirmation_id
                confirmation_code = getattr(payload, "confirmation_code", None)
            else:
                confirmation_id = request.headers.get("X-Confirmation-Id")
                confirmation_code = request.headers.get("X-Confirmation-Code")

            # 提取操作数据
            operation_data = {}
            if extract_operation_data:
                operation_data = extract_operation_data(payload)
            elif payload is not None and hasattr(payload, "dict"):
                operation_data = payload.dict()

            # 如果没有确认信息，返回确认请求
            if not confirmation_id:
                service = SensitiveOperationService(
                    redis_client=_get_redis_client(),
                )

                confirmation_info = service.request_confirmation(
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                    operation_type=operation_type,
                    operation_data=operation_data,
                    require_code=require_code,
                )

                raise HTTPException(
                    status_code=status.HTTP_428_PRECONDITION_REQUIRED,
                    detail={
                        "message": "confirmation required for sensitive operation",
                        "operation_type": operation_type,
                        "confirmation_id": confirmation_info["confirmation_id"],
                        "confirmation_code": confirmation_info["confirmation_code"],
                        "expires_at": confirmation_info["expires_at"],
                        "require_code": confirmation_info["require_code"],
                    },
                )

            # 验证确认信息
            service = SensitiveOperationService(
                redis_client=_get_redis_client(),
            )

            try:
                verified_data = service.verify_confirmation(
                    confirmation_id=confirmation_id,
                    confirmation_code=confirmation_code,
                    tenant_id=ctx.tenant_id,
                    user_id=ctx.user_id,
                )

                # 验证操作类型匹配
                if verified_data["operation_type"] != operation_type:
                    raise ValueError("operation type mismatch")

                logger.info(
                    "sensitive operation confirmed: type=%s, tenant=%s, user=%s",
                    operation_type,
                    ctx.tenant_id,
                    ctx.user_id,
                )

                # 执行原函数
                return await func(*args, **kwargs)

            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"confirmation verification failed: {exc}",
                ) from exc

        return wrapper

    return decorator


def _get_redis_client():
    """获取 Redis 客户端。"""
    from tkp_api.core.config import get_settings

    settings = get_settings()

    if not settings.redis_url:
        return None

    try:
        import redis
        return redis.from_url(settings.redis_url, decode_responses=True)
    except Exception as exc:
        logger.warning("failed to get redis client: %s", exc)
        return None
