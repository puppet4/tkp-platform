"""检索请求结构。"""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class RetrievalQueryRequest(BaseModel):
    """检索接口请求体。"""

    query: str = Field(min_length=1, description="用户查询文本。", examples=["退款流程是什么"])
    kb_ids: list[UUID] = Field(default_factory=list, description="可选知识库范围，空表示使用全部可见知识库。")
    top_k: int = Field(default=8, ge=1, le=50, description="返回切片数量上限。", examples=[8])
    filters: dict[str, Any] = Field(default_factory=dict, description="可选元数据过滤条件。")
    with_citations: bool = Field(default=True, description="是否期望返回引用信息。")
