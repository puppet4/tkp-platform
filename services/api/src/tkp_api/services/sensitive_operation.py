"""敏感操作双重确认服务。

提供敏感操作的双重确认机制：
- 操作确认请求
- 确认码生成和验证
- 操作审计
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

logger = logging.getLogger("tkp_api.sensitive_operation")


class SensitiveOperationService:
    """敏感操作确认服务。"""

    def __init__(
        self,
        *,
        redis_client=None,
        confirmation_ttl: int = 300,
        code_length: int = 6,
    ):
        """初始化敏感操作确认服务。

        Args:
            redis_client: Redis 客户端（用于存储确认码）
            confirmation_ttl: 确认码有效期（秒），默认 5 分钟
            code_length: 确认码长度
        """
        self.redis = redis_client
        self.confirmation_ttl = confirmation_ttl
        self.code_length = code_length
        self.enabled = redis_client is not None

    def request_confirmation(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        operation_type: str,
        operation_data: dict[str, Any],
        require_code: bool = True,
    ) -> dict[str, Any]:
        """请求操作确认。

        Args:
            tenant_id: 租户 ID
            user_id: 用户 ID
            operation_type: 操作类型（delete_kb/delete_document/revoke_permission等）
            operation_data: 操作数据
            require_code: 是否需要确认码

        Returns:
            确认请求信息，包含 confirmation_id 和 confirmation_code（如果需要）
        """
        if not self.enabled:
            logger.warning("sensitive operation confirmation is disabled (redis not available)")
            return {
                "confirmation_id": None,
                "confirmation_code": None,
                "expires_at": None,
                "require_code": False,
            }

        # 生成确认 ID
        confirmation_id = secrets.token_urlsafe(32)

        # 生成确认码
        confirmation_code = None
        if require_code:
            confirmation_code = self._generate_code()

        # 存储确认请求
        confirmation_data = {
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "operation_type": operation_type,
            "operation_data": operation_data,
            "confirmation_code": confirmation_code,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        try:
            import json
            key = f"sensitive_op:confirmation:{confirmation_id}"
            value = json.dumps(confirmation_data)
            self.redis.setex(key, self.confirmation_ttl, value)

            expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.confirmation_ttl)

            logger.info(
                "confirmation requested: id=%s, type=%s, tenant=%s, user=%s",
                confirmation_id[:8],
                operation_type,
                tenant_id,
                user_id,
            )

            return {
                "confirmation_id": confirmation_id,
                "confirmation_code": confirmation_code,
                "expires_at": expires_at.isoformat(),
                "require_code": require_code,
            }
        except Exception as exc:
            logger.exception("failed to create confirmation request: %s", exc)
            raise

    def verify_confirmation(
        self,
        *,
        confirmation_id: str,
        confirmation_code: str | None = None,
        tenant_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        """验证操作确认。

        Args:
            confirmation_id: 确认 ID
            confirmation_code: 确认码（如果需要）
            tenant_id: 租户 ID
            user_id: 用户 ID

        Returns:
            操作数据

        Raises:
            ValueError: 验证失败
        """
        if not self.enabled:
            raise ValueError("sensitive operation confirmation is disabled")

        try:
            import json
            key = f"sensitive_op:confirmation:{confirmation_id}"
            value = self.redis.get(key)

            if not value:
                raise ValueError("confirmation not found or expired")

            confirmation_data = json.loads(value)

            # 验证租户和用户
            if confirmation_data["tenant_id"] != str(tenant_id):
                raise ValueError("tenant mismatch")

            if confirmation_data["user_id"] != str(user_id):
                raise ValueError("user mismatch")

            # 验证确认码
            stored_code = confirmation_data.get("confirmation_code")
            if stored_code:
                if not confirmation_code:
                    raise ValueError("confirmation code required")
                if confirmation_code != stored_code:
                    raise ValueError("invalid confirmation code")

            # 删除确认请求（一次性使用）
            self.redis.delete(key)

            logger.info(
                "confirmation verified: id=%s, type=%s, tenant=%s, user=%s",
                confirmation_id[:8],
                confirmation_data["operation_type"],
                tenant_id,
                user_id,
            )

            return {
                "operation_type": confirmation_data["operation_type"],
                "operation_data": confirmation_data["operation_data"],
            }

        except Exception as exc:
            logger.warning("confirmation verification failed: %s", exc)
            raise ValueError(f"confirmation verification failed: {exc}") from exc

    def cancel_confirmation(self, *, confirmation_id: str) -> bool:
        """取消确认请求。

        Args:
            confirmation_id: 确认 ID

        Returns:
            是否成功取消
        """
        if not self.enabled:
            return False

        try:
            key = f"sensitive_op:confirmation:{confirmation_id}"
            deleted_raw = self.redis.delete(key)
            deleted = int(deleted_raw) if isinstance(deleted_raw, (int, float)) else 0
            if deleted:
                logger.info("confirmation cancelled: id=%s", confirmation_id[:8])
            return deleted > 0
        except Exception as exc:
            logger.warning("failed to cancel confirmation: %s", exc)
            return False

    def _generate_code(self) -> str:
        """生成确认码。"""
        # 生成数字确认码
        code = "".join(str(secrets.randbelow(10)) for _ in range(self.code_length))
        return code

    def is_sensitive_operation(self, operation_type: str) -> bool:
        """判断是否为敏感操作。

        Args:
            operation_type: 操作类型

        Returns:
            是否为敏感操作
        """
        sensitive_operations = {
            "delete_kb",
            "delete_document",
            "delete_tenant",
            "revoke_admin_permission",
            "change_owner",
            "delete_user",
            "reset_password",
            "disable_tenant",
            "purge_data",
            "export_data",
        }

        return operation_type in sensitive_operations


# 装饰器：要求敏感操作确认
def require_confirmation(operation_type: str):
    """装饰器：要求敏感操作确认。

    使用方式:
    ```python
    @require_confirmation("delete_kb")
    def delete_knowledge_base(kb_id: UUID, confirmation_id: str = None):
        # 函数实现
        pass
    ```
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            confirmation_id = kwargs.get("confirmation_id")
            if not confirmation_id:
                raise ValueError(f"confirmation required for operation: {operation_type}")

            # 验证确认（需要从上下文获取 tenant_id 和 user_id）
            # 这里简化处理，实际使用时需要从请求上下文获取
            logger.info("confirmation required for %s: %s", operation_type, confirmation_id)

            return func(*args, **kwargs)

        return wrapper
    return decorator
