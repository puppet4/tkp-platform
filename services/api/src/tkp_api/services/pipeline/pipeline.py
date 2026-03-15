"""Unified Retrieval Pipeline.

Single entry point for both /api/retrieval/query and /api/chat/completions.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Generator

from sqlalchemy.orm import Session

from tkp_api.core.config import get_settings
from tkp_api.services.pipeline.intent_classifier import IntentClassifier
from tkp_api.services.pipeline.scoring import score_to_api
from tkp_api.services.pipeline.stages import (
    stage_classify_intent,
    stage_context_pack,
    stage_normalize_scores,
    stage_parent_child_merge,
    stage_query_preprocess,
    stage_query_rewrite,
    stage_rerank,
    stage_retrieve,
    stage_rrf_merge,
)
from tkp_api.services.pipeline.types import (
    ChunkResult,
    GenerationConfig,
    GenerationResult,
    IntentResult,
    RetrievalRequest,
    RetrievalResult,
)

logger = logging.getLogger("tkp_api.pipeline")


class RetrievalPipeline:
    """Unified retrieval + generation pipeline."""

    def __init__(
        self,
        *,
        hybrid_retriever,
        query_preprocessor,
        parent_child_merger,
        context_packer,
        answer_grader,
        generator,
        intent_classifier: IntentClassifier | None = None,
    ):
        self.hybrid_retriever = hybrid_retriever
        self.query_preprocessor = query_preprocessor
        self.parent_child_merger = parent_child_merger
        self.context_packer = context_packer
        self.answer_grader = answer_grader
        self.generator = generator
        self.intent_classifier = intent_classifier

    # ------------------------------------------------------------------
    # Public API: retrieve (stages 1-8)
    # ------------------------------------------------------------------

    def retrieve(self, db: Session, request: RetrievalRequest) -> RetrievalResult:
        """Execute retrieval pipeline (stages 1-8)."""
        start = time.perf_counter()
        settings = get_settings()

        query = request.query
        query_rewrite_info = {"original_query": query, "rewritten_query": query, "rewrite_applied": False}

        # Stage 1: Query preprocessing
        if settings.query_language_detection_enabled or settings.query_spell_correction_enabled:
            preprocess_result = stage_query_preprocess(query, self.query_preprocessor)
            query = preprocess_result["processed_query"]

        # Stage 2: Query rewrite
        enable_rewrite = request.enable_query_rewrite if request.enable_query_rewrite is not None else settings.retrieval_enable_query_rewrite
        queries = [query]
        if enable_rewrite and self.hybrid_retriever.query_rewriter:
            rewrite_result = stage_query_rewrite(query, self.hybrid_retriever.query_rewriter)
            queries = rewrite_result["rewritten_queries"]
            if rewrite_result["rewrite_applied"]:
                query_rewrite_info = {
                    "original_query": request.query,
                    "rewritten_query": queries[0],
                    "rewrite_applied": True,
                    "all_queries": queries,
                }

        # Determine strategy
        strategy = request.strategy
        if strategy == "hybrid" and not settings.elasticsearch_enabled:
            strategy = "vector"

        # Stage 3: Retrieval
        vector_hits, keyword_hits = stage_retrieve(
            db, queries, self.hybrid_retriever,
            tenant_id=request.tenant_id, kb_ids=request.kb_ids,
            top_k=request.top_k, strategy=strategy,
        )

        # Stage 4: Score normalisation
        vector_hits = stage_normalize_scores(vector_hits)
        keyword_hits = stage_normalize_scores(keyword_hits)

        # Stage 5: RRF merge (or single-strategy)
        if strategy == "hybrid" and keyword_hits:
            hits = stage_rrf_merge(
                vector_hits, keyword_hits,
                vector_weight=settings.retrieval_vector_weight,
                fulltext_weight=settings.retrieval_fulltext_weight,
            )
        elif strategy == "keyword":
            hits = sorted(keyword_hits, key=lambda x: x.final_score, reverse=True)
        else:
            hits = sorted(vector_hits, key=lambda x: x.final_score, reverse=True)

        # Stage 6: Rerank
        enable_rerank = request.enable_rerank if request.enable_rerank is not None else settings.retrieval_enable_rerank
        rerank_applied = False
        if enable_rerank and self.hybrid_retriever.reranker and hits:
            hits = stage_rerank(hits, request.query, self.hybrid_retriever.reranker, request.top_k)
            rerank_applied = True
        else:
            hits = hits[:request.top_k]

        # Stage 7: Parent-child merge
        if settings.parent_child_merge_enabled and hits:
            hits = stage_parent_child_merge(db, hits, self.parent_child_merger, request.tenant_id)

        # Stage 8: Context packing
        packing_stats = None
        if self.context_packer:
            hits, packing_stats = stage_context_pack(
                hits, request.query, self.context_packer, request.max_context_tokens,
            )

        # Filter by min_score
        if request.min_score > 0:
            hits = [h for h in hits if h.final_score >= request.min_score]

        latency_ms = int((time.perf_counter() - start) * 1000)

        return RetrievalResult(
            hits=hits,
            latency_ms=latency_ms,
            strategy=strategy,
            query_rewrite=query_rewrite_info,
            rerank_applied=rerank_applied,
            context_packing_stats=packing_stats,
        )

    # ------------------------------------------------------------------
    # Public API: generate (stages 0-10, non-streaming)
    # ------------------------------------------------------------------

    def generate(self, db: Session, request: RetrievalRequest) -> GenerationResult:
        """Execute full RAG pipeline including generation."""
        intent: IntentResult | None = None

        # Stage 0: Intent classification (chat path only)
        if not request.skip_intent_classification and self.intent_classifier:
            intent = stage_classify_intent(
                request.query, request.history_messages, self.intent_classifier,
            )
            if not intent.needs_retrieval:
                return self._generate_without_retrieval(db, request, intent)
            if intent.rewritten_query:
                request.query = intent.rewritten_query

        # Stages 1-8: Retrieval
        retrieval_result = self.retrieve(db, request)

        if not retrieval_result.hits:
            return GenerationResult(
                hits=[],
                latency_ms=retrieval_result.latency_ms,
                strategy=retrieval_result.strategy,
                query_rewrite=retrieval_result.query_rewrite,
                rerank_applied=retrieval_result.rerank_applied,
                answer=f'抱歉，在知识库中未找到与"{request.query}"相关的信息。',
                citations=[],
                usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
                intent=intent,
            )

        # Stage 9: Generation
        gen_config = request.generation_config or GenerationConfig()
        context_chunks = self._chunks_to_dicts(retrieval_result.hits)

        gen_result = self.generator.generate_answer(
            query=request.query,
            context_chunks=context_chunks,
            history_messages=request.history_messages[-10:] if request.history_messages else None,
            include_confidence=get_settings().answer_grading_enabled,
        )

        # Stage 10: Answer grading
        settings = get_settings()
        confidence = None
        rejected = False

        if settings.answer_grading_enabled and self.answer_grader:
            grading = self.answer_grader.calculate_confidence(
                query=request.query,
                answer=gen_result.get("answer", ""),
                chunks=context_chunks,
                llm_confidence=gen_result.get("llm_confidence"),
            )
            confidence = grading.get("confidence_score")
            rejected = grading.get("rejected", False)

            if rejected:
                return GenerationResult(
                    hits=retrieval_result.hits,
                    latency_ms=retrieval_result.latency_ms,
                    strategy=retrieval_result.strategy,
                    query_rewrite=retrieval_result.query_rewrite,
                    rerank_applied=retrieval_result.rerank_applied,
                    answer=grading.get("rejection_message", "抱歉，我对这个问题的回答置信度不足。"),
                    citations=[],
                    usage=gen_result.get("usage", {}),
                    confidence=confidence,
                    rejected=True,
                    intent=intent,
                )

        return GenerationResult(
            hits=retrieval_result.hits,
            latency_ms=retrieval_result.latency_ms,
            strategy=retrieval_result.strategy,
            query_rewrite=retrieval_result.query_rewrite,
            rerank_applied=retrieval_result.rerank_applied,
            context_packing_stats=retrieval_result.context_packing_stats,
            answer=gen_result.get("answer", ""),
            citations=gen_result.get("citations", []),
            usage=gen_result.get("usage", {}),
            confidence=confidence,
            rejected=rejected,
            intent=intent,
        )

    # ------------------------------------------------------------------
    # Public API: generate_streaming (stages 0-10, streaming)
    # ------------------------------------------------------------------

    def generate_streaming(
        self, db: Session, request: RetrievalRequest,
    ) -> Generator[dict[str, Any], None, None]:
        """Stream: yield dicts with type=citations|content|done|error."""
        intent: IntentResult | None = None

        # Stage 0: Intent classification
        if not request.skip_intent_classification and self.intent_classifier:
            intent = stage_classify_intent(
                request.query, request.history_messages, self.intent_classifier,
            )
            if not intent.needs_retrieval:
                yield from self._stream_without_retrieval(request, intent)
                return
            if intent.rewritten_query:
                request.query = intent.rewritten_query

        # Stages 1-8
        retrieval_result = self.retrieve(db, request)
        context_chunks = self._chunks_to_dicts(retrieval_result.hits)

        # Yield citations
        citations = []
        for chunk in context_chunks:
            citations.append({
                "chunk_id": str(chunk["chunk_id"]),
                "document_id": str(chunk["document_id"]),
                "document_version_id": str(chunk.get("document_version_id", "")),
                "document_title": chunk["document_title"],
                "kb_name": chunk["kb_name"],
                "similarity": chunk["similarity"],
                "snippet": chunk.get("snippet", ""),
                "content": chunk["content"],
            })
        yield {"type": "citations", "data": citations}

        # Stage 9: Streaming generation
        gen_config = request.generation_config or GenerationConfig()
        history = request.history_messages[-10:] if request.history_messages else None

        full_answer = ""
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

        try:
            for chunk_text in self.generator.generate_streaming_answer(
                query=request.query,
                context_chunks=context_chunks,
                history_messages=history,
                temperature=gen_config.temperature,
                max_tokens=gen_config.max_tokens,
            ):
                full_answer += chunk_text
                yield {"type": "content", "data": chunk_text}

        except Exception as exc:
            logger.exception("streaming generation failed: %s", exc)
            yield {"type": "error", "data": str(exc)}
            return

        # Stage 10: Answer grading (post-stream)
        settings = get_settings()
        confidence = None

        if settings.answer_grading_enabled and self.answer_grader and full_answer:
            try:
                grading = self.answer_grader.calculate_confidence(
                    query=request.query,
                    answer=full_answer,
                    chunks=context_chunks,
                )
                confidence = grading.get("confidence_score")
            except Exception as exc:
                logger.warning("post-stream grading failed: %s", exc)

        yield {
            "type": "done",
            "data": {
                "answer": full_answer,
                "usage": usage,
                "confidence": confidence,
                "citations": citations,
            },
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_without_retrieval(
        self, db: Session, request: RetrievalRequest, intent: IntentResult,
    ) -> GenerationResult:
        """Generate answer without retrieval (chitchat, general knowledge, etc.)."""
        gen_config = request.generation_config or GenerationConfig()
        history = request.history_messages[-10:] if request.history_messages else None

        try:
            # Use generator with empty context
            result = self.generator.generate_answer(
                query=request.query,
                context_chunks=[],
                history_messages=history,
            )
            return GenerationResult(
                hits=[],
                latency_ms=0,
                strategy="none",
                query_rewrite={"original_query": request.query, "rewritten_query": request.query, "rewrite_applied": False},
                rerank_applied=False,
                answer=result.get("answer", ""),
                citations=[],
                usage=result.get("usage", {}),
                intent=intent,
            )
        except Exception as exc:
            logger.exception("generation without retrieval failed: %s", exc)
            return GenerationResult(
                hits=[], latency_ms=0, strategy="none",
                query_rewrite={"original_query": request.query, "rewritten_query": request.query, "rewrite_applied": False},
                rerank_applied=False,
                answer="抱歉，生成回答时出现错误。",
                citations=[], usage={}, intent=intent,
            )

    def _stream_without_retrieval(
        self, request: RetrievalRequest, intent: IntentResult,
    ) -> Generator[dict[str, Any], None, None]:
        """Stream generation without retrieval."""
        yield {"type": "citations", "data": []}

        gen_config = request.generation_config or GenerationConfig()
        history = request.history_messages[-10:] if request.history_messages else None
        full_answer = ""

        try:
            for chunk_text in self.generator.generate_streaming_answer(
                query=request.query,
                context_chunks=[],
                history_messages=history,
                temperature=gen_config.temperature,
                max_tokens=gen_config.max_tokens,
            ):
                full_answer += chunk_text
                yield {"type": "content", "data": chunk_text}
        except Exception as exc:
            yield {"type": "error", "data": str(exc)}
            return

        yield {"type": "done", "data": {"answer": full_answer, "usage": {}, "confidence": None, "citations": []}}

    @staticmethod
    def _clean_content(text: str) -> str:
        """Strip markdown noise from chunk content for better display and LLM input."""
        # Remove markdown images: ![alt](path)
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", text)
        # Remove HTML comments
        text = re.sub(r"<!--.*?-->", "", text)
        # Remove URL-encoded links that are just index noise
        text = re.sub(r"\[([^\]]*)\]\(%[A-F0-9]{2}[^)]*\)", r"\1", text)
        # Collapse excessive blank lines
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def _chunks_to_dicts(hits: list[ChunkResult]) -> list[dict[str, Any]]:
        """Convert ChunkResult list to dicts, deduplicate by document_id, clean content."""
        seen_doc_ids: set[str] = set()
        result = []
        for h in hits:
            # Deduplicate: keep only the highest-scoring chunk per document
            if h.document_id in seen_doc_ids:
                continue
            seen_doc_ids.add(h.document_id)

            cleaned = RetrievalPipeline._clean_content(h.content)
            # Skip chunks with very little real content after cleaning
            if len(cleaned) < 10:
                continue

            snippet = cleaned[:200] + "..." if len(cleaned) > 200 else cleaned
            result.append({
                "chunk_id": h.chunk_id,
                "document_id": h.document_id,
                "document_version_id": h.document_version_id,
                "kb_id": h.kb_id,
                "kb_name": h.kb_name,
                "document_title": h.document_title,
                "chunk_no": h.chunk_no,
                "content": cleaned,
                "snippet": snippet,
                "metadata": h.metadata,
                "parent_chunk_id": h.parent_chunk_id,
                "score": h.final_score,
                "similarity": h.final_score,
                "retrieval_method": h.retrieval_method,
            })
        return result


class PipelineSingleton:
    """Thread-safe singleton for the unified pipeline."""

    _instance: RetrievalPipeline | None = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls) -> RetrievalPipeline:
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls._create()
        return cls._instance

    @classmethod
    def _create(cls) -> RetrievalPipeline:
        from tkp_api.services.context_packing import create_context_packer
        from tkp_api.services.parent_child_merger import ParentChildMerger
        from tkp_api.services.query_preprocessing import QueryPreprocessor
        from tkp_api.services.rag.answer_grader import create_answer_grader
        from tkp_api.services.rag.llm_generator import create_generator

        settings = get_settings()

        # --- Hybrid retriever (reuses existing creation logic) ---
        from tkp_api.services.embedding_service import get_embedding_service
        from tkp_api.services.rag.vector_retrieval import create_retriever

        embedding_service = get_embedding_service()
        vector_retriever = create_retriever(
            embedding_service=embedding_service,
            top_k=settings.retrieval_top_k,
            similarity_threshold=settings.retrieval_similarity_threshold,
        )

        elasticsearch_client = None
        if settings.elasticsearch_enabled:
            try:
                from tkp_api.services.rag.elasticsearch_client import create_elasticsearch_client
                elasticsearch_client = create_elasticsearch_client(
                    hosts=settings.elasticsearch_hosts.split(","),
                    api_key=settings.elasticsearch_api_key or None,
                    username=settings.elasticsearch_username or None,
                    password=settings.elasticsearch_password or None,
                    verify_certs=settings.elasticsearch_verify_certs,
                )
            except Exception as exc:
                logger.warning("failed to initialize elasticsearch: %s", exc)

        reranker = None
        if settings.retrieval_enable_rerank and settings.rerank_api_key:
            try:
                from tkp_api.services.rag.reranker import create_reranker
                reranker = create_reranker(
                    provider=settings.rerank_provider,
                    api_key=settings.rerank_api_key,
                    model=settings.rerank_model or None,
                    top_n=settings.rerank_top_n,
                )
            except Exception as exc:
                logger.warning("failed to initialize reranker: %s", exc)

        query_rewriter = None
        if settings.retrieval_enable_query_rewrite:
            try:
                from tkp_api.services.rag.query_rewriter import create_query_rewriter
                query_rewriter = create_query_rewriter(
                    api_key=settings.resolved_openai_chat_api_key,
                    base_url=settings.resolved_openai_chat_base_url,
                    model=settings.openai_chat_model,
                    strategy=settings.query_rewrite_strategy,
                )
            except Exception as exc:
                logger.warning("failed to initialize query rewriter: %s", exc)

        from tkp_api.services.rag.hybrid_retrieval import create_hybrid_retriever
        hybrid_retriever = create_hybrid_retriever(
            vector_retriever=vector_retriever,
            elasticsearch_client=elasticsearch_client,
            reranker=reranker,
            query_rewriter=query_rewriter,
            vector_weight=settings.retrieval_vector_weight,
            fulltext_weight=settings.retrieval_fulltext_weight,
        )

        # --- Other components ---
        query_preprocessor = QueryPreprocessor(
            enable_language_detection=settings.query_language_detection_enabled,
            enable_spell_correction=settings.query_spell_correction_enabled,
        )
        parent_child_merger = ParentChildMerger(
            max_merge_distance=settings.parent_child_max_merge_distance,
        )
        context_packer = create_context_packer(
            max_tokens=settings.context_max_tokens,
            similarity_threshold=settings.context_similarity_threshold,
            reserve_tokens=settings.context_reserve_tokens,
        )
        answer_grader = create_answer_grader()
        generator = create_generator(
            api_key=settings.resolved_openai_chat_api_key,
            base_url=settings.resolved_openai_chat_base_url,
            model=settings.openai_chat_model,
            temperature=settings.openai_chat_temperature,
            max_tokens=settings.openai_chat_max_tokens,
        )

        # Intent classifier
        from openai import OpenAI
        intent_client = OpenAI(
            api_key=settings.resolved_openai_chat_api_key,
            base_url=settings.resolved_openai_chat_base_url or None,
        )
        intent_classifier = IntentClassifier(client=intent_client, model=settings.openai_chat_model)

        return RetrievalPipeline(
            hybrid_retriever=hybrid_retriever,
            query_preprocessor=query_preprocessor,
            parent_child_merger=parent_child_merger,
            context_packer=context_packer,
            answer_grader=answer_grader,
            generator=generator,
            intent_classifier=intent_classifier,
        )

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        with cls._lock:
            cls._instance = None
