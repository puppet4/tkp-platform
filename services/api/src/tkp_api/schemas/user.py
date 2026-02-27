"""用户管理相关请求结构。"""

from pydantic import BaseModel, Field


class UserUpdateRequest(BaseModel):
    """更新用户资料请求体。"""

    display_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=128,
        description="新的用户展示名。",
        examples=["Alice Chen"],
    )
    status: str | None = Field(
        default=None,
        min_length=2,
        max_length=32,
        description="用户状态，例如 active/disabled。",
        examples=["active"],
    )
