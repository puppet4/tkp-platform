"""重排序 Policy Score 服务。

提供基于业务策略的重排序评分：
- 新鲜度评分
- 权威性评分
- 用户偏好评分
- 业务规则评分
"""

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("tkp_api.policy_score")


class PolicyScorer:
    """策略评分器。"""

    def __init__(
        self,
        *,
        recency_weight: float = 0.3,
        authority_weight: float = 0.3,
        preference_weight: float = 0.2,
        business_weight: float = 0.2,
    ):
        """初始化策略评分器。

        Args:
            recency_weight: 新鲜度权重
            authority_weight: 权威性权重
            preference_weight: 用户偏好权重
            business_weight: 业务规则权重
        """
        self.recency_weight = recency_weight
        self.authority_weight = authority_weight
        self.preference_weight = preference_weight
        self.business_weight = business_weight

        # 归一化权重
        total_weight = recency_weight + authority_weight + preference_weight + business_weight
        if total_weight > 0:
            self.recency_weight /= total_weight
            self.authority_weight /= total_weight
            self.preference_weight /= total_weight
            self.business_weight /= total_weight

    def score(
        self,
        chunks: list[dict[str, Any]],
        *,
        user_preferences: dict[str, Any] | None = None,
        business_rules: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """计算策略评分。

        Args:
            chunks: 文档块列表
            user_preferences: 用户偏好
            business_rules: 业务规则

        Returns:
            带有 policy_score 的文档块列表
        """
        if not chunks:
            return []

        for chunk in chunks:
            # 1. 新鲜度评分
            recency_score = self._score_recency(chunk)

            # 2. 权威性评分
            authority_score = self._score_authority(chunk)

            # 3. 用户偏好评分
            preference_score = self._score_preference(chunk, user_preferences)

            # 4. 业务规则评分
            business_score = self._score_business(chunk, business_rules)

            # 5. 综合评分
            policy_score = (
                self.recency_weight * recency_score
                + self.authority_weight * authority_score
                + self.preference_weight * preference_score
                + self.business_weight * business_score
            )

            chunk["policy_score"] = policy_score
            chunk["policy_breakdown"] = {
                "recency": recency_score,
                "authority": authority_score,
                "preference": preference_score,
                "business": business_score,
            }

        logger.debug("policy scores calculated for %d chunks", len(chunks))

        return chunks

    def rerank_with_policy(
        self,
        chunks: list[dict[str, Any]],
        *,
        relevance_weight: float = 0.7,
        policy_weight: float = 0.3,
        user_preferences: dict[str, Any] | None = None,
        business_rules: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """结合相关性和策略评分重排序。

        Args:
            chunks: 文档块列表（需包含 score 字段）
            relevance_weight: 相关性权重
            policy_weight: 策略权重
            user_preferences: 用户偏好
            business_rules: 业务规则

        Returns:
            重排序后的文档块列表
        """
        if not chunks:
            return []

        # 计算策略评分
        chunks = self.score(chunks, user_preferences=user_preferences, business_rules=business_rules)

        # 归一化权重
        total_weight = relevance_weight + policy_weight
        if total_weight > 0:
            relevance_weight /= total_weight
            policy_weight /= total_weight

        # 计算综合评分
        for chunk in chunks:
            relevance_score = chunk.get("score", 0.0)
            policy_score = chunk.get("policy_score", 0.0)

            final_score = relevance_weight * relevance_score + policy_weight * policy_score

            chunk["final_score"] = final_score
            chunk["score_breakdown"] = {
                "relevance": relevance_score,
                "policy": policy_score,
                "relevance_weight": relevance_weight,
                "policy_weight": policy_weight,
            }

        # 按综合评分排序
        chunks.sort(key=lambda x: x.get("final_score", 0.0), reverse=True)

        logger.info(
            "reranked with policy: chunks=%d, relevance_weight=%.2f, policy_weight=%.2f",
            len(chunks),
            relevance_weight,
            policy_weight,
        )

        return chunks

    def _score_recency(self, chunk: dict[str, Any]) -> float:
        """新鲜度评分。

        基于文档创建时间或更新时间。
        """
        # 获取时间戳
        created_at = chunk.get("created_at")
        updated_at = chunk.get("updated_at")

        timestamp = updated_at or created_at
        if not timestamp:
            return 0.5  # 默认中等分数

        try:
            # 解析时间戳
            if isinstance(timestamp, str):
                doc_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            elif isinstance(timestamp, datetime):
                doc_time = timestamp
            else:
                return 0.5

            # 计算时间差（天数）
            now = datetime.now(timezone.utc)
            days_old = (now - doc_time).days

            # 新鲜度衰减函数（指数衰减）
            # 0 天 = 1.0, 30 天 = 0.5, 90 天 = 0.25, 180 天 = 0.1
            if days_old <= 0:
                return 1.0
            elif days_old <= 30:
                return 1.0 - (days_old / 60)
            elif days_old <= 90:
                return 0.5 - ((days_old - 30) / 120)
            elif days_old <= 180:
                return 0.25 - ((days_old - 90) / 360)
            else:
                return 0.1

        except Exception as exc:
            logger.debug("recency scoring failed: %s", exc)
            return 0.5

    def _score_authority(self, chunk: dict[str, Any]) -> float:
        """权威性评分。

        基于文档来源、作者、引用次数等。
        """
        metadata = chunk.get("metadata", {})

        score = 0.5  # 基础分数

        # 1. 文档来源权威性
        source = metadata.get("source", "").lower()
        if "official" in source or "doc" in source:
            score += 0.2
        elif "wiki" in source:
            score += 0.15
        elif "blog" in source:
            score += 0.05

        # 2. 作者权威性
        author = metadata.get("author", "").lower()
        if author and author != "unknown":
            score += 0.1

        # 3. 引用次数
        citations = metadata.get("citations", 0)
        if citations > 10:
            score += 0.2
        elif citations > 5:
            score += 0.1
        elif citations > 0:
            score += 0.05

        # 4. 文档类型
        doc_type = metadata.get("type", "").lower()
        if doc_type in ["manual", "guide", "specification"]:
            score += 0.15
        elif doc_type in ["tutorial", "howto"]:
            score += 0.1

        return min(score, 1.0)

    def _score_preference(self, chunk: dict[str, Any], user_preferences: dict[str, Any] | None) -> float:
        """用户偏好评分。

        基于用户历史行为、偏好设置等。
        """
        if not user_preferences:
            return 0.5

        score = 0.5
        metadata = chunk.get("metadata", {})

        # 1. 偏好的知识库
        preferred_kbs = user_preferences.get("preferred_knowledge_bases", [])
        kb_id = chunk.get("knowledge_base_id")
        if kb_id and str(kb_id) in preferred_kbs:
            score += 0.3

        # 2. 偏好的文档类型
        preferred_types = user_preferences.get("preferred_doc_types", [])
        doc_type = metadata.get("type", "")
        if doc_type in preferred_types:
            score += 0.2

        # 3. 偏好的语言
        preferred_lang = user_preferences.get("preferred_language")
        doc_lang = metadata.get("language")
        if preferred_lang and doc_lang == preferred_lang:
            score += 0.2

        # 4. 历史交互
        interaction_score = user_preferences.get("interaction_scores", {}).get(str(chunk.get("document_id")), 0)
        score += min(interaction_score * 0.1, 0.3)

        return min(score, 1.0)

    def _score_business(self, chunk: dict[str, Any], business_rules: dict[str, Any] | None) -> float:
        """业务规则评分。

        基于业务策略、合规要求等。
        """
        if not business_rules:
            return 0.5

        score = 0.5
        metadata = chunk.get("metadata", {})

        # 1. 优先级标签
        priority_tags = business_rules.get("priority_tags", [])
        chunk_tags = metadata.get("tags", [])
        if any(tag in priority_tags for tag in chunk_tags):
            score += 0.3

        # 2. 降级标签
        downgrade_tags = business_rules.get("downgrade_tags", [])
        if any(tag in downgrade_tags for tag in chunk_tags):
            score -= 0.3

        # 3. 合规状态
        compliance_status = metadata.get("compliance_status")
        if compliance_status == "approved":
            score += 0.2
        elif compliance_status == "pending":
            score -= 0.1
        elif compliance_status == "rejected":
            score -= 0.5

        # 4. 业务分类
        business_category = metadata.get("business_category")
        preferred_categories = business_rules.get("preferred_categories", [])
        if business_category in preferred_categories:
            score += 0.2

        return max(min(score, 1.0), 0.0)
