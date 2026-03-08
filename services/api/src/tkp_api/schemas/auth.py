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


class AuthMFALoginRequest(BaseModel):
    """MFA 二阶段登录请求。"""

    challenge_token: str = Field(min_length=32, description="登录第一阶段返回的挑战令牌。")
    otp_code: str | None = Field(default=None, min_length=6, max_length=6, description="6 位 TOTP 动态码。")
    backup_code: str | None = Field(default=None, min_length=6, max_length=32, description="恢复码。")


class AuthSwitchTenantRequest(BaseModel):
    """切换租户请求。"""

    tenant_id: UUID = Field(description="目标租户 ID。")


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
    tenant_id: UUID | None = Field(default=None, description="当前访问令牌绑定的租户 ID。")


class AuthLogoutData(BaseSchema):
    """登出结果结构。"""

    logged_out: bool = Field(description="是否已完成登出。")
    revoked: bool = Field(description="当前 token 是否已加入黑名单。")


class AuthMFATotpSetupRequest(BaseModel):
    """发起 TOTP 设置请求。"""

    password: str = Field(min_length=8, max_length=128, description="当前登录密码。")


class AuthMFATotpEnableRequest(BaseModel):
    """启用 TOTP 请求。"""

    code: str = Field(min_length=6, max_length=6, description="验证器中的 6 位动态码。")


class AuthMFATotpDisableRequest(BaseModel):
    """停用 TOTP 请求。"""

    password: str = Field(min_length=8, max_length=128, description="当前登录密码。")
    otp_code: str | None = Field(default=None, min_length=6, max_length=6, description="6 位动态码。")
    backup_code: str | None = Field(default=None, min_length=6, max_length=32, description="恢复码。")


class AuthMFATotpSetupData(BaseSchema):
    """TOTP 设置返回结构。"""

    enrolled: bool = Field(description="是否已完成密钥下发。")
    enabled: bool = Field(description="是否已启用。")
    secret: str = Field(description="Base32 TOTP 密钥。")
    otpauth_uri: str = Field(description="Authenticator 可识别的 otpauth URI。")


class AuthMFATotpStatusData(BaseSchema):
    """TOTP 状态结构。"""

    enrolled: bool = Field(description="是否存在 TOTP 配置。")
    enabled: bool = Field(description="是否启用。")
    backup_codes_remaining: int = Field(description="剩余可用恢复码数量。")


class AuthMFATotpEnableData(BaseSchema):
    """TOTP 启用结果。"""

    enabled: bool = Field(description="是否已启用。")
    backup_codes: list[str] = Field(description="一次性恢复码（仅首次返回）。")


class AuthMFATotpDisableData(BaseSchema):
    """TOTP 停用结果。"""

    enabled: bool = Field(description="是否已启用。")
