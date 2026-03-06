"""向量嵌入服务模块。

使用 OpenAI Embeddings API 生成文本向量。
"""

import logging
from typing import Any

logger = logging.getLogger("tkp_api.rag.embeddings")


class EmbeddingService:
    """向量嵌入服务。"""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        dimensions: int = 1536,
        batch_size: int = 100,
    ):
        """初始化嵌入服务。

        Args:
            api_key: OpenAI API 密钥
            model: 嵌入模型名称
            dimensions: 向量维度
            batch_size: 批处理大小
        """
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Embedding service requires 'openai' package") from exc

        self.client = OpenAI(api_key=api_key)
        self.model = model
        self.dimensions = dimensions
        self.batch_size = batch_size
        logger.info("initialized embedding service: model=%s, dimensions=%d", model, dimensions)

    def embed_text(self, text: str) -> list[float]:
        """为单个文本生成向量。

        Args:
            text: 输入文本

        Returns:
            向量列表
        """
        if not text.strip():
            raise ValueError("Cannot embed empty text")

        try:
            response = self.client.embeddings.create(
                input=text,
                model=self.model,
                dimensions=self.dimensions,
            )
            embedding = response.data[0].embedding
            logger.debug("generated embedding: text_len=%d, vector_dim=%d", len(text), len(embedding))
            return embedding
        except Exception as exc:
            logger.exception("failed to generate embedding for text: %s", text[:100])
            raise RuntimeError(f"Embedding generation failed: {exc}") from exc

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """批量生成向量。

        Args:
            texts: 文本列表

        Returns:
            向量列表
        """
        if not texts:
            return []

        # 过滤空文本
        valid_texts = [t for t in texts if t.strip()]
        if not valid_texts:
            raise ValueError("Cannot embed batch with all empty texts")

        try:
            # 分批处理
            all_embeddings: list[list[float]] = []
            for i in range(0, len(valid_texts), self.batch_size):
                batch = valid_texts[i : i + self.batch_size]
                response = self.client.embeddings.create(
                    input=batch,
                    model=self.model,
                    dimensions=self.dimensions,
                )
                batch_embeddings = [item.embedding for item in response.data]
                all_embeddings.extend(batch_embeddings)
                logger.info("generated embeddings: batch=%d/%d, count=%d", i // self.batch_size + 1, (len(valid_texts) + self.batch_size - 1) // self.batch_size, len(batch))

            return all_embeddings
        except Exception as exc:
            logger.exception("failed to generate batch embeddings: batch_size=%d", len(texts))
            raise RuntimeError(f"Batch embedding generation failed: {exc}") from exc

    def count_tokens(self, text: str) -> int:
        """估算文本的 token 数量。

        Args:
            text: 输入文本

        Returns:
            token 数量
        """
        try:
            import tiktoken
        except ImportError:
            # 如果没有 tiktoken，使用简单估算（1 token ≈ 4 字符）
            return len(text) // 4

        try:
            encoding = tiktoken.encoding_for_model(self.model)
            return len(encoding.encode(text))
        except Exception:
            # 回退到默认编码
            encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text))


def create_embedding_service(*, api_key: str, model: str = "text-embedding-3-small") -> EmbeddingService:
    """创建嵌入服务实例的工厂函数。

    Args:
        api_key: OpenAI API 密钥
        model: 嵌入模型名称

    Returns:
        EmbeddingService 实例
    """
    return EmbeddingService(api_key=api_key, model=model)