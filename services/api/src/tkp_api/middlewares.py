"""应用中间件注册。"""

from time import perf_counter
import uuid

from fastapi import FastAPI, Request


async def request_id_middleware(request: Request, call_next):
    """注入请求追踪 ID，并通过响应头返回。"""
    request.state.request_id = str(uuid.uuid4())
    request.state.request_started_at = perf_counter()
    response = await call_next(request)
    response.headers["X-Request-Id"] = request.state.request_id
    elapsed = perf_counter() - request.state.request_started_at
    response.headers["X-Process-Time-Ms"] = str(round(elapsed * 1000, 2))
    return response


def register_middlewares(app: FastAPI) -> None:
    """集中注册中间件。"""
    app.middleware("http")(request_id_middleware)
