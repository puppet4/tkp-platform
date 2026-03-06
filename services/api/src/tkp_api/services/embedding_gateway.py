"""Embedding Gateway - 模型路由、缓存、限流、降级。

提供统一的 Embedding 生成接口，支持：
- 多模型路由（OpenAI、Cohere、本地模型）
- Redis 缓存
- 速率限制
- 降级策略
"""

import hashlib
import logging
import time
from typing import Any

from openai import OpenAI

logger = logging.getLogger("tkp_api.embedding_gateway")


class EmbeddingCache:
    """Embedding 缓存层。"""

    def __init__(self, redis_client=None, ttl: int = 86400):
        """初始化缓存。

        Args:
            redis_client: Redis 客户端
            ttl: 缓存过期时间（秒），默认 24 小时
        """
        self.redis = redis_client
        self.ttl = ttl
        self.enabled = redis_client is not None

    def _make_key(self, text: str, model: str) -> str:
        """生成缓存键。"""
        content = f"{model}:{text}"
        hash_key = hashlib.sha256(content.encode()).hexdigest()
        return f"embedding:{hash_key}"

    def get(self, text: str, model: str) -> list[float] | None:
        """从缓存获取 embedding。"""
        if not self.enabled:
            return None

        try:
            key = self._make_key(text, model)
            cached = self.redis.get(key)
            if cached:
                import json
                logger.debug("embedding cache hit: model=%s, text_len=%d", model, len(text))
                return json.loads(cached)
        except Exception as exc:
            logger.warning("embedding cache get failed: %s", exc)

        return None

    def set(self, text: str, model: str, embedding: list[float]) -> None:
        """将 embedding 存入缓存。"""
        if not self.enabled:
            return

        try:
            import json
            key = self._make_key(text, model)
            value = json.dumps(embedding)
            self.redis.setex(key, self.ttl, value)
            logger.debug("embedding cached: model=%s, text_len=%d", model, len(text))
        except Exception as exc:
            logger.warning("embedding cache set failed: %s", exc)


class RateLimiter:
    """速率限制器。"""

    def __init__(self, redis_client=None, max_requests: int = 100, window_seconds: int = 60):
        """初始化速率限制器。

        Args:
            redis_client: Redis 客户端
            max_requests: 时间窗口内最大请求数
            window_seconds: 时间窗口大小（秒）
        """
        self.redis = redis_client
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.enabled = redis_client is not None

    def check_limit(self, key: str) -> bool:
        """检查是否超过速率限制。

        Args:
            key: 限流键（如 tenant_id）

        Returns:
            True 表示允许请求，False 表示超限
        """
        if not self.enabled:
            return True

        try:
            rate_key = f"rate_limit:embedding:{key}"
            current = self.redis.get(rate_key)

            if current is None:
                # 首次请求
                self.redis.setex(rate_key, self.window_seconds, 1)
                return True

            count = int(current)
            if count >= self.max_requests:
                logger.warning("rate limit exceeded: key=%s, count=%d", key, count)
                return False

            # 增加计数
            self.redis.incr(rate_key)
            return True
        except Exception as exc:
            logger.warning("rate limiter check failed: %s", exc)
            return True  # 失败时允许请求


class EmbeddingProvider:
    """Embedding 提供者基类。"""

    def generate(self, texts: list[str], **kwargs) -> list[list[float]]:
        """生成 embeddings。"""
        raise NotImplementedError


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """OpenAI Embedding 提供者。"""

    def __init__(self, api_key: str, model: str = "text-embedding-3-small"):
        """初始化 OpenAI 提供者。"""
        self.client = OpenAI(api_key=api_key)
        self.model = model

    def generate(self, texts: list[str], **kwargs) -> list[list[float]]:
        """生成 embeddings。"""
        try:
            response = self.client.embeddings.create(
                input=texts,
                model=self.model,
            )
            return [item.embedding for item in response.data]
        except Exception as exc:
            logger.exception("openai embedding failed: %s", exc)
            raise


class CohereEmbeddingProvider(EmbeddingProvider):
    """Cohere Embedding 提供者。"""

    def __init__(self, api_key: str, model: str = "embed-multilingual-v3.0"):
        """初始化 Cohere 提供者。"""
        try:
            import cohere
        except ImportError as exc:
            raise RuntimeError("Cohere provider requires 'cohere' package") from exc

        self.client = cohere.Client(api_key)
        self.model = model

    def generate(self, texts: list[str], **kwargs) -> list[list[float]]:
        """生成 embeddings。"""
        try:
            response = self.client.embed(
                texts=texts,
                model=self.model,
                input_type="search_document",
            )
            return response.embeddings
        except Exception as exc:
            logger.exception("cohere embedding failed: %s", exc)
            raise


class LocalEmbeddingProvider(EmbeddingProvider):
    """本地 Embedding 提供者（sentence-transformers）。"""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        """初始化本地提供者。"""
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("Local provider requires 'sentence-transformers' package") from exc

        self.model = SentenceTransformer(model_name)

    def generate(self, texts: list[str], **kwargs) -> list[list[float]]:
        """生成 embeddings。"""
        try:
            embeddings = self.model.encode(texts, convert_to_numpy=True)
            return embeddings.tolist()
        except Exception as exc:
            logger.exception("local embedding failed: %s", exc)
            raise


class EmbeddingGateway:
    """Embedding Gateway - 统一的 Embedding 生成接口。"""

    def __init__(
        self,
        *,
        primary_provider: EmbeddingProvider,
        fallback_provider: EmbeddingProvider | None = None,
        cache: EmbeddingCache | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        """初始化 Embedding Gateway。

        Args:
            primary_provider: 主要提供者
            fallback_provider: 降级提供者
            cache: 缓存层
            rate_limiter: 速率限制器
        """
        self.primary_provider = primary_provider
        self.fallback_provider = fallback_provider
        self.cache = cache
        self.rate_limiter = rate_limiter

        logger.info(
            "embedding gateway initialized: primary=%s, fallback=%s, cache=%s, rate_limiter=%s",
            type(primary_provider).__name__,
            type(fallback_provider).__name__ if fallback_provider else None,
            cache.enabled if cache else False,
            rate_limiter.enabled if rate_limiter else False,
        )

    def generate(
        self,
        texts: list[str],
        *,
        tenant_id: str | None = None,
        use_cache: bool = True,
    ) -> list[list[float]]:
        """生成 embeddings。

        Args:
            texts: 文本列表
            tenant_id: 租户 ID（用于速率限制）
            use_cache: 是否使用缓存

        Returns:
            Embeddings 列表
        """
        # 速率限制检查
        if self.rate_limiter and tenant_id:
            if not self.rate_limiter.check_limit(tenant_id):
                raise RuntimeError(f"Rate limit exceeded for tenant: {tenant_id}")

        # 尝试从缓存获取
        if use_cache and self.cache:
            cached_embeddings = []
            uncached_texts = []
            uncached_indices = []

            for i, text in enumerate(texts):
                cached = self.cache.get(text, self._get_model_name())
                if cached:
                    cached_embeddings.append((i, cached))
                else:
                    uncached_texts.append(text)
                    uncached_indices.append(i)

            # 如果全部命中缓存
            if not uncached_texts:
                logger.info("all embeddings from cache: count=%d", len(texts))
                return [emb for _, emb in sorted(cached_embeddings)]

            # 生成未缓存的 embeddings
            try:
                new_embeddings = self._generate_with_fallback(uncached_texts)

                # 存入缓存
                for text, embedding in zip(uncached_texts, new_embeddings):
                    self.cache.set(text, self._get_model_name(), embedding)

                # 合并结果
                all_embeddings = cached_embeddings + list(zip(uncached_indices, new_embeddings))
                return [emb for _, emb in sorted(all_embeddings)]
            except Exception as exc:
                logger.exception("embedding generation failed: %s", exc)
                raise
        else:
            # 不使用缓存，直接生成
            return self._generate_with_fallback(texts)

    def _generate_with_fallback(self, texts: list[str]) -> list[list[float]]:
        """使用主要提供者生成，失败时降级。"""
        try:
            start_time = time.time()
            embeddings = self.primary_provider.generate(texts)
            elapsed = time.time() - start_time

            logger.info(
                "embedding generated: provider=%s, count=%d, elapsed=%.2fs",
                type(self.primary_provider).__name__,
                len(texts),
                elapsed,
            )

            return embeddings
        except Exception as exc:
            logger.warning("primary provider failed: %s", exc)

            if self.fallback_provider:
                logger.info("falling back to secondary provider")
                try:
                    start_time = time.time()
                    embeddings = self.fallback_provider.generate(texts)
                    elapsed = time.time() - start_time

                    logger.info(
                        "embedding generated (fallback): provider=%s, count=%d, elapsed=%.2fs",
                        type(self.fallback_provider).__name__,
                        len(texts),
                        elapsed,
                    )

                    return embeddings
                except Exception as fallback_exc:
                    logger.exception("fallback provider also failed: %s", fallback_exc)
                    raise

            raise

    def _get_model_name(self) -> str:
        """获取当前模型名称。"""
        if hasattr(self.primary_provider, "model"):
            return self.primary_provider.model
        return type(self.primary_provider).__name__


def create_embedding_gateway(
    *,
    primary_provider_type: str = "openai",
    primary_api_key: str | None = None,
    primary_model: str | None = None,
    fallback_provider_type: str | None = None,
    fallback_api_key: str | None = None,
    fallback_model: str | None = None,
    redis_client=None,
    cache_ttl: int = 86400,
    rate_limit_max: int = 100,
    rate_limit_window: int = 60,
) -> EmbeddingGateway:
    """创建 Embedding Gateway 的工厂函数。

    Args:
        primary_provider_type: 主要提供者类型（openai/cohere/local）
        primary_api_key: 主要提供者 API 密钥
        primary_model: 主要提供者模型名称
        fallback_provider_type: 降级提供者类型
        fallback_api_key: 降级提供者 API 密钥
        fallback_model: 降级提供者模型名称
        redis_client: Redis 客户端
        cache_ttl: 缓存过期时间
        rate_limit_max: 速率限制最大请求数
        rate_limit_window: 速率限制时间窗口

    Returns:
        EmbeddingGateway 实例
    """
    # 创建主要提供者
    if primary_provider_type == "openai":
        primary_provider = OpenAIEmbeddingProvider(
            api_key=primary_api_key,
            model=primary_model or "text-embedding-3-small",
        )
    elif primary_provider_type == "cohere":
        primary_provider = CohereEmbeddingProvider(
            api_key=primary_api_key,
            model=primary_model or "embed-multilingual-v3.0",
        )
    elif primary_provider_type == "local":
        primary_provider = LocalEmbeddingProvider(
            model_name=primary_model or "sentence-transformers/all-MiniLM-L6-v2",
        )
    else:
        raise ValueError(f"Unsupported provider type: {primary_provider_type}")

    # 创建降级提供者
    fallback_provider = None
    if fallback_provider_type:
        if fallback_provider_type == "openai":
            fallback_provider = OpenAIEmbeddingProvider(
                api_key=fallback_api_key,
                model=fallback_model or "text-embedding-3-small",
            )
        elif fallback_provider_type == "cohere":
            fallback_provider = CohereEmbeddingProvider(
                api_key=fallback_api_key,
                model=fallback_model or "embed-multilingual-v3.0",
            )
        elif fallback_provider_type == "local":
            fallback_provider = LocalEmbeddingProvider(
                model_name=fallback_model or "sentence-transformers/all-MiniLM-L6-v2",
            )

    # 创建缓存层
    cache = EmbeddingCache(redis_client=redis_client, ttl=cache_ttl) if redis_client else None

    # 创建速率限制器
    rate_limiter = (
        RateLimiter(
            redis_client=redis_client,
            max_requests=rate_limit_max,
            window_seconds=rate_limit_window,
        )
        if redis_client
        else None
    )

    return EmbeddingGateway(
        primary_provider=primary_provider,
        fallback_provider=fallback_provider,
        cache=cache,
        rate_limiter=rate_limiter,
    )
