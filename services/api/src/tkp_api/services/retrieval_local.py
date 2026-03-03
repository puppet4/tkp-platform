"""检索实现服务。"""

import hashlib
import json
import math
import re
from uuid import UUID

from sqlalchemy import bindparam, or_, select, text
from sqlalchemy.orm import Session

from tkp_api.models.enums import DocumentStatus
from tkp_api.models.knowledge import Document, DocumentChunk

_DEFAULT_MIN_SCORE_BY_STRATEGY: dict[str, int] = {
    "hybrid": 120,
    "vector": 120,
    "keyword": 500,
}
_QUERY_REWRITE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("退款", ("退费", "refund")),
    ("退费", ("退款", "refund")),
    ("登录", ("signin", "login")),
    ("权限", ("授权", "permission")),
)
_WORD_RE = re.compile(r"[a-z0-9_]+")


def _embed_text(content: str, *, dim: int = 1536) -> list[float]:
    """使用确定性哈希算法生成文本向量。"""
    normalized = " ".join(content.strip().lower().split())
    if not normalized:
        return [0.0] * dim

    base_tokens = [token for token in normalized.split(" ") if token]
    if len(base_tokens) < 8:
        compact = normalized.replace(" ", "")
        base_tokens.extend(compact[i : i + 2] for i in range(max(0, len(compact) - 1)))
    if not base_tokens:
        base_tokens = [normalized]

    vector = [0.0] * dim
    for pos, token in enumerate(base_tokens[:1024], start=1):
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        weight = 1.0 / math.sqrt(pos)
        for offset in (0, 4, 8, 12, 16, 20):
            idx = int.from_bytes(digest[offset : offset + 2], "big") % dim
            sign = -1.0 if (digest[offset + 2] & 1) else 1.0
            magnitude = 0.2 + (digest[offset + 3] / 255.0)
            vector[idx] += sign * magnitude * weight

    norm = math.sqrt(sum(value * value for value in vector))
    if norm <= 0:
        return [0.0] * dim
    return [value / norm for value in vector]


def _vector_to_pg_literal(vector: list[float]) -> str:
    """将向量转为 pgvector 字面量。"""
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


def _normalize_query(text_value: str) -> str:
    return " ".join((text_value or "").strip().split())


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _extract_terms(text_value: str) -> list[str]:
    normalized = (text_value or "").strip().lower()
    if not normalized:
        return []

    terms: list[str] = []
    terms.extend(token for token in _WORD_RE.findall(normalized) if len(token) >= 2)

    for part in normalized.split():
        compact = part.strip()
        if len(compact) >= 2 and any(ord(ch) > 127 for ch in compact):
            terms.append(compact)

    if " " not in normalized and len(normalized) >= 2 and any(ord(ch) > 127 for ch in normalized):
        terms.append(normalized)

    return _dedupe_keep_order(terms)


def _rewrite_query(query: str) -> dict[str, object]:
    original = _normalize_query(query)
    lowered = original.lower()
    additions: list[str] = []

    for marker, aliases in _QUERY_REWRITE_RULES:
        if marker in original:
            for alias in aliases:
                if alias.lower() not in lowered:
                    additions.append(alias)

    rewritten = original
    if additions:
        rewritten = f"{original} {' '.join(_dedupe_keep_order(additions))}"

    return {
        "original_query": original,
        "rewritten_query": rewritten,
        "rewrite_applied": rewritten != original,
        "query_terms": _extract_terms(rewritten),
    }


def _resolve_effective_min_score(strategy: str, requested_min_score: int) -> int:
    normalized_requested = max(0, min(1000, int(requested_min_score)))
    if normalized_requested > 0:
        return normalized_requested
    return _DEFAULT_MIN_SCORE_BY_STRATEGY.get(strategy, 120)


def _matches_filters(metadata: dict[str, object], filters: dict[str, object]) -> bool:
    """判断切片 metadata 是否满足过滤条件。"""
    if not filters:
        return True
    for key, expected in filters.items():
        if key not in metadata:
            return False
        actual = metadata.get(key)
        if isinstance(expected, (dict, list)):
            if actual != expected:
                return False
            continue
        if str(actual) != str(expected):
            return False
    return True


def _collect_matched_terms(*, content: str, title_path: str | None, query_terms: list[str]) -> list[str]:
    haystack = f"{content}\n{title_path or ''}".lower()
    matched = [term for term in query_terms if term and term in haystack]
    return _dedupe_keep_order(matched)[:8]


def _score_keyword_match(content: str, query: str, first_token: str) -> int:
    """对关键词匹配结果进行打分。"""
    lower_content = content.lower()
    q = query.lower().strip()
    token = first_token.lower().strip()
    if q and q in lower_content:
        return 880
    if token and token in lower_content:
        return 640
    return 0


def _build_hit(
    *,
    chunk_id: UUID | str,
    document_id: UUID | str,
    document_version_id: UUID | str,
    kb_id: UUID | str,
    chunk_no: int,
    title_path: str | None,
    snippet: str,
    metadata: dict[str, object],
    score: int,
    match_type: str,
    reason: str,
    matched_terms: list[str],
    score_breakdown: dict[str, int],
    with_citations: bool,
) -> dict[str, object]:
    """统一组装命中记录。"""
    payload: dict[str, object] = {
        "chunk_id": str(chunk_id),
        "document_id": str(document_id),
        "document_version_id": str(document_version_id),
        "kb_id": str(kb_id),
        "chunk_no": int(chunk_no),
        "title_path": title_path,
        "score": int(score),
        "match_type": match_type,
        "snippet": snippet,
        "metadata": metadata,
        "reason": reason,
        "matched_terms": matched_terms,
        "score_breakdown": score_breakdown,
    }
    if with_citations:
        payload["citation"] = {
            "chunk_id": str(chunk_id),
            "document_id": str(document_id),
            "document_version_id": str(document_version_id),
            "kb_id": str(kb_id),
            "chunk_no": int(chunk_no),
            "title_path": title_path,
        }
    else:
        payload["citation"] = None
    return payload


def _search_keyword_chunks(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID],
    query: str,
    query_terms: list[str],
    top_k: int,
    filters: dict[str, object],
    with_citations: bool,
) -> list[dict[str, object]]:
    """关键词检索回退路径（兼容 sqlite）。"""
    first_token = query.split()[0] if query.split() else query
    stmt = (
        select(DocumentChunk)
        .join(Document, Document.id == DocumentChunk.document_id)
        .where(DocumentChunk.tenant_id == tenant_id)
        .where(DocumentChunk.kb_id.in_(kb_ids))
        .where(Document.status == DocumentStatus.READY)
        .where(
            or_(
                DocumentChunk.content.ilike(f"%{query}%"),
                DocumentChunk.content.ilike(f"%{first_token}%"),
            )
        )
        .order_by(DocumentChunk.created_at.desc())
        .limit(max(top_k * 20, 100))
    )
    chunks = db.execute(stmt).scalars().all()

    results: list[dict[str, object]] = []
    for chunk in chunks:
        metadata = chunk.metadata_ or {}
        if not _matches_filters(metadata, filters):
            continue

        keyword_score = _score_keyword_match(chunk.content, query, first_token)
        if keyword_score <= 0:
            continue

        matched_terms = _collect_matched_terms(
            content=chunk.content,
            title_path=chunk.title_path,
            query_terms=query_terms,
        )
        reason = "关键词精确命中" if query.lower().strip() in chunk.content.lower() else "关键词分词命中"
        score_breakdown = {
            "vector_score": 0,
            "keyword_score": int(keyword_score),
            "rerank_bonus": 0,
            "final_score": int(keyword_score),
        }
        results.append(
            _build_hit(
                chunk_id=chunk.id,
                document_id=chunk.document_id,
                document_version_id=chunk.document_version_id,
                kb_id=chunk.kb_id,
                chunk_no=chunk.chunk_no,
                title_path=chunk.title_path,
                snippet=chunk.content[:300],
                metadata=metadata,
                score=keyword_score,
                match_type="keyword",
                reason=reason,
                matched_terms=matched_terms,
                score_breakdown=score_breakdown,
                with_citations=with_citations,
            )
        )

    results.sort(key=lambda item: int(item["score"]), reverse=True)
    return results[:top_k]


def _search_vector_chunks_postgres(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID],
    query: str,
    query_terms: list[str],
    top_k: int,
    filters: dict[str, object],
    with_citations: bool,
) -> list[dict[str, object]]:
    """PostgreSQL + pgvector 向量检索路径。"""
    filter_sql = ""
    params: dict[str, object] = {
        "tenant_id": str(tenant_id),
        "kb_ids": [str(kb_id) for kb_id in kb_ids],
        "query_vector": _vector_to_pg_literal(_embed_text(query)),
        "limit": max(top_k * 5, top_k),
    }
    if filters:
        filter_sql = "AND c.metadata @> CAST(:metadata_filter AS jsonb)"
        params["metadata_filter"] = json.dumps(filters, ensure_ascii=False)

    sql = text(
        f"""
        SELECT
            c.id AS chunk_id,
            c.document_id,
            c.document_version_id,
            c.kb_id,
            c.chunk_no,
            c.title_path,
            LEFT(c.content, 300) AS snippet,
            c.metadata AS metadata,
            (e.vector <=> CAST(:query_vector AS vector)) AS distance
        FROM chunk_embeddings e
        JOIN document_chunks c ON c.id = e.chunk_id
        JOIN documents d ON d.id = c.document_id
        WHERE c.tenant_id = :tenant_id
          AND c.kb_id IN :kb_ids
          AND d.status = 'ready'
          {filter_sql}
        ORDER BY distance ASC, c.created_at DESC
        LIMIT :limit
        """
    ).bindparams(bindparam("kb_ids", expanding=True))

    rows = db.execute(sql, params).mappings().all()
    results: list[dict[str, object]] = []
    for row in rows:
        metadata = row["metadata"] or {}
        if not _matches_filters(metadata, filters):
            continue

        distance = float(row["distance"]) if row["distance"] is not None else 1.0
        similarity = max(0.0, 1.0 - distance)
        vector_score = int(similarity * 1000)
        matched_terms = _collect_matched_terms(
            content=str(row["snippet"] or ""),
            title_path=row["title_path"],
            query_terms=query_terms,
        )
        score_breakdown = {
            "vector_score": int(vector_score),
            "keyword_score": 0,
            "rerank_bonus": 0,
            "final_score": int(vector_score),
        }
        results.append(
            _build_hit(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                document_version_id=row["document_version_id"],
                kb_id=row["kb_id"],
                chunk_no=row["chunk_no"],
                title_path=row["title_path"],
                snippet=row["snippet"] or "",
                metadata=metadata,
                score=vector_score,
                match_type="vector",
                reason="向量语义召回命中",
                matched_terms=matched_terms,
                score_breakdown=score_breakdown,
                with_citations=with_citations,
            )
        )
    results.sort(key=lambda item: int(item["score"]), reverse=True)
    return results[:top_k]


def _normalize_retrieval_strategy(value: str) -> str:
    normalized = (value or "hybrid").strip().lower()
    if normalized not in {"hybrid", "vector", "keyword"}:
        return "hybrid"
    return normalized


def _merge_hybrid_hits(
    vector_hits: list[dict[str, object]],
    keyword_hits: list[dict[str, object]],
) -> list[dict[str, object]]:
    merged: dict[str, dict[str, object]] = {}
    for hit in vector_hits:
        merged[str(hit["chunk_id"])] = dict(hit)

    for hit in keyword_hits:
        chunk_id = str(hit["chunk_id"])
        existing = merged.get(chunk_id)
        if existing is None:
            merged[chunk_id] = dict(hit)
            continue

        existing_score = int(existing.get("score") or 0)
        keyword_score = int(hit.get("score") or 0)
        merged_score = min(1000, max(existing_score, keyword_score) + 60)
        existing["score"] = merged_score
        existing["match_type"] = "hybrid"
        existing["reason"] = "向量+关键词融合命中"
        if not existing.get("snippet"):
            existing["snippet"] = hit.get("snippet")
        if existing.get("metadata") in (None, {}):
            existing["metadata"] = hit.get("metadata")
        if existing.get("citation") is None and hit.get("citation") is not None:
            existing["citation"] = hit["citation"]

        merged_terms = _dedupe_keep_order(
            list(existing.get("matched_terms") or []) + list(hit.get("matched_terms") or [])
        )
        existing["matched_terms"] = merged_terms

        breakdown = dict(existing.get("score_breakdown") or {})
        hit_breakdown = dict(hit.get("score_breakdown") or {})
        breakdown["vector_score"] = int(breakdown.get("vector_score") or 0)
        breakdown["keyword_score"] = max(
            int(breakdown.get("keyword_score") or 0),
            int(hit_breakdown.get("keyword_score") or keyword_score),
        )
        breakdown["rerank_bonus"] = int(breakdown.get("rerank_bonus") or 0)
        breakdown["final_score"] = merged_score
        existing["score_breakdown"] = breakdown

    merged_hits = list(merged.values())
    merged_hits.sort(key=lambda item: int(item["score"]), reverse=True)
    return merged_hits


def _apply_rerank(hits: list[dict[str, object]], *, rewritten_query: str, query_terms: list[str]) -> tuple[list[dict[str, object]], bool]:
    rerank_applied = False
    rewritten_lower = rewritten_query.lower().strip()

    for hit in hits:
        snippet = str(hit.get("snippet") or "")
        title_path = str(hit.get("title_path") or "")
        metadata = hit.get("metadata") if isinstance(hit.get("metadata"), dict) else {}
        matched_terms = list(hit.get("matched_terms") or [])

        bonus = 0
        if rewritten_lower and rewritten_lower in snippet.lower():
            bonus += 30
        bonus += min(30, len(matched_terms) * 8)
        if any(term in title_path.lower() for term in query_terms):
            bonus += 20
        if isinstance(metadata, dict) and metadata.get("source") == "policy":
            bonus += 5

        if bonus > 0:
            rerank_applied = True

        current_score = int(hit.get("score") or 0)
        final_score = min(1000, current_score + bonus)
        hit["score"] = final_score

        breakdown = dict(hit.get("score_breakdown") or {})
        breakdown["vector_score"] = int(breakdown.get("vector_score") or 0)
        breakdown["keyword_score"] = int(breakdown.get("keyword_score") or 0)
        breakdown["rerank_bonus"] = int(breakdown.get("rerank_bonus") or 0) + bonus
        breakdown["final_score"] = final_score
        hit["score_breakdown"] = breakdown

        reason = str(hit.get("reason") or "相关性命中")
        if bonus > 0 and "重排" not in reason:
            reason = f"{reason} + 重排增强"
        hit["reason"] = reason

    hits.sort(key=lambda item: int(item["score"]), reverse=True)
    return hits, rerank_applied


def search_chunks_detailed(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID],
    query: str,
    top_k: int,
    filters: dict[str, object] | None = None,
    with_citations: bool = True,
    retrieval_strategy: str = "hybrid",
    min_score: int = 0,
) -> dict[str, object]:
    """检索切片（向量优先，关键词兜底）并返回解释信息。"""
    rewrite_info = _rewrite_query(query)
    normalized_strategy = _normalize_retrieval_strategy(retrieval_strategy)
    effective_min_score = _resolve_effective_min_score(normalized_strategy, min_score)
    normalized_filters = filters or {}
    query_terms = list(rewrite_info.get("query_terms") or [])

    if not kb_ids:
        return {
            "hits": [],
            "query_rewrite": {
                "original_query": rewrite_info["original_query"],
                "rewritten_query": rewrite_info["rewritten_query"],
                "rewrite_applied": rewrite_info["rewrite_applied"],
            },
            "effective_min_score": effective_min_score,
            "rerank_applied": False,
        }

    vector_hits: list[dict[str, object]] = []
    dialect = db.get_bind().dialect.name
    original_query = str(rewrite_info["original_query"])
    rewritten_query = str(rewrite_info["rewritten_query"])

    if normalized_strategy in {"hybrid", "vector"} and dialect == "postgresql":
        try:
            vector_hits = _search_vector_chunks_postgres(
                db,
                tenant_id=tenant_id,
                kb_ids=kb_ids,
                query=rewritten_query,
                query_terms=query_terms,
                top_k=top_k,
                filters=normalized_filters,
                with_citations=with_citations,
            )
        except Exception:
            vector_hits = []

    keyword_hits: list[dict[str, object]] = []
    if normalized_strategy == "keyword" or (normalized_strategy == "hybrid" and len(vector_hits) < top_k):
        keyword_hits = _search_keyword_chunks(
            db,
            tenant_id=tenant_id,
            kb_ids=kb_ids,
            query=original_query,
            query_terms=query_terms,
            top_k=top_k,
            filters=normalized_filters,
            with_citations=with_citations,
        )

    if normalized_strategy == "vector":
        merged = vector_hits
    elif normalized_strategy == "keyword":
        merged = keyword_hits
    else:
        merged = _merge_hybrid_hits(vector_hits, keyword_hits)

    reranked_hits, rerank_applied = _apply_rerank(
        merged,
        rewritten_query=rewritten_query,
        query_terms=query_terms,
    )
    filtered = [hit for hit in reranked_hits if int(hit["score"]) >= effective_min_score]

    return {
        "hits": filtered[:top_k],
        "query_rewrite": {
            "original_query": rewrite_info["original_query"],
            "rewritten_query": rewrite_info["rewritten_query"],
            "rewrite_applied": rewrite_info["rewrite_applied"],
        },
        "effective_min_score": effective_min_score,
        "rerank_applied": rerank_applied,
    }


def search_chunks(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID],
    query: str,
    top_k: int,
    filters: dict[str, object] | None = None,
    with_citations: bool = True,
    retrieval_strategy: str = "hybrid",
    min_score: int = 0,
) -> list[dict[str, object]]:
    """检索切片（兼容旧调用签名，仅返回 hits 列表）。"""
    detailed = search_chunks_detailed(
        db,
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        query=query,
        top_k=top_k,
        filters=filters,
        with_citations=with_citations,
        retrieval_strategy=retrieval_strategy,
        min_score=min_score,
    )
    return list(detailed["hits"])
