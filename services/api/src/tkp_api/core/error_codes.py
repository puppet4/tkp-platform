"""统一错误码定义。

错误码格式：E + 类别(1位) + 序号(3位)
- E1xxx: 权限与认证类错误
- E2xxx: 配额与限流类错误
- E3xxx: 参数校验类错误
- E4xxx: 资源状态类错误
- E5xxx: 外部服务类错误
"""

from enum import Enum


class ErrorCode(str, Enum):
    """标准错误码枚举。"""

    # E1xxx: 权限与认证
    UNAUTHORIZED = "E1000"
    PERMISSION_DENIED = "E1001"
    INVALID_CREDENTIALS = "E1002"
    TOKEN_EXPIRED = "E1003"
    TENANT_CONTEXT_REQUIRED = "E1004"

    # E2xxx: 配额与限流
    QUOTA_EXCEEDED = "E2001"
    RATE_LIMIT_EXCEEDED = "E2002"
    STORAGE_QUOTA_EXCEEDED = "E2003"
    DOCUMENT_QUOTA_EXCEEDED = "E2004"

    # E3xxx: 参数校验
    VALIDATION_ERROR = "E3001"
    INVALID_INPUT = "E3002"
    MISSING_REQUIRED_FIELD = "E3003"
    INVALID_FILE_FORMAT = "E3004"
    FILE_TOO_LARGE = "E3005"

    # E4xxx: 资源状态
    RESOURCE_NOT_FOUND = "E4001"
    RESOURCE_CONFLICT = "E4002"
    RESOURCE_ARCHIVED = "E4003"
    RESOURCE_LOCKED = "E4004"
    DUPLICATE_RESOURCE = "E4005"

    # E5xxx: 外部服务
    STORAGE_ERROR = "E5001"
    EMBEDDING_ERROR = "E5002"
    RETRIEVAL_ERROR = "E5003"
    LLM_ERROR = "E5004"
    INTERNAL_ERROR = "E5999"


# 错误码到用户友好消息的映射
ERROR_MESSAGES_ZH: dict[ErrorCode, str] = {
    # 权限与认证
    ErrorCode.UNAUTHORIZED: "未登录或登录状态已失效",
    ErrorCode.PERMISSION_DENIED: "权限不足",
    ErrorCode.INVALID_CREDENTIALS: "用户名或密码错误",
    ErrorCode.TOKEN_EXPIRED: "访问令牌已过期",
    ErrorCode.TENANT_CONTEXT_REQUIRED: "缺少租户上下文",
    # 配额与限流
    ErrorCode.QUOTA_EXCEEDED: "配额已超限",
    ErrorCode.RATE_LIMIT_EXCEEDED: "请求过于频繁，请稍后重试",
    ErrorCode.STORAGE_QUOTA_EXCEEDED: "存储空间已满",
    ErrorCode.DOCUMENT_QUOTA_EXCEEDED: "文档数量已达上限",
    # 参数校验
    ErrorCode.VALIDATION_ERROR: "请求参数校验失败",
    ErrorCode.INVALID_INPUT: "输入参数不合法",
    ErrorCode.MISSING_REQUIRED_FIELD: "缺少必填字段",
    ErrorCode.INVALID_FILE_FORMAT: "文件格式不支持",
    ErrorCode.FILE_TOO_LARGE: "文件大小超过限制",
    # 资源状态
    ErrorCode.RESOURCE_NOT_FOUND: "资源不存在",
    ErrorCode.RESOURCE_CONFLICT: "资源状态冲突",
    ErrorCode.RESOURCE_ARCHIVED: "资源已归档",
    ErrorCode.RESOURCE_LOCKED: "资源已锁定",
    ErrorCode.DUPLICATE_RESOURCE: "资源已存在",
    # 外部服务
    ErrorCode.STORAGE_ERROR: "存储服务异常",
    ErrorCode.EMBEDDING_ERROR: "向量化服务异常",
    ErrorCode.RETRIEVAL_ERROR: "检索服务异常",
    ErrorCode.LLM_ERROR: "大模型服务异常",
    ErrorCode.INTERNAL_ERROR: "系统内部错误",
}


def get_error_message(code: ErrorCode) -> str:
    """获取错误码对应的中文消息。"""
    return ERROR_MESSAGES_ZH.get(code, "未知错误")
