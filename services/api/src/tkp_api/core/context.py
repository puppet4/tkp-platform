"""请求上下文管理。

使用 contextvars 在异步环境中传递请求上下文。
"""

from contextvars import ContextVar
from typing import Any

from starlette.requests import Request

# 请求上下文变量（线程安全、协程安全）
_request_context: ContextVar[Request | None] = ContextVar("request_context", default=None)


def set_request_context(request: Request) -> Any:
    """设置当前请求上下文。

    Args:
        request: FastAPI/Starlette Request 对象

    Returns:
        Token，用于后续重置上下文
    """
    return _request_context.set(request)


def get_request_context() -> Request | None:
    """获取当前请求上下文。

    Returns:
        当前请求对象，如果不在请求上下文中则返回 None
    """
    return _request_context.get()


def reset_request_context(token: Any) -> None:
    """重置请求上下文。

    Args:
        token: set_request_context() 返回的 token
    """
    _request_context.reset(token)
