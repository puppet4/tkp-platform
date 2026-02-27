"""RAG 服务入口。"""

from fastapi import FastAPI

app = FastAPI(
    title="检索增强服务",
    description="RAG 子服务健康检查与后续检索能力扩展入口。",
)


@app.get(
    "/health/live",
    summary="存活探针",
    description="用于判断 RAG 服务进程是否存活。",
)
def live() -> dict[str, str]:
    """返回固定存活状态。"""
    return {"status": "ok"}
