"""Embedding Gateway 工厂函数。"""

import logging
import threading
from functools import lru_cache

from tkp_api.core.config import get_settings
from tkp_api.services.embedding_gateway import (
    CohereEmbeddingProvider,
    EmbeddingCache,
    EmbeddingGateway,
    LocalEmbeddingProvider,
    OpenAIEmbeddingProvider,
    RateLimiter,
)

logger = logging.getLogger("tkp_api.embedding_factory")


def create_embedding_gateway() -> EmbeddingGateway:
    """创建 Embedding Gateway 实例。

    根据配置创建主提供者、降级提供者、缓存和限流器。
    """
    settings = get_settings()

    # 创建 Redis 客户端（用于缓存和限流）
    redis_client = None
    if settings.redis_url:
        try:
            import redis
            redis_client = redis.from_url(settings.redis_url, decode_responses=True)
            logger.info("redis client initialized for embedding gateway")
        except Exception as exc:
            logger.warning("failed to initialize redis client: %s", exc)

    # 创建缓存
    cache = None
    if settings.embedding_cache_enabled:
        cache = EmbeddingCache(redis_client=redis_client, ttl=settings.embedding_cache_ttl)
        logger.info("embedding cache enabled: ttl=%d", settings.embedding_cache_ttl)

    # 创建限流器
    rate_limiter = None
    if settings.embedding_rate_limit_enabled:
        rate_limiter = RateLimiter(
            redis_client=redis_client,
            max_requests=settings.embedding_rate_limit_max,
            window_seconds=settings.embedding_rate_limit_window,
        )
        logger.info(
            "embedding rate limiter enabled: max=%d, window=%d",
            settings.embedding_rate_limit_max,
            settings.embedding_rate_limit_window,
        )

    # 创建主提供者
    primary_provider = _create_provider(settings.embedding_provider, settings)
    logger.info("primary embedding provider: %s", settings.embedding_provider)

    # 创建降级提供者
    fallback_provider = None
    if settings.embedding_fallback_provider:
        try:
            fallback_provider = _create_provider(settings.embedding_fallback_provider, settings)
            logger.info("fallback embedding provider: %s", settings.embedding_fallback_provider)
        except Exception as exc:
            logger.warning("failed to create fallback provider: %s", exc)

    # 创建 Gateway
    gateway = EmbeddingGateway(
        primary_provider=primary_provider,
        fallback_provider=fallback_provider,
        cache=cache,
        rate_limiter=rate_limiter,
    )

    logger.info("embedding gateway initialized")
    return gateway


def _create_provider(provider_type: str, settings):
    """根据类型创建 Embedding 提供者。"""
    if provider_type == "openai":
        api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else ""
        if not api_key:
            raise ValueError("openai_api_key is required for OpenAI provider")
        return OpenAIEmbeddingProvider(
            api_key=api_key,
            model=settings.openai_embedding_model,
            base_url=settings.openai_api_base,
        )
    elif provider_type == "cohere":
        api_key = settings.cohere_api_key.get_secret_value() if settings.cohere_api_key else ""
        if not api_key:
            raise ValueError("cohere_api_key is required for Cohere provider")
        return CohereEmbeddingProvider(
            api_key=api_key,
            model=settings.cohere_embedding_model,
        )
    elif provider_type == "local":
        return LocalEmbeddingProvider(model_name=settings.local_embedding_model)
    else:
        raise ValueError(f"unsupported embedding provider: {provider_type}")


# 线程安全的单例实现
class EmbeddingGatewaySingleton:
    """线程安全的 Embedding Gateway 单例。"""

    _instance: EmbeddingGateway | None = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> EmbeddingGateway:
        """获取 Embedding Gateway 单例实例（线程安全）。"""
        if cls._instance is None:
            with cls._lock:
                # 双重检查锁定
                if cls._instance is None:
                    cls._instance = create_embedding_gateway()
                    logger.info("embedding gateway singleton created")
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例实例（主要用于测试）。"""
        with cls._lock:
            cls._instance = None
            logger.info("embedding gateway singleton reset")


@lru_cache(maxsize=1)
def get_embedding_gateway() -> EmbeddingGateway:
    """获取 Embedding Gateway 实例（使用 lru_cache 确保单例）。

    这个函数使用 @lru_cache 装饰器，确保：
    1. 线程安全
    2. 只创建一次实例
    3. 可以通过 get_embedding_gateway.cache_clear() 清除缓存（用于测试）
    """
    return EmbeddingGatewaySingleton.get_instance()
