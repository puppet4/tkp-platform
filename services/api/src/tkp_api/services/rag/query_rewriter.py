"""查询改写服务模块。

支持查询扩展、同义词替换、多查询生成。
"""

import logging
from typing import Any

logger = logging.getLogger("tkp_api.rag.query_rewriter")


class QueryRewriter:
    """查询改写器。"""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        model: str = "gpt-4o-mini",
        strategy: str = "expansion",
    ):
        """初始化查询改写器。

        Args:
            api_key: OpenAI API 密钥
            base_url: OpenAI API 基础 URL（可选）
            model: 使用的模型
            strategy: 改写策略（expansion/multi_query/synonym）
        """
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("Query rewriter requires 'openai' package") from exc

        self.client = OpenAI(api_key=api_key, base_url=base_url if base_url else None)
        self.model = model
        self.strategy = strategy
        logger.info("initialized query rewriter: model=%s, strategy=%s", model, strategy)

    def rewrite(self, query: str) -> dict[str, Any]:
        """改写查询。

        Args:
            query: 原始查询

        Returns:
            包含 original_query、rewritten_queries、strategy 的字典
        """
        if not query.strip():
            return {
                "original_query": query,
                "rewritten_queries": [query],
                "strategy": self.strategy,
                "rewrite_applied": False,
            }

        try:
            if self.strategy == "expansion":
                rewritten = self._expand_query(query)
            elif self.strategy == "multi_query":
                rewritten = self._generate_multi_queries(query)
            elif self.strategy == "synonym":
                rewritten = self._synonym_replacement(query)
            else:
                rewritten = [query]

            return {
                "original_query": query,
                "rewritten_queries": rewritten,
                "strategy": self.strategy,
                "rewrite_applied": len(rewritten) > 1 or rewritten[0] != query,
            }
        except Exception as exc:
            logger.exception("query rewrite failed: %s", exc)
            return {
                "original_query": query,
                "rewritten_queries": [query],
                "strategy": self.strategy,
                "rewrite_applied": False,
            }

    def _expand_query(self, query: str) -> list[str]:
        """查询扩展：添加相关术语和上下文。"""
        prompt = f"""你是一个查询扩展专家。请将以下查询扩展为更详细的版本，添加相关术语和上下文。

原始查询: {query}

要求：
1. 保留原始查询的核心意图
2. 添加相关的同义词和术语
3. 只返回扩展后的查询，不要解释

扩展查询:"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=200,
        )

        expanded = (response.choices[0].message.content or "").strip()
        logger.info("query expansion: '%s' -> '%s'", query, expanded)
        return [expanded]

    def _generate_multi_queries(self, query: str) -> list[str]:
        """生成多个相关查询。"""
        prompt = f"""你是一个查询生成专家。请根据以下查询生成3个不同角度的相关查询。

原始查询: {query}

要求：
1. 每个查询从不同角度探索相同主题
2. 保持查询的相关性
3. 每行一个查询，不要编号

相关查询:"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300,
        )

        content = (response.choices[0].message.content or "").strip()
        queries = [q.strip() for q in content.split("\n") if q.strip()]

        # 确保包含原始查询
        if query not in queries:
            queries.insert(0, query)

        logger.info("multi-query generation: %d queries generated", len(queries))
        return queries[:4]  # 最多返回4个查询

    def _synonym_replacement(self, query: str) -> list[str]:
        """同义词替换。"""
        prompt = f"""你是一个同义词专家。请将以下查询中的关键词替换为同义词，生成2个变体。

原始查询: {query}

要求：
1. 保持查询的核心意图不变
2. 只替换关键词，不改变句子结构
3. 每行一个变体，不要编号

变体查询:"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=200,
        )

        content = (response.choices[0].message.content or "").strip()
        variants = [q.strip() for q in content.split("\n") if q.strip()]

        # 包含原始查询
        if query not in variants:
            variants.insert(0, query)

        logger.info("synonym replacement: %d variants generated", len(variants))
        return variants[:3]  # 最多返回3个变体


def create_query_rewriter(
    *,
    api_key: str,
    base_url: str | None = None,
    model: str = "gpt-4o-mini",
    strategy: str = "expansion",
) -> QueryRewriter:
    """创建查询改写器的工厂函数。"""
    return QueryRewriter(
        api_key=api_key,
        base_url=base_url,
        model=model,
        strategy=strategy,
    )
