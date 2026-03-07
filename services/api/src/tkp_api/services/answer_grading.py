"""Answer Grading - 答案置信度评分、低置信度拒答机制。

提供 RAG 答案质量评估功能：
- 置信度评分
- 低置信度拒答
- 答案质量评估
- 引用一致性检查
"""

import logging
import re
from typing import Any

from openai import OpenAI

logger = logging.getLogger("tkp_api.answer_grading")


class AnswerGrader:
    """答案评分器。"""

    def __init__(
        self,
        *,
        openai_client: OpenAI | None = None,
        confidence_threshold: float = 0.5,
        min_citation_count: int = 1,
        enable_llm_grading: bool = True,
    ):
        """初始化答案评分器。

        Args:
            openai_client: OpenAI 客户端（用于 LLM 评分）
            confidence_threshold: 置信度阈值，低于此值触发拒答
            min_citation_count: 最小引用数量
            enable_llm_grading: 是否启用 LLM 评分
        """
        self.openai_client = openai_client
        self.confidence_threshold = confidence_threshold
        self.min_citation_count = min_citation_count
        self.enable_llm_grading = enable_llm_grading

    def grade(
        self,
        *,
        query: str,
        answer: str,
        contexts: list[dict[str, Any]],
        citations: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """评估答案质量。

        Args:
            query: 用户查询
            answer: 生成的答案
            contexts: 检索到的上下文列表
            citations: 引用列表

        Returns:
            评分结果，包含：
            - confidence: 置信度分数（0-1）
            - should_refuse: 是否应该拒答
            - refuse_reason: 拒答原因
            - quality_score: 质量分数（0-1）
            - citation_score: 引用一致性分数（0-1）
            - metrics: 详细指标
        """
        metrics = {}

        # 1. 基础检查
        if not answer or not answer.strip():
            return self._refuse_result("empty_answer", "答案为空")

        if not contexts:
            return self._refuse_result("no_context", "没有检索到相关上下文")

        # 2. 引用检查
        citation_score = self._check_citations(answer, citations or [])
        metrics["citation_score"] = citation_score
        metrics["citation_count"] = len(citations or [])

        if len(citations or []) < self.min_citation_count:
            return self._refuse_result("insufficient_citations", f"引用数量不足（需要至少 {self.min_citation_count} 个）")

        # 3. 答案长度检查
        answer_length = len(answer.strip())
        metrics["answer_length"] = answer_length

        if answer_length < 10:
            return self._refuse_result("answer_too_short", "答案过短")

        # 4. 上下文相关性检查
        relevance_score = self._check_relevance(answer, contexts)
        metrics["relevance_score"] = relevance_score

        # 5. LLM 评分（可选）
        llm_score = None
        if self.enable_llm_grading and self.openai_client:
            try:
                llm_score = self._llm_grade(query, answer, contexts)
                metrics["llm_score"] = llm_score
            except Exception as exc:
                logger.warning("llm grading failed: %s", exc)

        # 6. 计算综合置信度
        confidence = self._calculate_confidence(
            citation_score=citation_score,
            relevance_score=relevance_score,
            llm_score=llm_score,
        )
        metrics["confidence"] = confidence

        # 7. 判断是否拒答
        should_refuse = confidence < self.confidence_threshold
        refuse_reason = None
        if should_refuse:
            refuse_reason = f"置信度过低（{confidence:.2f} < {self.confidence_threshold}）"

        # 8. 计算质量分数
        quality_score = self._calculate_quality_score(
            confidence=confidence,
            citation_score=citation_score,
            relevance_score=relevance_score,
        )

        logger.info(
            "answer grading: confidence=%.2f, quality=%.2f, citations=%d, should_refuse=%s",
            confidence,
            quality_score,
            len(citations or []),
            should_refuse,
        )

        return {
            "confidence": confidence,
            "should_refuse": should_refuse,
            "refuse_reason": refuse_reason,
            "quality_score": quality_score,
            "citation_score": citation_score,
            "metrics": metrics,
        }

    def _refuse_result(self, reason_code: str, reason_message: str) -> dict[str, Any]:
        """生成拒答结果。"""
        return {
            "confidence": 0.0,
            "should_refuse": True,
            "refuse_reason": reason_message,
            "quality_score": 0.0,
            "citation_score": 0.0,
            "metrics": {"refuse_reason_code": reason_code},
        }

    def _check_citations(self, answer: str, citations: list[dict[str, Any]]) -> float:
        """检查引用一致性。

        检查答案中是否包含引用标记，以及引用是否有效。
        """
        if not citations:
            return 0.0

        # 查找答案中的引用标记（如 [1], [2] 等）
        citation_pattern = r"\[(\d+)\]"
        found_citations = set(re.findall(citation_pattern, answer))

        if not found_citations:
            # 答案中没有引用标记
            return 0.3

        # 检查引用是否有效
        valid_citation_ids = {str(i + 1) for i in range(len(citations))}
        valid_found = found_citations & valid_citation_ids

        if not valid_found:
            return 0.2

        # 计算引用覆盖率
        coverage = len(valid_found) / len(citations)
        return min(0.5 + coverage * 0.5, 1.0)

    def _check_relevance(self, answer: str, contexts: list[dict[str, Any]]) -> float:
        """检查答案与上下文的相关性。

        使用简单的词重叠率作为相关性指标。
        """
        if not contexts:
            return 0.0

        # 提取答案中的关键词
        answer_words = set(answer.lower().split())

        # 计算与每个上下文的重叠率
        max_overlap = 0.0
        for context in contexts:
            content = context.get("content", "")
            context_words = set(content.lower().split())

            if not answer_words or not context_words:
                continue

            overlap = len(answer_words & context_words)
            overlap_rate = overlap / len(answer_words)
            max_overlap = max(max_overlap, overlap_rate)

        return min(max_overlap, 1.0)

    def _llm_grade(self, query: str, answer: str, contexts: list[dict[str, Any]]) -> float:
        """使用 LLM 评估答案质量。

        让 LLM 判断答案是否准确、完整、相关。
        """
        if not self.openai_client:
            return 0.5

        # 构建评分 prompt
        context_text = "\n\n".join([f"[{i+1}] {ctx.get('content', '')}" for i, ctx in enumerate(contexts[:3])])

        prompt = f"""请评估以下答案的质量。

用户问题：
{query}

参考上下文：
{context_text}

生成的答案：
{answer}

请从以下维度评分（0-10分）：
1. 准确性：答案是否基于上下文，没有虚构信息
2. 完整性：答案是否充分回答了问题
3. 相关性：答案是否与问题相关

请只返回一个 0-10 的数字，表示综合评分。"""

        try:
            response = self.openai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "你是一个答案质量评估专家。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=10,
            )

            score_text = (response.choices[0].message.content or "").strip()
            score = float(score_text)
            return min(max(score / 10.0, 0.0), 1.0)
        except Exception as exc:
            logger.warning("llm grading failed: %s", exc)
            return 0.5

    def _calculate_confidence(
        self,
        *,
        citation_score: float,
        relevance_score: float,
        llm_score: float | None,
    ) -> float:
        """计算综合置信度。

        综合多个指标计算最终置信度。
        """
        weights = {
            "citation": 0.3,
            "relevance": 0.3,
            "llm": 0.4,
        }

        confidence = (
            citation_score * weights["citation"]
            + relevance_score * weights["relevance"]
        )

        if llm_score is not None:
            confidence += llm_score * weights["llm"]
        else:
            # 如果没有 LLM 评分，重新分配权重
            confidence = (
                citation_score * 0.5
                + relevance_score * 0.5
            )

        return min(max(confidence, 0.0), 1.0)

    def _calculate_quality_score(
        self,
        *,
        confidence: float,
        citation_score: float,
        relevance_score: float,
    ) -> float:
        """计算质量分数。"""
        return (confidence + citation_score + relevance_score) / 3.0


def create_answer_grader(openai_client: OpenAI | None = None) -> AnswerGrader:
    """创建答案评分器实例。"""
    from tkp_api.core.config import get_settings

    settings = get_settings()

    return AnswerGrader(
        openai_client=openai_client,
        confidence_threshold=getattr(settings, "answer_confidence_threshold", 0.5),
        min_citation_count=getattr(settings, "answer_min_citation_count", 1),
        enable_llm_grading=getattr(settings, "answer_enable_llm_grading", True),
    )
