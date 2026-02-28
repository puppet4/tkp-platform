"""应用运行配置。"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """接口服务共享配置。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="KD_", extra="ignore")

    app_name: str = Field(default="Tenant Knowledge Platform", description="应用名称。")
    app_env: str = Field(default="dev", description="运行环境标识。")
    app_debug: bool = Field(default=True, description="是否开启调试模式。")
    api_prefix: str = Field(default="/api", description="统一接口前缀。")
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/tkp_api",
        description="数据库连接地址。",
    )

    auth_jwt_algorithms: str = Field(default="HS256", description="令牌签名算法列表，逗号分隔。")
    auth_jwt_issuer: str | None = Field(default=None, description="期望的签发方。")
    auth_jwt_audience: str | None = Field(default=None, description="期望的受众。")
    auth_jwks_url: str | None = Field(default=None, description="可选密钥集合地址。")
    auth_jwt_secret: str = Field(default="change-me-in-prod", description="未使用密钥集合时的对称密钥。")
    auth_jwt_leeway_seconds: int = Field(default=30, description="令牌校验时钟容错秒数。")
    auth_access_token_ttl_seconds: int = Field(default=7200, description="本地登录签发的访问令牌有效期（秒）。")
    auth_local_issuer: str = Field(default="local", description="本地登录签发时写入的 provider。")
    auth_password_hash_iterations: int = Field(default=390000, description="PBKDF2 密码哈希迭代次数。")
    redis_url: str | None = Field(default=None, description="Redis 连接地址，用于令牌黑名单。")
    auth_token_blacklist_prefix: str = Field(default="auth:blacklist:", description="令牌黑名单键前缀。")
    auth_token_session_prefix: str = Field(default="auth:session:", description="登录会话键前缀。")

    storage_root: str = Field(default="./.storage", description="上传文件落盘根目录。")
    ingestion_default_max_attempts: int = Field(default=5, description="入库任务默认最大重试次数。")
    ingestion_retry_base_seconds: int = Field(default=15, description="重试退避基准秒数。")
    ingestion_retry_max_seconds: int = Field(default=1800, description="重试退避最大秒数。")

    @field_validator("auth_jwt_algorithms")
    @classmethod
    def normalize_algorithms(cls, value: str) -> str:
        """规范化算法列表并确保至少配置一项。"""
        items = [item.strip() for item in value.split(",") if item.strip()]
        if not items:
            raise ValueError("auth_jwt_algorithms must include at least one algorithm")
        return ",".join(items)

    @property
    def auth_algorithms(self) -> list[str]:
        """返回规范化后的算法数组。"""
        return [item.strip() for item in self.auth_jwt_algorithms.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    """返回缓存后的配置单例。"""
    return Settings()
