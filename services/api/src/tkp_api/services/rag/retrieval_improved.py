"""改进的 RAG 检索与生成服务 - 使用真实向量和 OpenAI LLM。"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from tkp_api.core.config import get_settings
from tkp_api.services.rag.vector_retrieval import create_retriever
from tkp_api.services.rag.llm_generator import create_generator

logger = logging.getLogger("tkp_api.rag.retrieval_improved")

# 全局服务实例（延迟初始化）
_embedding_service = None
_retriever = None
_generator = None


def _get_embedding_service():
    """获取或创建 embedding 服务单例。"""
    global _embedding_service
    if _embedding_service is None:
        from tkp_api.services.rag.embeddings import create_embedding_service
        settings = get_settings()
        _embedding_service = create_embedding_service(
            api_key=settings.openai_api_key,
            model=settings.openai_embedding_model,
        )
    return _embedding_service


def _get_retriever():
    """获取或创建检索器单例。"""
    global _retriever
    if _retriever is None:
        settings = get_settings()
        _retriever = create_retriever(
            embedding_service=_get_embedding_service(),
            top_k=settings.retrieval_top_k,
            similarity_threshold=settings.retrieval_similarity_threshold,
        )
    return _retriever


def _get_generator():
    """获取或创建生成器单例。"""
    global _generator
    if _generator is None:
        settings = get_settings()
        _generator = create_generator(
            api_key=settings.openai_api_key,
            model=settings.openai_chat_model,
            temperature=settings.openai_chat_temperature,
            max_tokens=settings.openai_chat_max_tokens,
        )
    return _generator


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

    retriever = _get_retriever()

    try:
        with db.connection() as conn:
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
                }
            )

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
) -> dict[str, Any]:
    """改进的问答生成接口。

    Args:
        db: 数据库会话
        tenant_id: 租户ID
        kb_ids: 知识库ID列表
        question: 用户问题
        top_k: 检索结果数量

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

    try:
        result = generator.generate_answer(
            query=question,
            context_chunks=chunks,
        )

        logger.info(
            "answer generated: question=%s, chunks=%d, tokens=%d",
            question[:50],
            len(chunks),
            result["usage"]["total_tokens"],
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
