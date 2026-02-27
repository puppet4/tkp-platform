"""全局通用结构。

用于定义统一响应包裹结构，便于在线接口文档展示与联调。
"""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field


class BaseSchema(BaseModel):
    """基础结构，开启对象映射能力。"""

    model_config = ConfigDict(from_attributes=True)


class PaginationMeta(BaseSchema):
    """分页元信息。"""

    page: int = Field(description="当前页码（从 1 开始）。")
    page_size: int = Field(description="每页条数。")
    total: int = Field(description="总记录数。")


class ErrorPayload(BaseSchema):
    """错误主体。"""

    code: str = Field(description="机器可识别错误码。")
    message: str = Field(description="人类可读错误信息。")
    details: dict[str, Any] = Field(default_factory=dict, description="可选扩展错误细节。")


class ErrorResponse(BaseSchema):
    """统一错误响应。"""

    request_id: str = Field(description="服务端生成的请求追踪 ID。")
    error: ErrorPayload = Field(description="错误主体。")


T = TypeVar("T")


class SuccessResponse(BaseSchema, Generic[T]):
    """统一成功响应。"""

    request_id: str = Field(description="服务端生成的请求追踪 ID。")
    data: T = Field(description="业务返回数据主体。")
    meta: dict[str, Any] = Field(default_factory=dict, description="可选扩展元信息。")
