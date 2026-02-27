"""工作空间相关请求结构。"""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class WorkspaceCreateRequest(BaseModel):
    """创建工作空间请求体。"""

    name: str = Field(min_length=2, max_length=128, description="工作空间名称。", examples=["智能问答组"])
    slug: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9-]+$",
        description="工作空间在租户内唯一标识。",
        examples=["qa-team"],
    )
    description: str | None = Field(default=None, description="工作空间说明。", examples=["面向客服知识运营"])


class WorkspaceMemberUpsertRequest(BaseModel):
    """工作空间成员新增/更新请求体。"""

    user_id: UUID = Field(description="目标用户 ID。")
    role: Literal["ws_owner", "ws_editor", "ws_viewer"] = Field(
        description="需要授予的工作空间角色。",
        examples=["ws_editor"],
    )


class WorkspaceUpdateRequest(BaseModel):
    """更新工作空间请求体。"""

    name: str | None = Field(default=None, min_length=2, max_length=128, description="新的工作空间名称。")
    slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9-]+$",
        description="新的工作空间短标识（租户内唯一）。",
    )
    description: str | None = Field(default=None, description="新的工作空间说明。")
    status: Literal["active", "archived"] | None = Field(
        default=None,
        description="工作空间状态。",
    )
