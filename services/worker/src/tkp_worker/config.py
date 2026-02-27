"""工作进程配置。"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """工作进程运行参数。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="KD_", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/tkp_api",
        description="数据库连接地址。",
    )
    storage_root: str = Field(default="./.storage", description="对象存储根目录。")

    worker_id: str = Field(default="tkp-worker-1", description="工作进程唯一标识。")
    worker_poll_interval_seconds: float = Field(default=2.0, description="空闲轮询间隔（秒）。")
    worker_heartbeat_interval_seconds: float = Field(default=10.0, description="任务心跳间隔（秒）。")
    worker_lock_timeout_seconds: int = Field(default=300, description="任务锁超时阈值（秒）。")

    ingestion_retry_base_seconds: int = Field(default=15, description="重试退避基准秒数。")
    ingestion_retry_max_seconds: int = Field(default=1800, description="重试退避最大秒数。")


@lru_cache
def get_settings() -> Settings:
    """返回缓存后的工作进程配置。"""
    return Settings()
