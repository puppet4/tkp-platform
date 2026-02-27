"""顶层路由注册。"""

from fastapi import APIRouter

from . import (
    agents,
    auth,
    chat,
    documents,
    health,
    knowledge_bases,
    permissions,
    retrieval,
    tenants,
    users,
    workspaces,
)

api_router = APIRouter()

# 固定注册顺序，便于在线接口文档展示和问题定位。
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(permissions.router)
api_router.include_router(users.router)
api_router.include_router(tenants.router)
api_router.include_router(workspaces.router)
api_router.include_router(knowledge_bases.router)
api_router.include_router(documents.router)
api_router.include_router(retrieval.router)
api_router.include_router(chat.router)
api_router.include_router(agents.router)
