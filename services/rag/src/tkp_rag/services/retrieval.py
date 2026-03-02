"""RAG 检索与回答生成服务。"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


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


def _parse_metadata(raw: object) -> dict[str, object]:
    """将 metadata 字段归一化为 dict。"""
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


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
    with_citations: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "chunk_id": str(chunk_id),
        "document_id": str(document_id),
        "document_version_id": str(document_version_id),
        "kb_id": str(kb_id),
        "chunk_no": int(chunk_no),
        "title_path": title_path,
        "score": int(score),
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
    first_token = query.split()[0] if query.split() else query
    sql = text(
        """
        SELECT
            c.id AS chunk_id,
            c.document_id,
            c.document_version_id,
            c.kb_id,
            c.chunk_no,
            c.title_path,
            c.content,
            c.metadata
        FROM document_chunks c
        JOIN documents d ON d.id = c.document_id
        WHERE c.tenant_id = :tenant_id
          AND c.kb_id IN :kb_ids
          AND d.status = 'ready'
          AND (
            LOWER(c.content) LIKE :query_like
            OR LOWER(c.content) LIKE :token_like
          )
        ORDER BY c.created_at DESC
        LIMIT :limit
        """
    ).bindparams(bindparam("kb_ids", expanding=True))
    rows = db.execute(
        sql,
        {
            "tenant_id": str(tenant_id),
            "kb_ids": [str(item) for item in kb_ids],
            "query_like": f"%{query.lower()}%",
            "token_like": f"%{first_token.lower()}%",
            "limit": max(top_k * 20, 100),
        },
    ).mappings()

    results: list[dict[str, object]] = []
    for row in rows:
        content = str(row["content"] or "")
        metadata = _parse_metadata(row["metadata"])
        if not _matches_filters(metadata, filters):
            continue
        score = _score_keyword_match(content, query, first_token)
        if score <= 0:
            continue
        results.append(
            _build_hit(
                chunk_id=row["chunk_id"],
                document_id=row["document_id"],
                document_version_id=row["document_version_id"],
                kb_id=row["kb_id"],
                chunk_no=int(row["chunk_no"]),
                title_path=row["title_path"],
                snippet=content[:300],
                metadata=metadata,
                score=score,
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

    rows = db.execute(sql, params).mappings()
    results: list[dict[str, object]] = []
    for row in rows:
        metadata = _parse_metadata(row["metadata"])
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
                chunk_no=int(row["chunk_no"]),
                title_path=row["title_path"],
                snippet=str(row["snippet"] or ""),
                metadata=metadata,
                score=score,
                with_citations=with_citations,
            )
        )
    results.sort(key=lambda item: int(item["score"]), reverse=True)
    return results[:top_k]


def search_chunks(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID],
    query: str,
    top_k: int,
    filters: dict[str, object] | None = None,
    with_citations: bool = True,
) -> list[dict[str, object]]:
    """检索切片（向量优先，关键词兜底）。"""
    if not kb_ids:
        return []

    normalized_filters = filters or {}
    dialect = db.get_bind().dialect.name
    vector_hits: list[dict[str, object]] = []
    if dialect == "postgresql":
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
            vector_hits = []

    if len(vector_hits) >= top_k:
        return vector_hits[:top_k]

    keyword_hits = _search_keyword_chunks(
        db,
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        query=query,
        top_k=top_k,
        filters=normalized_filters,
        with_citations=with_citations,
    )
    merged: list[dict[str, object]] = []
    seen_chunk_ids: set[str] = set()
    for hit in vector_hits + keyword_hits:
        chunk_id = str(hit["chunk_id"])
        if chunk_id in seen_chunk_ids:
            continue
        seen_chunk_ids.add(chunk_id)
        merged.append(hit)

    merged.sort(key=lambda item: int(item["score"]), reverse=True)
    return merged[:top_k]


def generate_answer(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID],
    question: str,
    top_k: int,
    filters: dict[str, object] | None = None,
    with_citations: bool = True,
) -> dict[str, object]:
    """生成问答回复。"""
    hits = search_chunks(
        db,
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        query=question,
        top_k=top_k,
        filters=filters or {},
        with_citations=with_citations,
    )

    if not hits:
        answer_text = f"未检索到与问题“{question}”相关的知识片段。"
    else:
        bullet_lines = [f"- {hit['snippet']}" for hit in hits[:3]]
        answer_text = "基于知识库检索到以下信息:\n" + "\n".join(bullet_lines)

    citations = [
        {
            "document_id": hit["document_id"],
            "chunk_id": hit["chunk_id"],
            "document_version_id": hit["document_version_id"],
        }
        for hit in hits
    ]
    prompt_tokens = max(1, len(question.split()))
    completion_tokens = max(1, len(answer_text.split()))
    return {
        "answer": answer_text,
        "citations": citations,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }

