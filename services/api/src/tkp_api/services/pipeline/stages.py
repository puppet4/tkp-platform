"""Pipeline stage functions.

Each stage is a pure function operating on pipeline data structures.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from tkp_api.services.pipeline.scoring import normalize_rrf_scores, normalize_vector_similarity
from tkp_api.services.pipeline.types import ChunkResult, IntentResult, RetrievalRequest

logger = logging.getLogger("tkp_api.pipeline.stages")


# ---------------------------------------------------------------------------
# Stage 0: Intent classification
# ---------------------------------------------------------------------------

def stage_classify_intent(
    query: str,
    history: list[dict] | None,
    classifier,
) -> IntentResult:
    """Classify user intent (chat path only)."""
    return classifier.classify(query, history)


# ---------------------------------------------------------------------------
# Stage 1: Query preprocessing
# ---------------------------------------------------------------------------

def stage_query_preprocess(query: str, preprocessor) -> dict[str, Any]:
    """Preprocess query (language detection, spell correction, normalisation)."""
    return preprocessor.preprocess(query)


# ---------------------------------------------------------------------------
# Stage 2: Query rewrite (multi-query)
# ---------------------------------------------------------------------------

def stage_query_rewrite(query: str, rewriter) -> dict[str, Any]:
    """Rewrite query into multiple search queries."""
    try:
        result = rewriter.rewrite(query)
        if result.get("rewrite_applied") and result.get("rewritten_queries"):
            return {
                "original_query": query,
                "rewritten_queries": result["rewritten_queries"],
                "rewrite_applied": True,
            }
    except Exception as exc:
        logger.warning("query rewrite failed, using original: %s", exc)

    return {
        "original_query": query,
        "rewritten_queries": [query],
        "rewrite_applied": False,
    }


# ---------------------------------------------------------------------------
# Stage 3: Retrieval (vector + keyword)
# ---------------------------------------------------------------------------

def stage_retrieve(
    db: Session,
    queries: list[str],
    retriever,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID] | None,
    top_k: int,
    strategy: str,
) -> tuple[list[ChunkResult], list[ChunkResult]]:
    """Execute retrieval for all queries. Returns (vector_hits, keyword_hits).

    For multi-query, deduplicates by chunk_id keeping the highest score.
    """
    vector_all: dict[str, ChunkResult] = {}
    keyword_all: dict[str, ChunkResult] = {}

    for q in queries:
        v_hits, k_hits = _retrieve_single(db, q, retriever, tenant_id=tenant_id, kb_ids=kb_ids, top_k=top_k, strategy=strategy)
        for hit in v_hits:
            existing = vector_all.get(hit.chunk_id)
            if existing is None or hit.vector_score > existing.vector_score:
                vector_all[hit.chunk_id] = hit
        for hit in k_hits:
            existing = keyword_all.get(hit.chunk_id)
            if existing is None or hit.keyword_score > existing.keyword_score:
                keyword_all[hit.chunk_id] = hit

    return list(vector_all.values()), list(keyword_all.values())


def _retrieve_single(
    db: Session,
    query: str,
    retriever,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID] | None,
    top_k: int,
    strategy: str,
) -> tuple[list[ChunkResult], list[ChunkResult]]:
    """Single-query retrieval. Returns (vector_hits, keyword_hits)."""
    vector_hits: list[ChunkResult] = []
    keyword_hits: list[ChunkResult] = []

    if strategy in ("vector", "hybrid"):
        try:
            conn = db.connection()
            raw = retriever.vector_retriever.retrieve(conn, query=query, tenant_id=tenant_id, kb_ids=kb_ids)
            for r in raw[:top_k * 2]:
                vector_hits.append(_raw_to_chunk(r, method="vector"))
        except Exception as exc:
            logger.exception("vector search failed: %s", exc)

    if strategy in ("keyword", "hybrid") and retriever.elasticsearch_client:
        try:
            raw = retriever.elasticsearch_client.full_text_search(
                index_name="document_chunks",
                query_text=query,
                tenant_id=tenant_id,
                kb_ids=kb_ids,
                size=top_k * 2,
            )
            for r in raw:
                keyword_hits.append(_es_to_chunk(r))
        except Exception as exc:
            logger.exception("keyword search failed: %s", exc)

    return vector_hits, keyword_hits


def _raw_to_chunk(r: dict, method: str = "vector") -> ChunkResult:
    sim = normalize_vector_similarity(float(r.get("similarity", 0)))
    return ChunkResult(
        chunk_id=str(r["chunk_id"]),
        document_id=str(r["document_id"]),
        document_version_id=str(r["document_version_id"]),
        kb_id=str(r["kb_id"]),
        kb_name=r.get("kb_name", ""),
        document_title=r.get("document_title", ""),
        chunk_no=r.get("chunk_no", 0),
        content=r.get("content", ""),
        metadata=r.get("metadata", {}),
        parent_chunk_id=str(r["parent_chunk_id"]) if r.get("parent_chunk_id") else None,
        vector_score=sim,
        final_score=sim,
        retrieval_method=method,
    )


def _es_to_chunk(r: dict) -> ChunkResult:
    score = float(r.get("score", 0))
    norm = min(1.0, score / 100.0) if score > 1.0 else max(0.0, score)
    return ChunkResult(
        chunk_id=str(r.get("id", "")),
        document_id=str(r.get("document_id", "")),
        document_version_id=str(r.get("document_version_id", "")),
        kb_id=str(r.get("kb_id", "")),
        kb_name=r.get("kb_name", ""),
        document_title=r.get("document_title", ""),
        chunk_no=r.get("chunk_no", 0),
        content=r.get("content", ""),
        metadata=r.get("metadata", {}),
        keyword_score=norm,
        final_score=norm,
        retrieval_method="keyword",
    )


# ---------------------------------------------------------------------------
# Stage 4: Score normalisation
# ---------------------------------------------------------------------------

def stage_normalize_scores(hits: list[ChunkResult]) -> list[ChunkResult]:
    """Ensure all scores are 0-1 (already handled by _raw_to_chunk)."""
    for h in hits:
        h.vector_score = max(0.0, min(1.0, h.vector_score))
        h.keyword_score = max(0.0, min(1.0, h.keyword_score))
        h.final_score = max(0.0, min(1.0, h.final_score))
    return hits


# ---------------------------------------------------------------------------
# Stage 5: RRF merge
# ---------------------------------------------------------------------------

def stage_rrf_merge(
    vector_hits: list[ChunkResult],
    keyword_hits: list[ChunkResult],
    *,
    vector_weight: float = 0.5,
    fulltext_weight: float = 0.5,
    k: int = 60,
) -> list[ChunkResult]:
    """Merge vector and keyword hits using Reciprocal Rank Fusion.

    Output scores are normalised so the top hit = 1.0.
    """
    merged: dict[str, ChunkResult] = {}

    for rank, hit in enumerate(sorted(vector_hits, key=lambda x: x.vector_score, reverse=True), start=1):
        cid = hit.chunk_id
        if cid not in merged:
            merged[cid] = ChunkResult(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                document_version_id=hit.document_version_id,
                kb_id=hit.kb_id,
                kb_name=hit.kb_name,
                document_title=hit.document_title,
                chunk_no=hit.chunk_no,
                content=hit.content,
                metadata=hit.metadata,
                parent_chunk_id=hit.parent_chunk_id,
                vector_score=hit.vector_score,
                retrieval_method="vector",
            )
        merged[cid].final_score += vector_weight / (k + rank)
        merged[cid].vector_score = max(merged[cid].vector_score, hit.vector_score)

    for rank, hit in enumerate(sorted(keyword_hits, key=lambda x: x.keyword_score, reverse=True), start=1):
        cid = hit.chunk_id
        if cid not in merged:
            merged[cid] = ChunkResult(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                document_version_id=hit.document_version_id,
                kb_id=hit.kb_id,
                kb_name=hit.kb_name,
                document_title=hit.document_title,
                chunk_no=hit.chunk_no,
                content=hit.content,
                metadata=hit.metadata,
                parent_chunk_id=hit.parent_chunk_id,
                keyword_score=hit.keyword_score,
                retrieval_method="keyword",
            )
        merged[cid].final_score += fulltext_weight / (k + rank)
        merged[cid].keyword_score = max(merged[cid].keyword_score, hit.keyword_score)
        if merged[cid].vector_score > 0 and merged[cid].keyword_score > 0:
            merged[cid].retrieval_method = "hybrid"

    results = sorted(merged.values(), key=lambda x: x.final_score, reverse=True)

    # Normalise: top = 1.0
    if results:
        max_score = results[0].final_score
        if max_score > 0:
            for r in results:
                r.final_score = r.final_score / max_score

    return results


# ---------------------------------------------------------------------------
# Stage 6: Rerank
# ---------------------------------------------------------------------------

def stage_rerank(
    hits: list[ChunkResult],
    query: str,
    reranker,
    top_k: int,
) -> list[ChunkResult]:
    """Rerank hits using external reranker service."""
    try:
        docs = [
            {
                "chunk_id": h.chunk_id,
                "document_id": h.document_id,
                "document_version_id": h.document_version_id,
                "kb_id": h.kb_id,
                "kb_name": h.kb_name,
                "document_title": h.document_title,
                "chunk_no": h.chunk_no,
                "content": h.content,
                "metadata": h.metadata,
                "score": h.final_score,
                "similarity": h.final_score,
                "retrieval_method": h.retrieval_method,
            }
            for h in hits
        ]
        reranked = reranker.rerank(query=query, documents=docs, top_n=top_k)

        result = []
        for i, doc in enumerate(reranked):
            chunk = ChunkResult(
                chunk_id=doc["chunk_id"],
                document_id=doc["document_id"],
                document_version_id=doc.get("document_version_id", ""),
                kb_id=doc.get("kb_id", ""),
                kb_name=doc.get("kb_name", ""),
                document_title=doc.get("document_title", ""),
                chunk_no=doc.get("chunk_no", 0),
                content=doc.get("content", ""),
                metadata=doc.get("metadata", {}),
                rerank_score=doc.get("rerank_score"),
                final_score=1.0 - (i / max(len(reranked), 1)),  # rank-based 1.0 → 0
                retrieval_method=doc.get("retrieval_method", "vector"),
            )
            result.append(chunk)

        logger.info("rerank applied: %d results", len(result))
        return result

    except Exception as exc:
        logger.warning("rerank failed, using original order: %s", exc)
        return hits[:top_k]


# ---------------------------------------------------------------------------
# Stage 7: Parent-child merge
# ---------------------------------------------------------------------------

def stage_parent_child_merge(
    db: Session,
    hits: list[ChunkResult],
    merger,
    tenant_id: UUID,
) -> list[ChunkResult]:
    """Expand child chunks to include parent context."""
    try:
        chunk_dicts = [
            {
                "chunk_id": h.chunk_id,
                "document_id": h.document_id,
                "document_version_id": h.document_version_id,
                "kb_id": h.kb_id,
                "kb_name": h.kb_name,
                "document_title": h.document_title,
                "chunk_no": h.chunk_no,
                "content": h.content,
                "metadata": h.metadata,
                "parent_chunk_id": h.parent_chunk_id,
                "similarity": h.final_score,
                "score": h.final_score,
            }
            for h in hits
        ]
        merged = merger.merge_with_parents(db=db, chunks=chunk_dicts, tenant_id=tenant_id)

        result = []
        for m in merged:
            # Find original ChunkResult to preserve scores
            original = next((h for h in hits if h.chunk_id == str(m.get("chunk_id", ""))), None)
            result.append(ChunkResult(
                chunk_id=str(m.get("chunk_id", "")),
                document_id=str(m.get("document_id", "")),
                document_version_id=str(m.get("document_version_id", "")),
                kb_id=str(m.get("kb_id", "")),
                kb_name=m.get("kb_name", ""),
                document_title=m.get("document_title", ""),
                chunk_no=m.get("chunk_no", 0),
                content=m.get("content", ""),
                metadata=m.get("metadata", {}),
                parent_chunk_id=m.get("parent_chunk_id"),
                vector_score=original.vector_score if original else 0.0,
                keyword_score=original.keyword_score if original else 0.0,
                final_score=original.final_score if original else float(m.get("similarity", 0)),
                retrieval_method=original.retrieval_method if original else "vector",
            ))

        logger.info("parent-child merge applied: %d chunks", len(result))
        return result

    except Exception as exc:
        logger.warning("parent-child merge failed: %s", exc)
        return hits


# ---------------------------------------------------------------------------
# Stage 8: Context packing
# ---------------------------------------------------------------------------

def stage_context_pack(
    hits: list[ChunkResult],
    query: str,
    packer,
    max_tokens: int,
) -> tuple[list[ChunkResult], dict]:
    """Pack context within token budget, dedup, truncate."""
    chunk_dicts = [
        {
            "content": h.content,
            "score": h.final_score,
            "chunk_id": h.chunk_id,
        }
        for h in hits
    ]

    try:
        pack_result = packer.pack(chunk_dicts, query=query, prioritize_by="score")
        packed_ids = {c["chunk_id"] for c in pack_result["packed_chunks"]}
        packed_hits = [h for h in hits if h.chunk_id in packed_ids]

        stats = {
            "total_tokens": pack_result["total_tokens"],
            "dropped_count": pack_result["dropped_count"],
            "dedup_count": pack_result["dedup_count"],
            "input_count": len(hits),
            "output_count": len(packed_hits),
        }
        return packed_hits, stats

    except Exception as exc:
        logger.warning("context packing failed: %s", exc)
        return hits, {"error": str(exc)}
