"""文档相关请求结构。"""

from typing import Any

from pydantic import BaseModel, Field


class DocumentUploadMetadata(BaseModel):
    """文档上传元数据参考结构。

    说明：上传接口当前通过 multipart 表单字段传入 JSON 字符串，
    此结构用于 Swagger 联调时的字段说明参考。
    """

    source_lang: str | None = Field(default=None, description="文档主要语言。", examples=["zh"])
    tags: list[str] = Field(default_factory=list, description="文档标签列表。", examples=[["操作手册", "内部"]])


class DocumentUpdateRequest(BaseModel):
    """更新文档请求体。"""

    title: str | None = Field(default=None, min_length=1, max_length=256, description="新的文档标题。")
    metadata: dict[str, Any] | None = Field(default=None, description="新的文档元数据。")
