"""真实的向量嵌入服务。

使用 OpenAI Embeddings API 生成语义向量，替换原有的哈希算法。
"""

import hashlib
import json
import logging
import threading
import time
from typing import Any

from cachetools import LRUCache  # type: ignore[import-untyped]
from openai import OpenAI

from tkp_api.core.config import get_settings
from tkp_api.core.exceptions import EmbeddingException

logger = logging.getLogger(__name__)

redis_module: Any | None = None
REDIS_AVAILABLE = False

try:
    import redis as redis_module
    REDIS_AVAILABLE = True
except ImportError:
    redis_module = None


def _normalize_embedding(value: Any) -> list[float] | None:
    """归一化 embedding 数据。"""
    if not isinstance(value, list):
        return None
    normalized: list[float] = []
    for item in value:
        if not isinstance(item, (int, float)):
            return None
        normalized.append(float(item))
    return normalized


class EmbeddingService:
    """向量嵌入服务。

    提供文本向量化功能，支持缓存和批处理。
    线程安全的单例实现。
    """

    def __init__(self):
        """初始化嵌入服务。"""
        self.settings = get_settings()
        self.client = OpenAI(
            api_key=self.settings.resolved_openai_embedding_api_key,
            base_url=self.settings.resolved_openai_embedding_base_url,
            timeout=self.settings.openai_embedding_timeout,
        )
        self.model = self.settings.openai_embedding_model
        self.dimensions = self.settings.openai_embedding_dimensions
        self.cache_enabled = self.settings.retrieval_cache_enabled
        self.cache_ttl = self.settings.retrieval_cache_ttl_seconds
        self.cache_prefix = f"{self.settings.retrieval_cache_prefix}embedding:"

        # 初始化 Redis 缓存（可选）
        self._redis_client: Any | None = None
        if REDIS_AVAILABLE and redis_module is not None and self.settings.redis_url and self.cache_enabled:
            try:
                self._redis_client = redis_module.Redis.from_url(
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
                if isinstance(cached, (str, bytes, bytearray)):
                    parsed = json.loads(cached)
                    normalized = _normalize_embedding(parsed)
                    if normalized is not None:
                        return normalized
            except Exception:
                pass

        # 回退到本地缓存（线程安全）
        with self._cache_lock:
            local_value = self._local_cache.get(cache_key)
            return _normalize_embedding(local_value)

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
            except Exception:
                pass

        # 同时存入本地缓存（线程安全，自动 LRU 淘汰）
        with self._cache_lock:
            self._local_cache[cache_key] = vector

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

        # 调用 OpenAI API（网络异常时最多重试 3 次）
        for attempt in range(3):
            try:
                logger.debug(f"Calling OpenAI embeddings API for text length {len(normalized)}")
                response = self.client.embeddings.create(
                    model=self.model,
                    input=normalized,
                    dimensions=self.dimensions,
                )
                vector = _normalize_embedding(response.data[0].embedding)
                if vector is None:
                    raise EmbeddingException(
                        "向量嵌入失败: embedding payload is invalid",
                        details={"model": self.model, "text_length": len(normalized)},
                    )

                # 存入缓存
                self._set_to_cache(normalized, vector)
                logger.debug(f"Embedding generated and cached for text length {len(normalized)}")
                return vector
            except EmbeddingException:
                raise
            except Exception as exc:
                is_retryable = isinstance(exc, (ConnectionError, TimeoutError))
                is_last_attempt = attempt >= 2
                if is_retryable and not is_last_attempt:
                    time.sleep(min(2 ** attempt, 10))
                    continue
                logger.error(f"Embedding failed: {str(exc)}", exc_info=True)
                raise EmbeddingException(
                    f"向量嵌入失败: {str(exc)}",
                    details={"model": self.model, "text_length": len(normalized)},
                ) from exc
        raise EmbeddingException(
            "向量嵌入失败: retry attempts exhausted",
            details={"model": self.model, "text_length": len(normalized)},
        )

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
                    vector = _normalize_embedding(embedding_data.embedding)
                    if vector is None:
                        raise EmbeddingException(
                            "批量向量嵌入失败: embedding payload is invalid",
                            details={"model": self.model, "batch_size": len(uncached_texts)},
                        )
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
