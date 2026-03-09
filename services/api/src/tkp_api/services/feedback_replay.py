"""反馈回放服务。

提供线上用户反馈收集和回放功能：
- 收集用户反馈
- 快照保存
- 反馈回放
- 对比分析
"""

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.models.conversation import Conversation, Message
from tkp_api.models.feedback import FeedbackReplay, UserFeedback
from tkp_api.models.knowledge import RetrievalLog

logger = logging.getLogger("tkp_api.feedback_replay")


class FeedbackReplayService:
    """反馈回放服务。"""

    def __init__(self, *, retriever=None, llm_generator=None):
        """初始化反馈回放服务。

        Args:
            retriever: 检索器（用于回放检索）
            llm_generator: LLM 生成器（用于回放生成）
        """
        self.retriever = retriever
        self.llm_generator = llm_generator

    def collect_feedback(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        user_id: UUID,
        feedback_type: str,
        feedback_value: str | None = None,
        comment: str | None = None,
        tags: list[str] | None = None,
        conversation_id: UUID | None = None,
        message_id: UUID | None = None,
        retrieval_log_id: UUID | None = None,
    ) -> UserFeedback:
        """收集用户反馈。

        Args:
            db: 数据库会话
            tenant_id: 租户 ID
            user_id: 用户 ID
            feedback_type: 反馈类型（thumbs_up/thumbs_down/rating/comment）
            feedback_value: 反馈值
            comment: 评论
            tags: 标签
            conversation_id: 会话 ID
            message_id: 消息 ID
            retrieval_log_id: 检索日志 ID

        Returns:
            用户反馈对象
        """
        # 创建快照
        snapshot = self._create_snapshot(
            db,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            message_id=message_id,
            retrieval_log_id=retrieval_log_id,
        )

        # 创建反馈记录
        feedback = UserFeedback(
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=message_id,
            retrieval_log_id=retrieval_log_id,
            feedback_type=feedback_type,
            feedback_value=feedback_value,
            comment=comment,
            tags=tags,
            snapshot=snapshot,
            processed=False,
        )

        db.add(feedback)
        db.commit()
        db.refresh(feedback)

        logger.info(
            "feedback collected: id=%s, type=%s, tenant=%s",
            feedback.id,
            feedback_type,
            tenant_id,
        )

        return feedback

    def replay_feedback(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        feedback_id: UUID,
        replay_type: str = "full_pipeline",
    ) -> FeedbackReplay:
        """回放反馈。

        Args:
            db: 数据库会话
            feedback_id: 反馈 ID
            replay_type: 回放类型（retrieval/generation/full_pipeline）

        Returns:
            回放记录
        """
        # 获取反馈
        stmt = select(UserFeedback).where(
            UserFeedback.id == feedback_id,
            UserFeedback.tenant_id == tenant_id,
        )
        result = db.execute(stmt)
        feedback = result.scalar_one_or_none()

        if not feedback:
            raise ValueError(f"feedback not found: {feedback_id}")

        # 创建回放记录
        replay = FeedbackReplay(
            tenant_id=feedback.tenant_id,
            feedback_id=feedback_id,
            replay_type=replay_type,
            status="running",
            original_result=feedback.snapshot,
        )

        db.add(replay)
        db.commit()
        db.refresh(replay)

        try:
            # 执行回放
            if replay_type == "retrieval":
                replay_result = self._replay_retrieval(db, feedback)
            elif replay_type == "generation":
                replay_result = self._replay_generation(db, feedback)
            elif replay_type == "full_pipeline":
                replay_result = self._replay_full_pipeline(db, feedback)
            else:
                raise ValueError(f"unsupported replay type: {replay_type}")

            # 对比分析
            comparison = self._compare_results(feedback.snapshot, replay_result)

            # 生成改进建议
            suggestions = self._generate_suggestions(feedback, comparison)

            # 更新回放记录
            replay.status = "completed"
            replay.replay_result = replay_result
            replay.comparison = comparison
            replay.suggestions = suggestions
            replay.completed_at = datetime.now(timezone.utc)

            # 标记反馈已处理
            feedback.processed = True
            feedback.processed_at = datetime.now(timezone.utc)
            feedback.processing_result = {
                "replay_id": str(replay.id),
                "comparison": comparison,
                "suggestions": suggestions,
            }

            db.commit()
            db.refresh(replay)

            logger.info("feedback replayed: feedback_id=%s, replay_id=%s", feedback_id, replay.id)

            return replay

        except Exception as exc:
            logger.exception("feedback replay failed: %s", exc)
            replay.status = "failed"
            replay.error_message = str(exc)
            replay.completed_at = datetime.now(timezone.utc)
            db.commit()
            raise

    def _create_snapshot(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        conversation_id: UUID | None,
        message_id: UUID | None,
        retrieval_log_id: UUID | None,
    ) -> dict[str, Any]:
        """创建快照。"""
        snapshot: dict[str, Any] = {}

        # 校验会话归属（如果提供）。
        if conversation_id:
            conversation_stmt = select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant_id,
            )
            conversation = db.execute(conversation_stmt).scalar_one_or_none()
            if not conversation:
                raise ValueError(f"conversation not found: {conversation_id}")

        # 保存消息快照
        if message_id:
            message_stmt = select(Message).where(
                Message.id == message_id,
                Message.tenant_id == tenant_id,
            )
            message_result = db.execute(message_stmt)
            message = message_result.scalar_one_or_none()
            if not message:
                raise ValueError(f"message not found: {message_id}")
            snapshot["message"] = {
                "id": str(message.id),
                "role": message.role,
                "content": message.content,
                "citations": message.citations,
                "usage": message.usage,
            }

        # 保存检索日志快照
        if retrieval_log_id:
            retrieval_stmt = select(RetrievalLog).where(
                RetrievalLog.id == retrieval_log_id,
                RetrievalLog.tenant_id == tenant_id,
            )
            retrieval_result = db.execute(retrieval_stmt)
            retrieval_log = retrieval_result.scalar_one_or_none()
            if not retrieval_log:
                raise ValueError(f"retrieval log not found: {retrieval_log_id}")
            snapshot["retrieval"] = {
                "id": str(retrieval_log.id),
                "query": retrieval_log.query_text,
                "results": retrieval_log.result_chunks,
                "metadata": retrieval_log.filter_json,
            }

        return snapshot

    def _replay_retrieval(self, db: Session, feedback: UserFeedback) -> dict[str, Any]:
        """回放检索。"""
        if not self.retriever:
            raise ValueError("retriever not configured")

        snapshot = feedback.snapshot or {}
        retrieval_snapshot = snapshot.get("retrieval", {})
        query = retrieval_snapshot.get("query")

        if not query:
            raise ValueError("no query in snapshot")

        # 执行检索
        result = self.retriever.retrieve(
            db=db,
            query=query,
            tenant_id=feedback.tenant_id,
        )

        return {
            "query": query,
            "hits": result.get("hits", []),
            "strategy": result.get("strategy"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _replay_generation(self, db: Session, feedback: UserFeedback) -> dict[str, Any]:
        """回放生成。"""
        if not self.llm_generator:
            raise ValueError("llm_generator not configured")

        snapshot = feedback.snapshot or {}
        message_snapshot = snapshot.get("message", {})
        retrieval_snapshot = snapshot.get("retrieval", {})

        query = retrieval_snapshot.get("query") or message_snapshot.get("content")
        contexts = retrieval_snapshot.get("results", [])

        if not query:
            raise ValueError("no query in snapshot")

        # 执行生成
        result = self.llm_generator.generate(
            query=query,
            contexts=contexts,
        )

        return {
            "query": query,
            "answer": result.get("content"),
            "citations": result.get("citations", []),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _replay_full_pipeline(self, db: Session, feedback: UserFeedback) -> dict[str, Any]:
        """回放完整流程。"""
        # 先回放检索
        retrieval_result = self._replay_retrieval(db, feedback)

        # 再回放生成
        snapshot = feedback.snapshot or {}
        retrieval_snapshot = snapshot.get("retrieval", {})
        query = retrieval_snapshot.get("query")

        if not self.llm_generator:
            raise ValueError("llm_generator not configured")

        generation_result = self.llm_generator.generate(
            query=query,
            contexts=retrieval_result.get("hits", []),
        )

        return {
            "retrieval": retrieval_result,
            "generation": {
                "query": query,
                "answer": generation_result.get("content"),
                "citations": generation_result.get("citations", []),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def _compare_results(
        self,
        original: dict[str, Any] | None,
        replay: dict[str, Any],
    ) -> dict[str, Any]:
        """对比原始结果和回放结果。"""
        if not original:
            return {"has_original": False}

        comparison: dict[str, Any] = {"has_original": True}

        # 对比检索结果
        original_retrieval = original.get("retrieval", {})
        replay_retrieval = replay.get("retrieval", {})

        if original_retrieval and replay_retrieval:
            original_hits = original_retrieval.get("results", [])
            replay_hits = replay_retrieval.get("hits", [])

            comparison["retrieval"] = {
                "original_count": len(original_hits),
                "replay_count": len(replay_hits),
                "overlap": self._calculate_overlap(original_hits, replay_hits),
            }

        # 对比生成结果
        original_message = original.get("message", {})
        replay_generation = replay.get("generation", {})

        if original_message and replay_generation:
            original_content = original_message.get("content", "")
            replay_content = replay_generation.get("answer", "")

            comparison["generation"] = {
                "original_length": len(original_content),
                "replay_length": len(replay_content),
                "similarity": self._calculate_text_similarity(original_content, replay_content),
            }

        return comparison

    def _calculate_overlap(self, list1: list[dict], list2: list[dict]) -> float:
        """计算两个列表的重叠率。"""
        if not list1 or not list2:
            return 0.0

        ids1 = {item.get("chunk_id") or item.get("id") for item in list1}
        ids2 = {item.get("chunk_id") or item.get("id") for item in list2}

        intersection = len(ids1 & ids2)
        union = len(ids1 | ids2)

        return intersection / union if union > 0 else 0.0

    def _calculate_text_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度（简单的词重叠率）。"""
        words1 = set(text1.lower().split())
        words2 = set(text2.lower().split())

        if not words1 or not words2:
            return 0.0

        intersection = len(words1 & words2)
        union = len(words1 | words2)

        return intersection / union if union > 0 else 0.0

    def _generate_suggestions(
        self,
        feedback: UserFeedback,
        comparison: dict[str, Any],
    ) -> list[str]:
        """生成改进建议。"""
        suggestions = []

        # 根据反馈类型生成建议
        if feedback.feedback_type == "thumbs_down":
            suggestions.append("用户对结果不满意，建议检查检索质量和生成质量")

        # 根据对比结果生成建议
        retrieval_comparison = comparison.get("retrieval", {})
        if retrieval_comparison:
            overlap = retrieval_comparison.get("overlap", 0.0)
            if overlap < 0.5:
                suggestions.append(f"检索结果重叠率较低（{overlap:.2%}），建议优化检索策略")

        generation_comparison = comparison.get("generation", {})
        if generation_comparison:
            similarity = generation_comparison.get("similarity", 0.0)
            if similarity < 0.3:
                suggestions.append(f"生成结果差异较大（相似度 {similarity:.2%}），建议检查生成模型")

        # 根据标签生成建议
        tags = feedback.tags or []
        if "不准确" in tags:
            suggestions.append("用户反馈不准确，建议检查事实性和引用准确性")
        if "不相关" in tags:
            suggestions.append("用户反馈不相关，建议优化检索召回策略")
        if "不完整" in tags:
            suggestions.append("用户反馈不完整，建议增加上下文长度或改进生成策略")

        return suggestions
