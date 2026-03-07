"""答案评分服务。

提供多信号置信度评分：
- 检索质量评分（相似度、数量、方差）
- LLM 自评分（从生成的回答中提取置信度）
- 引用覆盖评分（答案是否引用了检索到的内容）
"""

import logging
import re
from typing import Any

logger = logging.getLogger("tkp_api.answer_grader")


class AnswerGrader:
    """答案评分器。"""

    def __init__(
        self,
        *,
        threshold: float = 0.5,
        retrieval_weight: float = 0.4,
        llm_weight: float = 0.4,
        citation_weight: float = 0.2,
    ):
        """初始化答案评分器。

        Args:
            threshold: 置信度阈值，低于此值触发拒答
            retrieval_weight: 检索质量权重
            llm_weight: LLM 自评权重
            citation_weight: 引用覆盖权重
        """
        self.threshold = threshold
        self.retrieval_weight = retrieval_weight
        self.llm_weight = llm_weight
        self.citation_weight = citation_weight

        # 权重归一化
        total_weight = retrieval_weight + llm_weight + citation_weight
        self.retrieval_weight /= total_weight
        self.llm_weight /= total_weight
        self.citation_weight /= total_weight

        logger.info(
            "initialized answer grader: threshold=%.2f, weights=(retrieval=%.2f, llm=%.2f, citation=%.2f)",
            threshold,
            self.retrieval_weight,
            self.llm_weight,
            self.citation_weight,
        )

    def calculate_confidence(
        self,
        *,
        query: str,
        answer: str,
        chunks: list[dict[str, Any]],
        llm_confidence: float | None = None,
    ) -> dict[str, Any]:
        """计算答案置信度。

        Args:
            query: 用户查询
            answer: 生成的答案
            chunks: 检索到的文档块
            llm_confidence: LLM 自评置信度（0-1）

        Returns:
            评分结果，包含：
            - confidence_score: 总体置信度（0-1）
            - retrieval_score: 检索质量分数
            - llm_score: LLM 自评分数
            - citation_score: 引用覆盖分数
            - rejected: 是否拒答
            - rejection_reason: 拒答原因
            - suggestions: 改进建议
        """
        # 计算各项分数
        retrieval_score = self._calculate_retrieval_quality(chunks)
        llm_score = llm_confidence if llm_confidence is not None else 0.5
        citation_score = self._calculate_citation_coverage(answer, chunks)

        # 加权计算总分
        confidence_score = (
            retrieval_score * self.retrieval_weight
            + llm_score * self.llm_weight
            + citation_score * self.citation_weight
        )

        # 判断是否拒答
        rejected = confidence_score < self.threshold

        # 生成拒答原因和建议
        rejection_reason = None
        suggestions = []

        if rejected:
            reasons = []
            if retrieval_score < 0.5:
                reasons.append("检索到的相关文档质量较低")
                suggestions.append("尝试使用更具体的关键词重新提问")
            if llm_score < 0.5:
                reasons.append("模型对答案的置信度不足")
                suggestions.append("问题可能过于模糊或超出知识库范围")
            if citation_score < 0.3:
                reasons.append("答案缺乏足够的文档支持")
                suggestions.append("尝试提供更多上下文信息")

            rejection_reason = "、".join(reasons) if reasons else "置信度不足"

        logger.info(
            "confidence calculated: total=%.2f, retrieval=%.2f, llm=%.2f, citation=%.2f, rejected=%s",
            confidence_score,
            retrieval_score,
            llm_score,
            citation_score,
            rejected,
        )

        return {
            "confidence_score": confidence_score,
            "retrieval_score": retrieval_score,
            "llm_score": llm_score,
            "citation_score": citation_score,
            "rejected": rejected,
            "rejection_reason": rejection_reason,
            "rejection_message": self._generate_rejection_message(rejection_reason) if rejected else None,
            "suggestions": suggestions,
        }

    def _calculate_retrieval_quality(self, chunks: list[dict[str, Any]]) -> float:
        """计算检索质量分数。

        考虑因素：
        - 平均相似度
        - 检索到的文档数量
        - 相似度方差（一致性）

        Args:
            chunks: 检索到的文档块

        Returns:
            检索质量分数（0-1）
        """
        if not chunks:
            return 0.0

        # 提取相似度分数
        similarities: list[float] = []
        for chunk in chunks:
            raw_similarity = chunk.get("similarity", 0.0)
            if isinstance(raw_similarity, (int, float)):
                similarities.append(float(raw_similarity))
            else:
                similarities.append(0.0)

        # 平均相似度（权重 60%）
        avg_similarity = sum(similarities) / len(similarities)

        # 数量分数（权重 20%）- 至少 3 个文档才算好
        count_score = min(len(chunks) / 3.0, 1.0)

        # 一致性分数（权重 20%）- 方差越小越好
        if len(similarities) > 1:
            mean = avg_similarity
            variance = sum((s - mean) ** 2 for s in similarities) / len(similarities)
            consistency_score = max(0.0, 1.0 - variance * 2)
        else:
            consistency_score = 1.0

        quality_score = avg_similarity * 0.6 + count_score * 0.2 + consistency_score * 0.2

        return float(min(quality_score, 1.0))

    def _calculate_citation_coverage(self, answer: str, chunks: list[dict[str, Any]]) -> float:
        """计算引用覆盖分数。

        检查答案是否引用了检索到的文档内容。

        Args:
            answer: 生成的答案
            chunks: 检索到的文档块

        Returns:
            引用覆盖分数（0-1）
        """
        if not chunks or not answer:
            return 0.0

        # 提取答案中的关键短语（3-5 个词）
        answer_lower = answer.lower()
        answer_words = re.findall(r'\w+', answer_lower)

        if len(answer_words) < 3:
            return 0.0

        # 检查有多少个文档块的内容在答案中被引用
        cited_chunks = 0
        for chunk in chunks:
            content = chunk.get("content", "").lower()
            content_words = re.findall(r'\w+', content)

            # 检查是否有连续的 3 个词匹配
            for i in range(len(answer_words) - 2):
                phrase = " ".join(answer_words[i:i+3])
                if phrase in " ".join(content_words):
                    cited_chunks += 1
                    break

        # 计算覆盖率
        coverage = cited_chunks / len(chunks)

        return min(coverage, 1.0)

    def _generate_rejection_message(self, reason: str | None) -> str:
        """生成拒答消息。

        Args:
            reason: 拒答原因

        Returns:
            用户友好的拒答消息
        """
        base_message = "抱歉，我对这个问题的回答置信度不足。"

        if reason:
            return f"{base_message}原因：{reason}。"

        return base_message


def create_answer_grader() -> AnswerGrader:
    """创建答案评分器实例。"""
    from tkp_api.core.config import get_settings

    settings = get_settings()

    return AnswerGrader(
        threshold=settings.answer_confidence_threshold,
        retrieval_weight=settings.answer_grading_retrieval_weight,
        llm_weight=settings.answer_grading_llm_weight,
        citation_weight=settings.answer_grading_citation_weight,
    )
