"""FastAPI 应用入口点。"""

from fastapi import FastAPI

from tkp_api.core.config import get_settings
from tkp_api.exceptions import register_exception_handlers
from tkp_api.middlewares import register_middlewares
from tkp_api.api.router import api_router

settings = get_settings()


def create_app() -> FastAPI:
    """创建并配置 FastAPI 应用实例。"""
    app = FastAPI(
        title=settings.app_name,
        version="1.0.0",
        debug=settings.app_debug,
        description=(
            "多租户知识平台接口。\n\n"
            "所有业务接口统一返回：`{request_id, data, meta}`。\n"
            "认证头：`Authorization: Bearer <访问令牌>`。\n"
            "租户头：`X-Tenant-Id: <tenant_uuid>`。"
        ),
        openapi_tags=[
            {"name": "health", "description": "服务存活与就绪探针。"},
            {"name": "auth", "description": "认证身份辅助接口。"},
            {"name": "permissions", "description": "租户角色权限点配置与查询。"},
            {"name": "users", "description": "租户内用户查询与管理。"},
            {"name": "tenants", "description": "租户生命周期与租户成员管理。"},
            {"name": "workspaces", "description": "工作空间生命周期与成员管理。"},
            {"name": "knowledge_bases", "description": "知识库与知识库成员管理。"},
            {"name": "documents", "description": "文档上传、版本管理与入库任务查询。"},
            {"name": "retrieval", "description": "授权范围内的检索接口。"},
            {"name": "chat", "description": "带检索引用的问答接口。"},
            {"name": "agent", "description": "智能体运行创建、查询与取消。"},
        ],
    )

    register_middlewares(app)
    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
