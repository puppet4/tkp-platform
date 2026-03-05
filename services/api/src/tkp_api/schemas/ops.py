"""运维与评测请求结构。"""

from pydantic import BaseModel, Field
from uuid import UUID


class RetrievalEvalSampleRequest(BaseModel):
    """单条检索评测样本。"""

    query: str = Field(min_length=1, description="检索问题。")
    expected_terms: list[str] = Field(default_factory=list, description="预期命中关键字列表。")


class RetrievalEvalRequest(BaseModel):
    """检索评测请求体。"""

    kb_ids: list[UUID] = Field(default_factory=list, description="评测限定知识库范围；为空表示当前用户可读范围。")
    top_k: int = Field(default=5, ge=1, le=20, description="每条样本的检索条数。")
    samples: list[RetrievalEvalSampleRequest] = Field(
        min_length=1,
        max_length=100,
        description="评测样本列表。",
    )
