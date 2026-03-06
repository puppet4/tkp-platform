"""应用运行配置。"""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, field_validator, model_validator
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
    auth_jwt_secret: str = Field(
        default="change-me-in-prod-secret-at-least-32b",
        description="未使用密钥集合时的对称密钥。",
    )
    auth_jwt_leeway_seconds: int = Field(default=30, description="令牌校验时钟容错秒数。")
    auth_access_token_ttl_seconds: int = Field(default=7200, description="本地登录签发的访问令牌有效期（秒）。")
    auth_local_issuer: str = Field(default="local", description="本地登录签发时写入的 provider。")
    auth_password_hash_iterations: int = Field(default=390000, description="PBKDF2 密码哈希迭代次数。")
    redis_url: str | None = Field(default=None, description="Redis 连接地址，用于令牌黑名单。")
    auth_token_blacklist_prefix: str = Field(default="auth:blacklist:", description="令牌黑名单键前缀。")
    auth_token_session_prefix: str = Field(default="auth:session:", description="登录会话键前缀。")

    storage_root: str = Field(default="./.storage", description="上传文件落盘根目录。")
    storage_backend: Literal["local", "minio", "oss"] = Field(
        default="local",
        description="对象存储后端类型（local/minio/oss）。",
    )
    storage_bucket: str = Field(default="tkp-documents", description="对象存储桶名称。")
    storage_key_prefix: str | None = Field(default=None, description="对象键前缀。")
    storage_endpoint: str | None = Field(default=None, description="对象存储服务端点。")
    storage_access_key: str | None = Field(default=None, description="对象存储访问 Key。")
    storage_secret_key: str | None = Field(default=None, description="对象存储访问 Secret。")
    storage_region: str | None = Field(default=None, description="对象存储区域标识（可选）。")
    storage_secure: bool = Field(default=False, description="对象存储连接是否启用 HTTPS。")
    ingestion_default_max_attempts: int = Field(default=5, description="入库任务默认最大重试次数。")
    ingestion_retry_base_seconds: int = Field(default=15, description="重试退避基准秒数。")
    ingestion_retry_max_seconds: int = Field(default=1800, description="重试退避最大秒数。")
    agent_allowed_tools: str = Field(
        default="retrieval",
        description="Agent 可用工具白名单，逗号分隔。",
    )

    # OpenAI API 配置（用于内置 RAG 功能）
    openai_api_key: str = Field(default="", description="OpenAI API 密钥。")
    openai_embedding_model: str = Field(default="text-embedding-3-small", description="OpenAI 嵌入模型。")
    openai_chat_model: str = Field(default="gpt-4o-mini", description="OpenAI 聊天模型。")
    openai_chat_temperature: float = Field(default=0.7, description="LLM 生成温度。")
    openai_chat_max_tokens: int = Field(default=2000, description="LLM 最大生成 token 数。")
    openai_embedding_dimensions: int = Field(default=1536, description="向量维度。")

    # 文本切片配置
    chunk_size: int = Field(default=800, description="文本切片大小。")
    chunk_overlap: int = Field(default=200, description="切片重叠大小。")
    embedding_batch_size: int = Field(default=100, description="向量生成批次大小。")

    # 检索配置
    retrieval_top_k: int = Field(default=5, description="检索返回的最大结果数。")
    retrieval_similarity_threshold: float = Field(default=0.7, description="检索相似度阈值。")

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

    @property
    def agent_allowed_tools_list(self) -> list[str]:
        """返回规范化后的 Agent 工具白名单。"""
        return [item.strip() for item in self.agent_allowed_tools.split(",") if item.strip()]

    @model_validator(mode="after")
    def validate_runtime_contract(self) -> "Settings":
        """运行时关键配置校验（启动前失败，避免带病运行）。"""
        if not self.auth_jwks_url and len(self.auth_jwt_secret.encode("utf-8")) < 32:
            raise ValueError("KD_AUTH_JWT_SECRET must be at least 32 bytes when KD_AUTH_JWKS_URL is unset")

        if self.storage_backend in {"minio", "oss"}:
            missing: list[str] = []
            if not self.storage_endpoint:
                missing.append("KD_STORAGE_ENDPOINT")
            if not self.storage_access_key:
                missing.append("KD_STORAGE_ACCESS_KEY")
            if not self.storage_secret_key:
                missing.append("KD_STORAGE_SECRET_KEY")
            if not self.storage_bucket:
                missing.append("KD_STORAGE_BUCKET")
            if missing:
                raise ValueError(f"storage backend '{self.storage_backend}' requires: {', '.join(missing)}")

        if not self.agent_allowed_tools_list:
            raise ValueError("KD_AGENT_ALLOWED_TOOLS must include at least one tool")
        return self


@lru_cache
def get_settings() -> Settings:
    """返回缓存后的配置单例。"""
    return Settings()
