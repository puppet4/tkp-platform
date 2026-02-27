"""应用中间件注册。"""

import uuid

from fastapi import FastAPI, Request


async def request_id_middleware(request: Request, call_next):
    """注入请求追踪 ID，并通过响应头返回。"""
    request.state.request_id = str(uuid.uuid4())
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    return response


def register_middlewares(app: FastAPI) -> None:
    """集中注册中间件。"""
    app.middleware("http")(request_id_middleware)
