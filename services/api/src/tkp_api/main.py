"""FastAPI 应用入口点。"""

from fastapi import FastAPI

from tkp_api.core.config import get_settings
from tkp_api.core.logging_config import setup_logging
from tkp_api.exceptions import register_exception_handlers
from tkp_api.middlewares import register_middlewares
from tkp_api.api.router import api_router

settings = get_settings()

# 配置日志（在创建应用之前）
setup_logging()


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        debug=settings.app_debug,
        description=(
            "多租户知识平台接口。\n\n"
            "所有业务接口统一返回：`{request_id, data, meta}`。\n"
            "通过访问令牌进行认证。\n"
            "租户上下文：使用访问令牌中的 `tenant_id`。"
        ),
        openapi_tags=[
            {"name": "health", "description": "服务存活与就绪探针。"},
            {"name": "auth", "description": "认证身份辅助接口。"},
            {"name": "permissions-runtime", "description": "运行时权限查询（给前端鉴权使用，无副作用）。"},
            {"name": "permissions-config", "description": "权限配置管理（目录、模板、发布、角色权限维护）。"},
            {"name": "users", "description": "租户内用户查询与管理。"},
            {"name": "tenants", "description": "租户生命周期与租户成员管理。"},
            {"name": "workspaces", "description": "工作空间生命周期与成员管理。"},
            {"name": "knowledge_bases", "description": "知识库与知识库成员管理。"},
            {"name": "documents", "description": "文档上传、版本管理与入库任务查询。"},
            {"name": "ops", "description": "运行态可观测指标与运维辅助接口。"},
            {"name": "feedback", "description": "用户反馈收集与回放分析接口。"},
            {"name": "governance", "description": "数据治理（删除请求、保留策略、PII 脱敏）。"},
            {"name": "metrics", "description": "Prometheus 指标导出接口。"},
            {"name": "retrieval", "description": "授权范围内的检索接口。"},
            {"name": "chat", "description": "带检索引用的问答接口。"},
            {"name": "agent", "description": "智能体运行创建、查询与取消。"},
        ],
    )

    register_middlewares(app)
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)

    # 应用启动：预热连接池
    @app.on_event("startup")
    async def startup_event():
        """应用启动时预热连接池。"""
        import logging
        from sqlalchemy import text
        from tkp_api.db.session import engine

        logger = logging.getLogger(__name__)
        logger.info("Application starting up...")

        # 预热数据库连接池
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connection pool warmed up successfully")
        except Exception as e:
            logger.error(f"Failed to warm up database connection pool: {e}")

        logger.info("Application startup complete")

    # 优雅关闭：清理资源
    @app.on_event("shutdown")
    async def shutdown_event():
        """应用关闭时清理资源。"""
        import logging
        from tkp_api.db.session import engine

        logger = logging.getLogger(__name__)
        logger.info("Application shutting down, cleaning up resources...")

        # 关闭数据库连接池
        engine.dispose()
        logger.info("Database connection pool disposed")

        # 关闭 Redis 连接（如果有）
        try:
            from tkp_api.services.embedding_service import get_embedding_service
            embedding_service = get_embedding_service()
            if embedding_service._redis_client:
                embedding_service._redis_client.close()
                logger.info("Redis connection closed")
        except Exception as e:
            logger.warning(f"Failed to close Redis connection: {e}")

        logger.info("Application shutdown complete")

    return app


app = create_app()
