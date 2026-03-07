"""业务异常定义。

提供统一的业务异常基类，便于异常处理和错误响应。
"""

from typing import Any


class BusinessException(Exception):
    """业务异常基类。

    所有业务逻辑异常应继承此类，便于统一处理。
    """

    def __init__(
        self,
        message: str,
        code: str | None = None,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ):
        """初始化业务异常。

        Args:
            message: 错误消息
            code: 错误代码（默认使用类名）
            status_code: HTTP 状态码
            details: 额外的错误详情
        """
        super().__init__(message)
        self.message = message
        self.code = code or self.__class__.__name__.replace("Exception", "").upper()
        self.status_code = status_code
        self.details = details or {}


class ValidationException(BusinessException):
    """参数校验异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="VALIDATION_ERROR", status_code=422, details=details)


class ResourceNotFoundException(BusinessException):
    """资源不存在异常。"""

    def __init__(self, resource_type: str, resource_id: str | None = None):
        message = f"{resource_type} 不存在"
        if resource_id:
            message += f"：{resource_id}"
        super().__init__(message, code="RESOURCE_NOT_FOUND", status_code=404)


class PermissionDeniedException(BusinessException):
    """权限不足异常。"""

    def __init__(self, message: str = "无权限访问该资源"):
        super().__init__(message, code="PERMISSION_DENIED", status_code=403)


class ConflictException(BusinessException):
    """资源冲突异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="CONFLICT", status_code=409, details=details)


class DocumentValidationException(ValidationException):
    """文档校验异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, details=details)


class StorageException(BusinessException):
    """存储服务异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="STORAGE_ERROR", status_code=500, details=details)


class EmbeddingException(BusinessException):
    """向量嵌入服务异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="EMBEDDING_ERROR", status_code=500, details=details)


class RetrievalException(BusinessException):
    """检索服务异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="RETRIEVAL_ERROR", status_code=500, details=details)


class QuotaExceededException(BusinessException):
    """配额超限异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, code="QUOTA_EXCEEDED", status_code=429, details=details)


class RateLimitException(BusinessException):
    """速率限制异常。"""

    def __init__(self, message: str = "请求过于频繁，请稍后重试", details: dict[str, Any] | None = None):
        super().__init__(message, code="RATE_LIMIT_EXCEEDED", status_code=429, details=details)