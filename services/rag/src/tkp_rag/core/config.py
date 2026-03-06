"""RAG 服务配置。"""

from functools import lru_cache

from pydantic import Field, model_validator
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

    # OpenAI 配置
    openai_api_key: str = Field(
        default="",
        description="OpenAI API 密钥，用于生成查询向量和LLM回答。",
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI 嵌入模型名称。",
    )
    openai_chat_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI 聊天模型名称。",
    )
    openai_chat_temperature: float = Field(
        default=0.7,
        description="LLM 生成温度参数。",
    )
    openai_chat_max_tokens: int = Field(
        default=2000,
        description="LLM 生成最大 token 数。",
    )

    # 检索配置
    retrieval_top_k: int = Field(
        default=5,
        description="检索返回的最大文档块数量。",
    )
    retrieval_similarity_threshold: float = Field(
        default=0.7,
        description="相似度阈值（0-1），低于此值的结果将被过滤。",
    )

    @model_validator(mode="after")
    def validate_runtime_contract(self) -> "Settings":
        """运行时关键配置校验。"""
        if not self.database_url.strip():
            raise ValueError("KD_DATABASE_URL must not be blank")
        if not self.internal_service_token.strip():
            raise ValueError("KD_INTERNAL_SERVICE_TOKEN must not be blank")
        if not self.openai_api_key or self.openai_api_key.strip() == "":
            raise ValueError("KD_OPENAI_API_KEY is required for RAG service")
        return self


@lru_cache
def get_settings() -> Settings:
    """返回缓存后的配置单例。"""
    return Settings()
