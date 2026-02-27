"""租户相关请求结构。"""

from typing import Literal

from pydantic import BaseModel, Field


class TenantCreateRequest(BaseModel):
    """创建租户请求体。"""

    name: str = Field(
        min_length=2,
        max_length=128,
        description="租户展示名称。",
        examples=["研发中心"],
    )
    slug: str = Field(
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9-]+$",
        description="租户唯一短标识，只允许小写字母、数字和中划线。",
        examples=["rd-center"],
    )


class TenantMemberUpsertRequest(BaseModel):
    """租户成员新增/更新请求体。"""

    email: str = Field(description="目标用户邮箱。", examples=["alice@example.com"])
    role: Literal["owner", "admin", "member", "viewer"] = Field(
        description="需要授予的租户角色。",
        examples=["member"],
    )


class TenantMemberInviteRequest(BaseModel):
    """租户成员邀请请求体。"""

    email: str = Field(description="被邀请用户邮箱。", examples=["alice@example.com"])
    role: Literal["owner", "admin", "member", "viewer"] = Field(
        description="邀请后加入租户时授予的角色。",
        examples=["member"],
    )


class TenantMemberRoleUpdateRequest(BaseModel):
    """租户成员角色更新请求体。"""

    role: Literal["owner", "admin", "member", "viewer"] = Field(
        description="目标租户角色。",
        examples=["admin"],
    )


class TenantUpdateRequest(BaseModel):
    """更新租户请求体。"""

    name: str | None = Field(
        default=None,
        min_length=2,
        max_length=128,
        description="新的租户展示名称。",
        examples=["平台研发中心"],
    )
    slug: str | None = Field(
        default=None,
        min_length=2,
        max_length=64,
        pattern=r"^[a-z0-9-]+$",
        description="新的租户短标识。",
        examples=["platform-rd"],
    )
    status: Literal["active", "suspended"] | None = Field(
        default=None,
        description="租户状态（不允许通过此接口直接设置 deleted）。",
        examples=["suspended"],
    )
