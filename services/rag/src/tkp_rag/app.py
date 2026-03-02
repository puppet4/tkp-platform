"""RAG 服务入口。"""

from fastapi import FastAPI

from tkp_rag.api.internal import router as internal_router
from tkp_rag.core.config import get_settings

settings = get_settings()


def create_app() -> FastAPI:
    """创建 RAG FastAPI 应用。"""
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        debug=settings.app_debug,
        description=(
            "检索增强子服务。\n\n"
            "当前对外暴露内部路由 `/internal/*`，供 API 服务转发调用。"
        ),
        openapi_tags=[
            {"name": "health", "description": "服务健康检查。"},
            {"name": "internal-rag", "description": "供 API 服务调用的内部检索/生成接口。"},
        ],
    )

    @app.get(
        "/health/live",
        tags=["health"],
        summary="存活探针",
        description="用于判断 RAG 服务进程是否存活。",
    )
    def live() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(internal_router)
    return app


app = create_app()

