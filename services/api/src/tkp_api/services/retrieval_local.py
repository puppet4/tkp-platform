"""检索实现服务。"""

import hashlib
import json
import math
from uuid import UUID

from sqlalchemy import bindparam, or_, select, text
from sqlalchemy.orm import Session

from tkp_api.models.enums import DocumentStatus
from tkp_api.models.knowledge import Document, DocumentChunk


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
        score = _score_keyword_match(chunk.content, query, first_token)
        if score <= 0:
            continue
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
                score=score,
                match_type="keyword",
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
        score = int(similarity * 1000)
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
                score=score,
                match_type="vector",
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
        existing["score"] = min(1000, max(existing_score, keyword_score) + 60)
        existing["match_type"] = "hybrid"
        if not existing.get("snippet"):
            existing["snippet"] = hit.get("snippet")
        if existing.get("metadata") in (None, {}):
            existing["metadata"] = hit.get("metadata")
        if existing.get("citation") is None and hit.get("citation") is not None:
            existing["citation"] = hit["citation"]

    merged_hits = list(merged.values())
    merged_hits.sort(key=lambda item: int(item["score"]), reverse=True)
    return merged_hits


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
    """检索切片（向量优先，关键词兜底）。"""
    if not kb_ids:
        return []

    normalized_strategy = _normalize_retrieval_strategy(retrieval_strategy)
    normalized_min_score = max(0, min(1000, int(min_score)))
    normalized_filters = filters or {}
    dialect = db.get_bind().dialect.name
    vector_hits: list[dict[str, object]] = []
    if normalized_strategy in {"hybrid", "vector"} and dialect == "postgresql":
        try:
            vector_hits = _search_vector_chunks_postgres(
                db,
                tenant_id=tenant_id,
                kb_ids=kb_ids,
                query=query,
                top_k=top_k,
                filters=normalized_filters,
                with_citations=with_citations,
            )
        except Exception:
            # 向量查询异常时降级到关键词路径，保证接口可用性。
            vector_hits = []

    keyword_hits: list[dict[str, object]] = []
    if normalized_strategy == "keyword" or (
        normalized_strategy == "hybrid" and len(vector_hits) < top_k
    ):
        keyword_hits = _search_keyword_chunks(
            db,
            tenant_id=tenant_id,
            kb_ids=kb_ids,
            query=query,
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

    filtered = [hit for hit in merged if int(hit["score"]) >= normalized_min_score]
    return filtered[:top_k]
