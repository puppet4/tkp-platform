"""RAG 服务配置。"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """RAG 进程运行配置。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="KD_", extra="ignore")

    app_name: str = Field(default="Tenant Knowledge RAG", description="RAG 服务名称。")
    app_env: str = Field(default="dev", description="运行环境标识。")
    app_debug: bool = Field(default=True, description="是否开启调试模式。")
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/tkp_api",
        description="RAG 访问元数据和向量库的数据库地址。",
    )
    internal_service_token: str = Field(
        default="change-me-internal-token",
        description="服务间内部调用鉴权令牌（API->RAG）。",
    )


@lru_cache
def get_settings() -> Settings:
    """返回缓存后的配置单例。"""
    return Settings()
