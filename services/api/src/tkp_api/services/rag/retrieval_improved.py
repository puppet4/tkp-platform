"""改进的 RAG 检索与生成服务 - 使用真实向量和 OpenAI LLM。"""

from __future__ import annotations

import logging
import threading
from functools import lru_cache
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from tkp_api.core.config import get_settings
from tkp_api.services.parent_child_merger import ParentChildMerger
from tkp_api.services.query_preprocessing import QueryPreprocessor
from tkp_api.services.rag.answer_grader import create_answer_grader
from tkp_api.services.rag.llm_generator import create_generator
from tkp_api.services.rag.vector_retrieval import create_retriever

logger = logging.getLogger("tkp_api.rag.retrieval_improved")


def _normalize_usage(raw_usage: Any) -> dict[str, int]:
    """归一化生成器 usage 字段。"""
    if not isinstance(raw_usage, dict):
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    prompt_tokens = raw_usage.get("prompt_tokens", 0)
    completion_tokens = raw_usage.get("completion_tokens", 0)
    total_tokens = raw_usage.get("total_tokens", 0)
    return {
        "prompt_tokens": int(prompt_tokens) if isinstance(prompt_tokens, (int, float)) else 0,
        "completion_tokens": int(completion_tokens) if isinstance(completion_tokens, (int, float)) else 0,
        "total_tokens": int(total_tokens) if isinstance(total_tokens, (int, float)) else 0,
    }


def _normalize_generation_result(raw_result: Any) -> dict[str, Any]:
    """归一化生成器返回结果，确保字段类型稳定。"""
    if not isinstance(raw_result, dict):
        return {
            "answer": "",
            "citations": [],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    answer_raw = raw_result.get("answer")
    citations_raw = raw_result.get("citations")
    normalized_citations: list[Any] = citations_raw if isinstance(citations_raw, list) else []

    normalized: dict[str, Any] = {
        "answer": answer_raw if isinstance(answer_raw, str) else "",
        "citations": normalized_citations,
        "usage": _normalize_usage(raw_result.get("usage")),
    }
    if "llm_confidence" in raw_result:
        normalized["llm_confidence"] = raw_result.get("llm_confidence")
    return normalized


# 线程安全的服务单例管理器
class RAGServicesSingleton:
    """线程安全的 RAG 服务单例管理器。"""

    _embedding_service = None
    _retriever = None
    _generator = None
    _query_preprocessor = None
    _parent_child_merger = None
    _answer_grader = None
    _lock = threading.Lock()

    @classmethod
    def get_embedding_service(cls):
        """获取 embedding 服务单例（线程安全）。"""
        if cls._embedding_service is None:
            with cls._lock:
                if cls._embedding_service is None:
                    from tkp_api.services.rag.embeddings import create_embedding_service
                    settings = get_settings()
                    cls._embedding_service = create_embedding_service(
                        api_key=settings.resolved_openai_embedding_api_key,
                        base_url=settings.resolved_openai_embedding_base_url,
                        model=settings.openai_embedding_model,
                    )
        return cls._embedding_service

    @classmethod
    def get_retriever(cls):
        """获取检索器单例（线程安全）。"""
        if cls._retriever is None:
            with cls._lock:
                if cls._retriever is None:
                    settings = get_settings()
                    cls._retriever = create_retriever(
                        embedding_service=cls.get_embedding_service(),
                        top_k=settings.retrieval_top_k,
                        similarity_threshold=settings.retrieval_similarity_threshold,
                    )
        return cls._retriever

    @classmethod
    def get_generator(cls):
        """获取生成器单例（线程安全）。"""
        if cls._generator is None:
            with cls._lock:
                if cls._generator is None:
                    settings = get_settings()
                    cls._generator = create_generator(
                        api_key=settings.resolved_openai_chat_api_key,
                        base_url=settings.resolved_openai_chat_base_url,
                        model=settings.openai_chat_model,
                        temperature=settings.openai_chat_temperature,
                        max_tokens=settings.openai_chat_max_tokens,
                    )
        return cls._generator

    @classmethod
    def get_query_preprocessor(cls):
        """获取查询预处理器单例（线程安全）。"""
        if cls._query_preprocessor is None:
            with cls._lock:
                if cls._query_preprocessor is None:
                    settings = get_settings()
                    cls._query_preprocessor = QueryPreprocessor(
                        enable_language_detection=settings.query_language_detection_enabled,
                        enable_spell_correction=settings.query_spell_correction_enabled,
                    )
        return cls._query_preprocessor

    @classmethod
    def get_parent_child_merger(cls):
        """获取父子块合并器单例（线程安全）。"""
        if cls._parent_child_merger is None:
            with cls._lock:
                if cls._parent_child_merger is None:
                    settings = get_settings()
                    cls._parent_child_merger = ParentChildMerger(
                        max_merge_distance=settings.parent_child_max_merge_distance,
                    )
        return cls._parent_child_merger

    @classmethod
    def get_answer_grader(cls):
        """获取答案评分器单例（线程安全）。"""
        if cls._answer_grader is None:
            with cls._lock:
                if cls._answer_grader is None:
                    cls._answer_grader = create_answer_grader()
        return cls._answer_grader

    @classmethod
    def reset_all(cls) -> None:
        """重置所有单例实例（主要用于测试）。"""
        with cls._lock:
            cls._embedding_service = None
            cls._retriever = None
            cls._generator = None
            cls._query_preprocessor = None
            cls._parent_child_merger = None
            cls._answer_grader = None


@lru_cache(maxsize=1)
def _get_embedding_service():
    """获取 embedding 服务单例。"""
    return RAGServicesSingleton.get_embedding_service()


@lru_cache(maxsize=1)
def _get_retriever():
    """获取检索器单例。"""
    return RAGServicesSingleton.get_retriever()


@lru_cache(maxsize=1)
def _get_generator():
    """获取生成器单例。"""
    return RAGServicesSingleton.get_generator()


@lru_cache(maxsize=1)
def _get_query_preprocessor():
    """获取查询预处理器单例。"""
    return RAGServicesSingleton.get_query_preprocessor()


@lru_cache(maxsize=1)
def _get_parent_child_merger():
    """获取父子块合并器单例。"""
    return RAGServicesSingleton.get_parent_child_merger()


@lru_cache(maxsize=1)
def _get_answer_grader():
    """获取答案评分器单例。"""
    return RAGServicesSingleton.get_answer_grader()


def search_chunks_improved(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID] | None,
    query: str,
    top_k: int = 5,
) -> list[dict[str, Any]]:
    """改进的语义检索接口。

    Args:
        db: 数据库会话
        tenant_id: 租户ID
        kb_ids: 知识库ID列表
        query: 查询文本
        top_k: 返回结果数量

    Returns:
        检索结果列表
    """
    if not query.strip():
        return []

    settings = get_settings()
    original_query = query

    # Feature 1: Query Preprocessing
    if settings.query_language_detection_enabled or settings.query_spell_correction_enabled:
        preprocessor = _get_query_preprocessor()
        preprocessing_result = preprocessor.preprocess(query)
        query = preprocessing_result["processed_query"]

        logger.info(
            "query preprocessing: original='%s', processed='%s', language=%s",
            original_query[:50],
            query[:50],
            preprocessing_result.get("language"),
        )

    retriever = _get_retriever()

    try:
        conn = db.connection()
        results = retriever.retrieve(
            conn,
            query=query,
            tenant_id=tenant_id,
            kb_ids=kb_ids,
        )

        # 格式化为统一的返回格式
        formatted_results = []
        for result in results[:top_k]:
            formatted_results.append(
                {
                    "chunk_id": result["chunk_id"],
                    "document_id": result["document_id"],
                    "document_version_id": result["document_version_id"],
                    "kb_id": result["kb_id"],
                    "kb_name": result["kb_name"],
                    "document_title": result["document_title"],
                    "chunk_no": result["chunk_no"],
                    "content": result["content"],
                    "snippet": result["content"][:200] + "..." if len(result["content"]) > 200 else result["content"],
                    "score": result["similarity"],
                    "similarity": result["similarity"],
                    "metadata": result["metadata"],
                    "parent_chunk_id": result.get("parent_chunk_id"),
                }
            )

        # Feature 2: Parent-Child Chunk Merging
        if settings.parent_child_merge_enabled and formatted_results:
            merger = _get_parent_child_merger()
            formatted_results = merger.merge_with_parents(
                db=db,
                chunks=formatted_results,
                tenant_id=tenant_id,
            )
            logger.info("parent-child merging applied: %d chunks", len(formatted_results))

        logger.info("search completed: query=%s, results=%d", query[:50], len(formatted_results))
        return formatted_results

    except Exception as exc:
        logger.exception("search failed: %s", exc)
        return []


def generate_answer_improved(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID] | None,
    question: str,
    top_k: int = 5,
    history_messages: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """改进的问答生成接口。

    Args:
        db: 数据库会话
        tenant_id: 租户ID
        kb_ids: 知识库ID列表
        question: 用户问题
        top_k: 检索结果数量
        history_messages: 历史对话消息（用于上下文记忆）

    Returns:
        包含 answer、citations、usage 的字典
    """
    if not question.strip():
        return {
            "answer": "请输入有效的问题。",
            "citations": [],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    # 先检索相关文档
    chunks = search_chunks_improved(
        db,
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        query=question,
        top_k=top_k,
    )

    if not chunks:
        return {
            "answer": f'抱歉，在知识库中未找到与"{question}"相关的信息。',
            "citations": [],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

    # 使用 LLM 生成回答
    generator = _get_generator()
    settings = get_settings()

    try:
        # 如果启用答案评分，请求 LLM 提供置信度
        result = _normalize_generation_result(
            generator.generate_answer(
                query=question,
                context_chunks=chunks,
                history_messages=history_messages,
                include_confidence=settings.answer_grading_enabled,
            )
        )

        # Feature 3: Answer Grading
        if settings.answer_grading_enabled:
            grader = _get_answer_grader()
            grading = grader.calculate_confidence(
                query=question,
                answer=result["answer"],
                chunks=chunks,
                llm_confidence=result.get("llm_confidence"),
            )

            # 如果置信度过低，返回拒答
            if grading["rejected"]:
                logger.warning(
                    "answer rejected: confidence=%.2f, reason=%s",
                    grading["confidence_score"],
                    grading["rejection_reason"],
                )
                return {
                    "answer": grading["rejection_message"],
                    "citations": [],
                    "usage": result["usage"],
                    "confidence_score": grading["confidence_score"],
                    "rejected": True,
                    "rejection_reason": grading["rejection_reason"],
                    "suggestions": grading["suggestions"],
                }

            # 添加置信度信息到结果
            result["confidence_score"] = grading["confidence_score"]
            result["confidence_breakdown"] = {
                "retrieval_score": grading["retrieval_score"],
                "llm_score": grading["llm_score"],
                "citation_score": grading["citation_score"],
            }

        logger.info(
            "answer generated: question=%s, chunks=%d, history=%d, tokens=%d, confidence=%s",
            question[:50],
            len(chunks),
            len(history_messages) if history_messages else 0,
            result["usage"]["total_tokens"],
            f"{result.get('confidence_score', 0):.2f}" if settings.answer_grading_enabled else "N/A",
        )

        return result

    except Exception as exc:
        logger.exception("answer generation failed: %s", exc)
        # 回退到简单的摘要
        citations = [
            {
                "chunk_id": chunk["chunk_id"],
                "document_id": chunk["document_id"],
                "document_version_id": chunk["document_version_id"],
                "document_title": chunk["document_title"],
                "kb_name": chunk["kb_name"],
                "similarity": chunk["similarity"],
            }
            for chunk in chunks
        ]

        bullet_lines = [f"- {chunk['snippet']}" for chunk in chunks[:3]]
        fallback_answer = "基于知识库检索到以下信息:\n" + "\n".join(bullet_lines)

        return {
            "answer": fallback_answer,
            "citations": citations,
            "usage": {
                "prompt_tokens": len(question.split()),
                "completion_tokens": len(fallback_answer.split()),
                "total_tokens": len(question.split()) + len(fallback_answer.split()),
            },
        }
