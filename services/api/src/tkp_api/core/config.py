"""应用运行配置。"""

from functools import lru_cache
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
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
    auth_jwt_secret: SecretStr = Field(
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
    rag_base_url: str = Field(default="http://127.0.0.1:8010", description="RAG 服务基础地址。")
    rag_timeout_seconds: float = Field(default=8.0, description="调用 RAG 服务超时时间（秒）。")
    rag_max_retries: int = Field(default=1, description="RAG 服务调用最大重试次数。")
    rag_retry_backoff_seconds: float = Field(default=0.2, description="RAG 调用重试退避秒数。")
    rag_circuit_breaker_fail_threshold: int = Field(default=3, description="RAG 熔断失败阈值。")
    rag_circuit_breaker_open_seconds: int = Field(default=30, description="RAG 熔断打开时长（秒）。")
    internal_service_token: SecretStr = Field(default="change-me-internal-token", description="内部服务间鉴权令牌。")
    agent_allowed_tools: str = Field(
        default="retrieval",
        description="Agent 可用工具白名单，逗号分隔。",
    )

    # OpenAI API 配置（用于内置 RAG 功能）
    openai_api_key: SecretStr = Field(default="", description="OpenAI API 密钥。")
    openai_embedding_model: str = Field(default="text-embedding-3-small", description="OpenAI 嵌入模型。")
    openai_chat_model: str = Field(default="gpt-4o-mini", description="OpenAI 聊天模型。")
    openai_chat_temperature: float = Field(default=0.7, description="LLM 生成温度。")
    openai_chat_max_tokens: int = Field(default=2000, description="LLM 最大生成 token 数。")
    openai_embedding_dimensions: int = Field(default=1536, description="向量维度。")

    # 文本切片配置
    chunk_size: int = Field(default=800, description="文本切片大小。")
    chunk_overlap: int = Field(default=200, description="切片重叠大小。")
    embedding_batch_size: int = Field(default=100, description="向量生成批次大小。")

    # Embedding Gateway 配置
    embedding_provider: str = Field(default="openai", description="Embedding 提供者（openai/cohere/local）。")
    embedding_fallback_provider: str | None = Field(default=None, description="降级 Embedding 提供者。")
    embedding_cache_enabled: bool = Field(default=True, description="是否启用 Embedding 缓存。")
    embedding_cache_ttl: int = Field(default=86400, description="Embedding 缓存过期时间（秒）。")
    embedding_rate_limit_enabled: bool = Field(default=True, description="是否启用速率限制。")
    embedding_rate_limit_max: int = Field(default=1000, description="速率限制：时间窗口内最大请求数。")
    embedding_rate_limit_window: int = Field(default=60, description="速率限制：时间窗口大小（秒）。")
    cohere_api_key: SecretStr = Field(default="", description="Cohere API 密钥。")
    cohere_embedding_model: str = Field(default="embed-multilingual-v3.0", description="Cohere 嵌入模型。")
    local_embedding_model: str = Field(default="sentence-transformers/all-MiniLM-L6-v2", description="本地嵌入模型。")

    # Context Packing 配置
    context_max_tokens: int = Field(default=4000, description="上下文最大 token 数。")
    context_reserve_tokens: int = Field(default=500, description="为生成预留的 token 数。")
    context_similarity_threshold: float = Field(default=0.85, description="去重相似度阈值（0-1）。")
    context_prioritize_by: str = Field(default="score", description="优先级排序字段（score/recency/custom）。")

    # Answer Grading 配置
    answer_grading_enabled: bool = Field(default=True, description="是否启用答案评分。")
    answer_confidence_threshold: float = Field(default=0.5, description="答案置信度阈值，低于此值触发拒答。")
    answer_min_citation_count: int = Field(default=1, description="最小引用数量。")
    answer_enable_llm_grading: bool = Field(default=True, description="是否启用 LLM 评分。")
    answer_grading_model: str = Field(default="gpt-4o-mini", description="用于答案评分的模型。")
    answer_grading_retrieval_weight: float = Field(default=0.4, description="检索质量权重。")
    answer_grading_llm_weight: float = Field(default=0.4, description="LLM 自评权重。")
    answer_grading_citation_weight: float = Field(default=0.2, description="引用覆盖权重。")

    # Parent-Child Chunk 配置
    parent_child_merge_enabled: bool = Field(default=True, description="是否启用父子块合并。")
    parent_child_max_merge_distance: int = Field(default=2, description="相邻块最大合并距离。")

    # 敏感操作确认配置
    sensitive_operation_enabled: bool = Field(default=True, description="是否启用敏感操作双重确认。")
    sensitive_operation_confirmation_ttl: int = Field(default=300, description="确认码有效期（秒）。")
    sensitive_operation_code_length: int = Field(default=6, description="确认码长度。")

    # Query 预处理配置
    query_language_detection_enabled: bool = Field(default=True, description="是否启用查询语言识别。")
    query_spell_correction_enabled: bool = Field(default=True, description="是否启用查询拼写纠错。")
    query_normalization_enabled: bool = Field(default=True, description="是否启用查询规范化。")

    # Policy Score 配置
    policy_score_enabled: bool = Field(default=True, description="是否启用策略评分。")
    policy_recency_weight: float = Field(default=0.3, description="新鲜度权重。")
    policy_authority_weight: float = Field(default=0.3, description="权威性权重。")
    policy_preference_weight: float = Field(default=0.2, description="用户偏好权重。")
    policy_business_weight: float = Field(default=0.2, description="业务规则权重。")
    policy_relevance_weight: float = Field(default=0.7, description="相关性权重（重排序时）。")
    policy_weight: float = Field(default=0.3, description="策略权重（重排序时）。")

    # 检索配置
    retrieval_top_k: int = Field(default=5, description="检索返回的最大结果数。")
    retrieval_similarity_threshold: float = Field(default=0.7, description="检索相似度阈值。")
    retrieval_default_strategy: str = Field(default="hybrid", description="默认检索策略（vector/fulltext/hybrid）。")
    retrieval_vector_weight: float = Field(default=0.5, description="混合检索中向量检索的权重。")
    retrieval_fulltext_weight: float = Field(default=0.5, description="混合检索中全文检索的权重。")
    retrieval_enable_rerank: bool = Field(default=False, description="是否启用重排序。")
    retrieval_enable_query_rewrite: bool = Field(default=False, description="是否启用查询改写。")

    # Elasticsearch 配置（用于全文检索）
    elasticsearch_enabled: bool = Field(default=False, description="是否启用 Elasticsearch。")
    elasticsearch_hosts: str = Field(default="http://localhost:9200", description="Elasticsearch 节点地址，逗号分隔。")
    elasticsearch_api_key: str = Field(default="", description="Elasticsearch API Key。")
    elasticsearch_username: str = Field(default="", description="Elasticsearch 用户名。")
    elasticsearch_password: str = Field(default="", description="Elasticsearch 密码。")
    elasticsearch_index_name: str = Field(default="tkp_chunks", description="Elasticsearch 索引名称。")
    elasticsearch_verify_certs: bool = Field(default=True, description="是否验证 SSL 证书。")

    # 重排序配置
    rerank_provider: str = Field(default="cohere", description="重排序提供商（cohere/jina/cross-encoder）。")
    rerank_api_key: str = Field(default="", description="重排序 API 密钥。")
    rerank_model: str = Field(default="", description="重排序模型名称。")
    rerank_top_n: int = Field(default=5, description="重排序返回的最大结果数。")

    # 查询改写配置
    query_rewrite_strategy: str = Field(default="expansion", description="查询改写策略（expansion/multi_query/synonym）。")

    # 可观测性配置
    observability_enabled: bool = Field(default=False, description="是否启用可观测性功能。")
    observability_service_name: str = Field(default="tkp-api", description="服务名称（用于追踪和指标）。")
    observability_service_version: str = Field(default="1.0.0", description="服务版本。")
    observability_otlp_endpoint: str = Field(default="", description="OTLP 导出端点（如 http://localhost:4317）。")
    observability_enable_traces: bool = Field(default=True, description="是否启用分布式追踪。")
    observability_enable_metrics: bool = Field(default=True, description="是否启用指标收集。")
    observability_enable_logs: bool = Field(default=False, description="是否启用日志导出。")
    observability_log_format: str = Field(default="json", description="日志格式（json/text）。")
    observability_log_level: str = Field(default="INFO", description="日志级别。")

    # 数据治理配置
    governance_enable_rls: bool = Field(default=False, description="是否启用 Row Level Security。")
    governance_enable_pii_detection: bool = Field(default=True, description="是否启用 PII 检测。")
    governance_enable_pii_masking: bool = Field(default=True, description="是否启用 PII 脱敏。")
    governance_deletion_require_approval: bool = Field(default=True, description="数据删除是否需要审批。")
    governance_retention_enabled: bool = Field(default=False, description="是否启用数据保留策略。")

    # Agent 高级功能配置
    agent_enable_sandbox: bool = Field(default=True, description="是否启用 Agent 沙箱。")
    agent_enable_guardrail: bool = Field(default=True, description="是否启用 Agent Guardrail。")
    agent_sandbox_timeout: int = Field(default=30, description="沙箱执行超时时间（秒）。")
    agent_sandbox_max_memory_mb: int = Field(default=512, description="沙箱最大内存限制（MB）。")
    agent_max_iterations: int = Field(default=10, description="Agent 最大迭代次数。")
    agent_rate_limit_per_minute: int = Field(default=60, description="Agent 每分钟最大调用次数。")

    # Kafka 配置
    kafka_enabled: bool = Field(default=False, description="是否启用 Kafka。")
    kafka_bootstrap_servers: str = Field(default="localhost:9092", description="Kafka 服务器地址，逗号分隔。")
    kafka_client_id: str = Field(default="tkp-api", description="Kafka 客户端 ID。")
    kafka_consumer_group_id: str = Field(default="tkp-api-group", description="Kafka 消费者组 ID。")

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
        if not self.auth_jwks_url and len(self.auth_jwt_secret.get_secret_value().encode("utf-8")) < 32:
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
