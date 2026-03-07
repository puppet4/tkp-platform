"""数据库事务管理中间件。

统一管理请求级别的数据库事务，避免在依赖注入和业务逻辑中手动提交/回滚。
"""

import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from tkp_api.core.context import set_request_context, reset_request_context
from tkp_api.db.session import SessionLocal

logger = logging.getLogger(__name__)


class TransactionMiddleware(BaseHTTPMiddleware):
    """数据库事务中间件。

    为每个请求自动管理数据库事务：
    - 请求开始时创建会话并存储到 request.state.db
    - 设置请求上下文（contextvars）
    - 请求成功时自动提交
    - 请求失败时自动回滚
    - 请求结束时关闭会话

    注意：get_db() 依赖注入会从 contextvars 获取此会话。
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """处理请求并管理事务。"""
        # 跳过不需要数据库的路径
        skip_paths = ["/docs", "/openapi.json", "/redoc", "/favicon.ico"]
        if any(request.url.path.startswith(path) for path in skip_paths):
            return await call_next(request)

        # 设置请求上下文（用于 get_db() 访问）
        token = set_request_context(request)

        # 创建数据库会话并存储到 request.state
        db = SessionLocal()
        request.state.db = db

        try:
            # 执行请求处理
            response = await call_next(request)

            # 只有成功的响应才提交事务
            if response.status_code < 400:
                db.commit()
                logger.debug(f"Transaction committed for {request.method} {request.url.path}")
            else:
                db.rollback()
                logger.debug(f"Transaction rolled back for {request.method} {request.url.path} (status={response.status_code})")

            return response

        except Exception as e:
            # 异常时回滚事务
            db.rollback()
            logger.warning(f"Transaction rolled back due to exception: {e}")
            raise

        finally:
            # 确保会话关闭
            db.close()
            # 清理 request.state
            if hasattr(request.state, "db"):
                delattr(request.state, "db")
            # 重置请求上下文
            reset_request_context(token)
