"""工作进程配置。"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """工作进程运行参数。"""

    model_config = SettingsConfigDict(env_file=".env", env_prefix="KD_", extra="ignore")

    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/tkp_api",
        description="数据库连接地址。",
    )
    storage_root: str = Field(default="./.storage", description="对象存储根目录。")
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

    worker_id: str = Field(default="tkp-worker-1", description="工作进程唯一标识。")
    worker_poll_interval_seconds: float = Field(default=2.0, description="空闲轮询间隔（秒）。")
    worker_heartbeat_interval_seconds: float = Field(default=10.0, description="任务心跳间隔（秒）。")
    worker_lock_timeout_seconds: int = Field(default=300, description="任务锁超时阈值（秒）。")

    ingestion_retry_base_seconds: int = Field(default=15, description="重试退避基准秒数。")
    ingestion_retry_max_seconds: int = Field(default=1800, description="重试退避最大秒数。")

    # OpenAI 配置
    openai_api_key: str = Field(
        default="",
        description="OpenAI API 密钥，用于生成文本向量。",
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI 嵌入模型名称。",
    )
    openai_embedding_dimensions: int = Field(
        default=1536,
        description="嵌入向量维度。",
    )
    embedding_batch_size: int = Field(
        default=100,
        description="批量生成向量时的批次大小。",
    )

    # 文本切片配置
    chunk_size: int = Field(default=800, description="文本切片大小（字符数）。")
    chunk_overlap: int = Field(default=200, description="切片重叠大小（字符数）。")

    # OCR 配置
    ocr_enabled: bool = Field(default=False, description="是否启用 OCR 文字识别。")
    ocr_engine: str = Field(default="tesseract", description="OCR 引擎（tesseract/paddleocr）。")
    ocr_language: str = Field(default="eng+chi_sim", description="OCR 识别语言。")

    # 图片解析配置
    image_description_enabled: bool = Field(default=False, description="是否启用图片描述生成。")
    image_thumbnail_enabled: bool = Field(default=True, description="是否生成缩略图。")
    image_thumbnail_max_size: int = Field(default=300, description="缩略图最大尺寸（像素）。")

    # 表格提取配置
    table_extraction_enabled: bool = Field(default=False, description="是否启用表格提取。")
    table_extraction_method: str = Field(default="camelot", description="表格提取方法（camelot/tabula）。")

    @model_validator(mode="after")
    def validate_runtime_contract(self) -> "Settings":
        """运行时关键配置校验。"""
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

        if not self.openai_api_key or self.openai_api_key.strip() == "":
            raise ValueError("KD_OPENAI_API_KEY is required for embedding generation")

        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be less than chunk_size")

        return self


@lru_cache
def get_settings() -> Settings:
    """返回缓存后的工作进程配置。"""
    return Settings()
