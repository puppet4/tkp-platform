"""真实的向量嵌入服务。

使用 OpenAI Embeddings API 生成语义向量，替换原有的哈希算法。
"""

import hashlib
import json
import logging
import threading
from typing import Any

from cachetools import LRUCache
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from tkp_api.core.config import get_settings
from tkp_api.core.exceptions import EmbeddingException

logger = logging.getLogger(__name__)

try:
    from redis import Redis
    from redis.exceptions import RedisError

    REDIS_AVAILABLE = True
except ImportError:
    Redis = Any  # type: ignore[assignment]
    RedisError = Exception  # type: ignore[assignment]
    REDIS_AVAILABLE = False


class EmbeddingService:
    """向量嵌入服务。

    提供文本向量化功能，支持缓存和批处理。
    线程安全的单例实现。
    """

    def __init__(self):
        """初始化嵌入服务。"""
        self.settings = get_settings()
        self.client = OpenAI(
            api_key=self.settings.openai_api_key.get_secret_value(),
            base_url=self.settings.openai_api_base if self.settings.openai_api_base else None,
            timeout=self.settings.openai_embedding_timeout,
        )
        self.model = self.settings.openai_embedding_model
        self.dimensions = self.settings.openai_embedding_dimensions
        self.cache_enabled = self.settings.retrieval_cache_enabled
        self.cache_ttl = self.settings.retrieval_cache_ttl_seconds
        self.cache_prefix = f"{self.settings.retrieval_cache_prefix}embedding:"

        # 初始化 Redis 缓存（可选）
        self._redis_client: Redis | None = None
        if REDIS_AVAILABLE and self.settings.redis_url and self.cache_enabled:
            try:
                self._redis_client = Redis.from_url(
                    self.settings.redis_url,
                    decode_responses=False,  # 存储二进制数据
                    socket_connect_timeout=5,
                    socket_timeout=5,
                )
                # 测试连接
                self._redis_client.ping()
            except Exception:
                self._redis_client = None

        # 使用线程安全的 LRU 缓存（回退方案）
        self._local_cache: LRUCache = LRUCache(maxsize=1000)
        self._cache_lock = threading.Lock()

    def _get_cache_key(self, text: str) -> str:
        """生成缓存键。"""
        text_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        return f"{self.cache_prefix}{self.model}:{text_hash}"

    def _get_from_cache(self, text: str) -> list[float] | None:
        """从缓存获取向量。"""
        if not self.cache_enabled:
            return None

        cache_key = self._get_cache_key(text)

        # 尝试 Redis 缓存
        if self._redis_client:
            try:
                cached = self._redis_client.get(cache_key)
                if cached:
                    return json.loads(cached)
            except (RedisError, json.JSONDecodeError):
                pass

        # 回退到本地缓存（线程安全）
        with self._cache_lock:
            return self._local_cache.get(cache_key)

    def _set_to_cache(self, text: str, vector: list[float]) -> None:
        """将向量存入缓存。"""
        if not self.cache_enabled:
            return

        cache_key = self._get_cache_key(text)

        # 尝试 Redis 缓存
        if self._redis_client:
            try:
                self._redis_client.setex(
                    cache_key,
                    self.cache_ttl,
                    json.dumps(vector),
                )
            except RedisError:
                pass

        # 同时存入本地缓存（线程安全，自动 LRU 淘汰）
        with self._cache_lock:
            self._local_cache[cache_key] = vector

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=True,
    )
    def embed_text(self, text: str) -> list[float]:
        """生成单个文本的向量。

        Args:
            text: 待嵌入的文本

        Returns:
            向量列表

        Raises:
            EmbeddingException: 嵌入失败时抛出
        """
        # 标准化文本
        normalized = " ".join(text.strip().split())
        if not normalized:
            # 空文本返回零向量
            return [0.0] * self.dimensions

        # 检查缓存
        cached = self._get_from_cache(normalized)
        if cached is not None:
            logger.debug(f"Embedding cache hit for text length {len(normalized)}")
            return cached

        # 调用 OpenAI API
        try:
            logger.debug(f"Calling OpenAI embeddings API for text length {len(normalized)}")
            response = self.client.embeddings.create(
                model=self.model,
                input=normalized,
                dimensions=self.dimensions,
            )
            vector = response.data[0].embedding

            # 存入缓存
            self._set_to_cache(normalized, vector)
            logger.debug(f"Embedding generated and cached for text length {len(normalized)}")

            return vector

        except Exception as e:
            logger.error(f"Embedding failed: {str(e)}", exc_info=True)
            raise EmbeddingException(
                f"向量嵌入失败: {str(e)}",
                details={"model": self.model, "text_length": len(normalized)},
            ) from e

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量生成文本向量。

        Args:
            texts: 待嵌入的文本列表

        Returns:
            向量列表的列表

        Raises:
            EmbeddingException: 嵌入失败时抛出
        """
        if not texts:
            return []

        # 标准化文本
        normalized_texts = [" ".join(text.strip().split()) for text in texts]

        # 检查缓存
        results: list[list[float] | None] = []
        uncached_indices: list[int] = []
        uncached_texts: list[str] = []

        for i, text in enumerate(normalized_texts):
            if not text:
                results.append([0.0] * self.dimensions)
            else:
                cached = self._get_from_cache(text)
                if cached is not None:
                    results.append(cached)
                else:
                    results.append(None)
                    uncached_indices.append(i)
                    uncached_texts.append(text)

        # 批量调用 API 获取未缓存的向量
        if uncached_texts:
            try:
                response = self.client.embeddings.create(
                    model=self.model,
                    input=uncached_texts,
                    dimensions=self.dimensions,
                )

                for i, embedding_data in enumerate(response.data):
                    vector = embedding_data.embedding
                    original_index = uncached_indices[i]
                    results[original_index] = vector

                    # 存入缓存
                    self._set_to_cache(uncached_texts[i], vector)

            except Exception as e:
                raise EmbeddingException(
                    f"批量向量嵌入失败: {str(e)}",
                    details={"model": self.model, "batch_size": len(uncached_texts)},
                ) from e

        return [r for r in results if r is not None]


# 全局单例（线程安全）
_embedding_service: EmbeddingService | None = None
_embedding_service_lock = threading.Lock()


def get_embedding_service() -> EmbeddingService:
    """获取嵌入服务单例（线程安全）。"""
    global _embedding_service
    if _embedding_service is None:
        with _embedding_service_lock:
            # 双重检查锁定模式
            if _embedding_service is None:
                _embedding_service = EmbeddingService()
    return _embedding_service
