"""重排序服务模块。

支持多种重排序策略：Cohere Rerank、Jina Rerank、Cross-Encoder。
"""

import logging
from typing import Any

logger = logging.getLogger("tkp_api.rag.reranker")


class RerankService:
    """重排序服务。"""

    def __init__(
        self,
        *,
        provider: str = "cohere",
        api_key: str,
        model: str | None = None,
        top_n: int = 5,
    ):
        """初始化重排序服务。

        Args:
            provider: 重排序提供商（cohere/jina/cross-encoder）
            api_key: API 密钥
            model: 模型名称（可选）
            top_n: 返回的最大结果数
        """
        self.provider = provider
        self.api_key = api_key
        self.top_n = top_n

        if provider == "cohere":
            self.model = model or "rerank-english-v3.0"
            self._init_cohere()
        elif provider == "jina":
            self.model = model or "jina-reranker-v2-base-multilingual"
            self._init_jina()
        elif provider == "cross-encoder":
            self.model = model or "cross-encoder/ms-marco-MiniLM-L-6-v2"
            self._init_cross_encoder()
        else:
            raise ValueError(f"Unsupported rerank provider: {provider}")

        logger.info("initialized reranker: provider=%s, model=%s", provider, self.model)

    def _init_cohere(self):
        """初始化 Cohere Rerank。"""
        try:
            import cohere
        except ImportError as exc:
            raise RuntimeError("Cohere rerank requires 'cohere' package") from exc

        self.client = cohere.Client(api_key=self.api_key)

    def _init_jina(self):
        """初始化 Jina Rerank。"""
        # Jina 使用 HTTP API，不需要特殊初始化
        self.client = None

    def _init_cross_encoder(self):
        """初始化 Cross-Encoder。"""
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError("Cross-Encoder requires 'sentence-transformers' package") from exc

        self.client = CrossEncoder(self.model)

    def rerank(
        self,
        *,
        query: str,
        documents: list[dict[str, Any]],
        top_n: int | None = None,
    ) -> list[dict[str, Any]]:
        """重排序文档。

        Args:
            query: 查询文本
            documents: 文档列表，每个文档需包含 'content' 字段
            top_n: 返回的最大结果数（可选，默认使用初始化时的值）

        Returns:
            重排序后的文档列表，包含新的 rerank_score
        """
        if not documents:
            return []

        top_n = top_n or self.top_n

        try:
            if self.provider == "cohere":
                return self._rerank_cohere(query, documents, top_n)
            elif self.provider == "jina":
                return self._rerank_jina(query, documents, top_n)
            elif self.provider == "cross-encoder":
                return self._rerank_cross_encoder(query, documents, top_n)
        except Exception as exc:
            logger.exception("rerank failed: %s", exc)
            # 回退：保持原始顺序
            return documents[:top_n]

    def _rerank_cohere(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_n: int,
    ) -> list[dict[str, Any]]:
        """使用 Cohere Rerank。"""
        # 提取文档内容
        doc_texts = [doc.get("content", "") for doc in documents]

        # 调用 Cohere Rerank API
        response = self.client.rerank(
            query=query,
            documents=doc_texts,
            top_n=top_n,
            model=self.model,
        )

        # 重新组装结果
        reranked = []
        for result in response.results:
            idx = result.index
            doc = documents[idx].copy()
            doc["rerank_score"] = result.relevance_score
            doc["original_rank"] = idx
            reranked.append(doc)

        logger.info("cohere rerank: input=%d, output=%d", len(documents), len(reranked))
        return reranked

    def _rerank_jina(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_n: int,
    ) -> list[dict[str, Any]]:
        """使用 Jina Rerank。"""
        import requests

        # 提取文档内容
        doc_texts = [doc.get("content", "") for doc in documents]

        # 调用 Jina Rerank API
        url = "https://api.jina.ai/v1/rerank"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "query": query,
            "documents": doc_texts,
            "top_n": top_n,
        }

        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()

        # 重新组装结果
        reranked = []
        for result in data["results"]:
            idx = result["index"]
            doc = documents[idx].copy()
            doc["rerank_score"] = result["relevance_score"]
            doc["original_rank"] = idx
            reranked.append(doc)

        logger.info("jina rerank: input=%d, output=%d", len(documents), len(reranked))
        return reranked

    def _rerank_cross_encoder(
        self,
        query: str,
        documents: list[dict[str, Any]],
        top_n: int,
    ) -> list[dict[str, Any]]:
        """使用 Cross-Encoder 本地重排序。"""
        # 构建查询-文档对
        doc_texts = [doc.get("content", "") for doc in documents]
        pairs = [[query, text] for text in doc_texts]

        # 计算相关性分数
        scores = self.client.predict(pairs)

        # 按分数排序
        scored_docs = []
        for idx, (doc, score) in enumerate(zip(documents, scores)):
            doc_copy = doc.copy()
            doc_copy["rerank_score"] = float(score)
            doc_copy["original_rank"] = idx
            scored_docs.append(doc_copy)

        # 按 rerank_score 降序排序
        scored_docs.sort(key=lambda x: x["rerank_score"], reverse=True)

        reranked = scored_docs[:top_n]
        logger.info("cross-encoder rerank: input=%d, output=%d", len(documents), len(reranked))
        return reranked


def create_reranker(
    *,
    provider: str = "cohere",
    api_key: str,
    model: str | None = None,
    top_n: int = 5,
) -> RerankService:
    """创建重排序服务的工厂函数。"""
    return RerankService(
        provider=provider,
        api_key=api_key,
        model=model,
        top_n=top_n,
    )
