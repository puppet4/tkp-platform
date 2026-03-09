"""业务异常定义。

提供统一的业务异常基类，便于异常处理和错误响应。
"""

from typing import Any

from tkp_api.core.error_codes import ErrorCode, get_error_message


class BusinessException(Exception):
    """业务异常基类。

    所有业务逻辑异常应继承此类，便于统一处理。
    """

    def __init__(
        self,
        message: str,
        code: str | ErrorCode | None = None,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
        user_message_zh: str | None = None,
    ):
        """初始化业务异常。

        Args:
            message: 错误消息（技术消息）
            code: 错误代码（支持 ErrorCode 枚举或字符串）
            status_code: HTTP 状态码
            details: 额外的错误详情
            user_message_zh: 用户友好的中文错误消息
        """
        super().__init__(message)
        self.message = message

        # 支持 ErrorCode 枚举
        if isinstance(code, ErrorCode):
            self.code = code.value
            self.user_message_zh = user_message_zh or get_error_message(code)
        else:
            self.code = code or self.__class__.__name__.replace("Exception", "").upper()
            self.user_message_zh = user_message_zh or message

        self.status_code = status_code
        self.details = details or {}


class ValidationException(BusinessException):
    """参数校验异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message,
            code=ErrorCode.VALIDATION_ERROR,
            status_code=422,
            details=details,
        )


class ResourceNotFoundException(BusinessException):
    """资源不存在异常。"""

    def __init__(self, resource_type: str, resource_id: str | None = None):
        message = f"{resource_type} 不存在"
        if resource_id:
            message += f"：{resource_id}"
        super().__init__(
            message,
            code=ErrorCode.RESOURCE_NOT_FOUND,
            status_code=404,
        )


class PermissionDeniedException(BusinessException):
    """权限不足异常。"""

    def __init__(self, message: str = "无权限访问该资源"):
        super().__init__(
            message,
            code=ErrorCode.PERMISSION_DENIED,
            status_code=403,
        )


class ConflictException(BusinessException):
    """资源冲突异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message,
            code=ErrorCode.RESOURCE_CONFLICT,
            status_code=409,
            details=details,
        )


class DocumentValidationException(ValidationException):
    """文档校验异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message, details=details)


class StorageException(BusinessException):
    """存储服务异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message,
            code=ErrorCode.STORAGE_ERROR,
            status_code=500,
            details=details,
        )


class EmbeddingException(BusinessException):
    """向量嵌入服务异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message,
            code=ErrorCode.EMBEDDING_ERROR,
            status_code=500,
            details=details,
        )


class RetrievalException(BusinessException):
    """检索服务异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message,
            code=ErrorCode.RETRIEVAL_ERROR,
            status_code=500,
            details=details,
        )


class QuotaExceededException(BusinessException):
    """配额超限异常。"""

    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(
            message,
            code=ErrorCode.QUOTA_EXCEEDED,
            status_code=429,
            details=details,
        )


class RateLimitException(BusinessException):
    """速率限制异常。"""

    def __init__(self, message: str = "请求过于频繁，请稍后重试", details: dict[str, Any] | None = None):
        super().__init__(
            message,
            code=ErrorCode.RATE_LIMIT_EXCEEDED,
            status_code=429,
            details=details,
        )