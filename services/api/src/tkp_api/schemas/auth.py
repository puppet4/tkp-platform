"""登录与登出请求结构。"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from tkp_api.schemas.common import BaseSchema


class AuthRegisterRequest(BaseModel):
    """本地账号注册请求。"""

    email: str = Field(
        min_length=5,
        max_length=256,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="登录邮箱。",
        examples=["alice@example.com"],
    )
    password: str = Field(min_length=8, max_length=128, description="登录密码。", examples=["StrongPassw0rd!"])
    display_name: str | None = Field(default=None, min_length=1, max_length=128, description="展示名。")


class AuthLoginRequest(BaseModel):
    """本地账号登录请求。"""

    email: str = Field(
        min_length=5,
        max_length=256,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
        description="登录邮箱。",
        examples=["alice@example.com"],
    )
    password: str = Field(min_length=8, max_length=128, description="登录密码。", examples=["StrongPassw0rd!"])


class AuthRegisterData(BaseSchema):
    """注册结果结构。"""

    user_id: UUID = Field(description="用户 ID。")
    email: str = Field(description="登录邮箱。")
    display_name: str = Field(description="展示名。")
    auth_provider: str = Field(description="认证来源。")
    personal_tenant_id: UUID = Field(description="个人租户 ID。")
    personal_tenant_slug: str = Field(description="个人租户短标识。")
    personal_tenant_name: str = Field(description="个人租户名称。")
    default_workspace_id: UUID = Field(description="个人租户默认工作空间 ID。")


class AuthLoginData(BaseSchema):
    """登录结果结构。"""

    access_token: str = Field(description="访问令牌。")
    token_type: str = Field(default="bearer", description="令牌类型。")
    expires_at: datetime = Field(description="令牌过期时间（UTC）。")
    expires_in: int = Field(description="距过期剩余秒数。")


class AuthLogoutData(BaseSchema):
    """登出结果结构。"""

    logged_out: bool = Field(description="是否已完成登出。")
    revoked: bool = Field(description="当前 token 是否已加入黑名单。")
