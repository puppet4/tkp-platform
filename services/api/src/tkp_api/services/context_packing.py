"""Context Packing - Token 预算管理、智能去重、上下文优先级排序。

提供 RAG 上下文打包功能：
- Token 预算管理
- 智能去重（语义相似度）
- 上下文优先级排序
- 截断策略
"""

import hashlib
import logging
from typing import Any

import tiktoken

logger = logging.getLogger("tkp_api.context_packing")


class ContextPacker:
    """上下文打包器。"""

    def __init__(
        self,
        *,
        max_tokens: int = 4000,
        model: str = "gpt-4o-mini",
        similarity_threshold: float = 0.85,
        reserve_tokens: int = 500,
    ):
        """初始化上下文打包器。

        Args:
            max_tokens: 最大 token 预算
            model: 用于 token 计数的模型名称
            similarity_threshold: 去重相似度阈值（0-1）
            reserve_tokens: 为生成预留的 token 数
        """
        self.max_tokens = max_tokens
        self.model = model
        self.similarity_threshold = similarity_threshold
        self.reserve_tokens = reserve_tokens
        self.available_tokens = max_tokens - reserve_tokens

        # 初始化 tokenizer
        try:
            self.encoding = tiktoken.encoding_for_model(model)
        except KeyError:
            logger.warning("model %s not found, using cl100k_base encoding", model)
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        """计算文本的 token 数量。"""
        return len(self.encoding.encode(text))

    def pack(
        self,
        chunks: list[dict[str, Any]],
        *,
        query: str | None = None,
        prioritize_by: str = "score",
    ) -> dict[str, Any]:
        """打包上下文。

        Args:
            chunks: 检索到的文档块列表，每个块包含 content、score 等字段
            query: 查询文本（用于相关性计算）
            prioritize_by: 优先级排序字段（score/recency/custom）

        Returns:
            打包结果，包含：
            - packed_chunks: 打包后的文档块列表
            - total_tokens: 总 token 数
            - dropped_count: 被丢弃的块数量
            - dedup_count: 去重移除的块数量
        """
        if not chunks:
            return {
                "packed_chunks": [],
                "total_tokens": 0,
                "dropped_count": 0,
                "dedup_count": 0,
            }

        # 1. 计算每个块的 token 数
        for chunk in chunks:
            chunk["_token_count"] = self.count_tokens(chunk.get("content", ""))

        # 2. 优先级排序
        sorted_chunks = self._prioritize(chunks, prioritize_by)

        # 3. 智能去重
        deduped_chunks, dedup_count = self._deduplicate(sorted_chunks)

        # 4. Token 预算管理
        packed_chunks, total_tokens, dropped_count = self._fit_budget(deduped_chunks)

        logger.info(
            "context packing: input=%d, deduped=%d, packed=%d, tokens=%d, dropped=%d",
            len(chunks),
            len(deduped_chunks),
            len(packed_chunks),
            total_tokens,
            dropped_count,
        )

        return {
            "packed_chunks": packed_chunks,
            "total_tokens": total_tokens,
            "dropped_count": dropped_count,
            "dedup_count": dedup_count,
        }

    def _prioritize(self, chunks: list[dict[str, Any]], prioritize_by: str) -> list[dict[str, Any]]:
        """优先级排序。"""
        if prioritize_by == "score":
            # 按相关性分数降序
            return sorted(chunks, key=lambda x: x.get("score", 0.0), reverse=True)
        elif prioritize_by == "recency":
            # 按时间戳降序
            return sorted(chunks, key=lambda x: x.get("created_at", ""), reverse=True)
        elif prioritize_by == "custom":
            # 按自定义优先级字段
            return sorted(chunks, key=lambda x: x.get("priority", 0), reverse=True)
        else:
            # 默认保持原顺序
            return chunks

    def _deduplicate(self, chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        """智能去重。

        使用内容哈希和语义相似度进行去重。
        """
        if not chunks:
            return [], 0

        deduped = []
        seen_hashes = set()
        dedup_count = 0

        for chunk in chunks:
            content = chunk.get("content", "")

            # 1. 精确去重（基于内容哈希）
            content_hash = hashlib.md5(content.encode()).hexdigest()
            if content_hash in seen_hashes:
                dedup_count += 1
                logger.debug("exact duplicate removed: hash=%s", content_hash[:8])
                continue

            # 2. 语义去重（基于相似度）
            if self._is_semantically_duplicate(content, deduped):
                dedup_count += 1
                logger.debug("semantic duplicate removed: content_len=%d", len(content))
                continue

            seen_hashes.add(content_hash)
            deduped.append(chunk)

        return deduped, dedup_count

    def _is_semantically_duplicate(self, content: str, existing_chunks: list[dict[str, Any]]) -> bool:
        """检查是否与已有块语义重复。

        使用简单的 Jaccard 相似度（基于词集合）。
        对于更精确的语义相似度，可以使用 embedding 计算余弦相似度。
        """
        if not existing_chunks:
            return False

        # 将内容转换为词集合
        words1 = set(content.lower().split())

        for chunk in existing_chunks:
            existing_content = chunk.get("content", "")
            words2 = set(existing_content.lower().split())

            # 计算 Jaccard 相似度
            if not words1 or not words2:
                continue

            intersection = len(words1 & words2)
            union = len(words1 | words2)
            similarity = intersection / union if union > 0 else 0.0

            if similarity >= self.similarity_threshold:
                return True

        return False

    def _fit_budget(self, chunks: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
        """根据 token 预算选择块。

        Args:
            chunks: 已排序和去重的块列表

        Returns:
            (打包后的块列表, 总 token 数, 被丢弃的块数量)
        """
        packed = []
        total_tokens = 0
        dropped_count = 0

        for chunk in chunks:
            chunk_tokens = chunk.get("_token_count", 0)

            # 检查是否超出预算
            if total_tokens + chunk_tokens > self.available_tokens:
                # 尝试截断
                if self._can_truncate(chunk, total_tokens):
                    truncated_chunk = self._truncate_chunk(chunk, self.available_tokens - total_tokens)
                    packed.append(truncated_chunk)
                    total_tokens += truncated_chunk["_token_count"]
                    logger.debug("chunk truncated: original=%d, truncated=%d", chunk_tokens, truncated_chunk["_token_count"])
                else:
                    dropped_count += 1
                    logger.debug("chunk dropped: tokens=%d, budget_remaining=%d", chunk_tokens, self.available_tokens - total_tokens)
                break

            packed.append(chunk)
            total_tokens += chunk_tokens

        # 如果还有剩余块，全部标记为丢弃
        dropped_count += len(chunks) - len(packed)

        return packed, total_tokens, dropped_count

    def _can_truncate(self, chunk: dict[str, Any], current_tokens: int) -> bool:
        """判断是否可以截断块。

        只有当剩余预算足够容纳至少一半内容时才截断。
        """
        chunk_tokens = chunk.get("_token_count", 0)
        remaining_budget = self.available_tokens - current_tokens
        return remaining_budget >= chunk_tokens * 0.5

    def _truncate_chunk(self, chunk: dict[str, Any], max_tokens: int) -> dict[str, Any]:
        """截断块以适应 token 预算。

        Args:
            chunk: 原始块
            max_tokens: 最大允许的 token 数

        Returns:
            截断后的块
        """
        content = chunk.get("content", "")
        tokens = self.encoding.encode(content)

        if len(tokens) <= max_tokens:
            return chunk

        # 截断 token 并解码
        truncated_tokens = tokens[:max_tokens]
        truncated_content = self.encoding.decode(truncated_tokens)

        # 创建新块
        truncated_chunk = chunk.copy()
        truncated_chunk["content"] = truncated_content + "..."
        truncated_chunk["_token_count"] = max_tokens
        truncated_chunk["_truncated"] = True

        return truncated_chunk

    def estimate_generation_tokens(self, prompt_template: str, context: str) -> int:
        """估算生成所需的 token 数。

        Args:
            prompt_template: Prompt 模板
            context: 上下文内容

        Returns:
            估算的 token 数
        """
        full_prompt = prompt_template.replace("{context}", context)
        return self.count_tokens(full_prompt)


def create_context_packer(
    max_tokens: int = 4000,
    model: str = "gpt-4o-mini",
    similarity_threshold: float = 0.85,
    reserve_tokens: int = 500,
) -> ContextPacker:
    """创建上下文打包器实例。"""
    return ContextPacker(
        max_tokens=max_tokens,
        model=model,
        similarity_threshold=similarity_threshold,
        reserve_tokens=reserve_tokens,
    )
