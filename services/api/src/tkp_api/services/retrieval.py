"""检索实现服务。"""

from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session


def search_chunks(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID],
    query: str,
    top_k: int,
) -> list[dict[str, object]]:
    """基于简单文本匹配检索切片。

    说明：这是便于联调的基础实现，后续可替换为向量检索 + 重排。
    """
    if not kb_ids:
        # 没有任何可读知识库时直接返回空集合。
        return []

    # 使用参数化 SQL，避免拼接导致的注入风险。
    sql = text(
        """
        SELECT
            c.id AS chunk_id,
            c.document_id,
            c.document_version_id,
            c.kb_id,
            LEFT(c.content, 300) AS snippet,
            CASE
                WHEN c.content ILIKE :exact_pattern THEN 100
                WHEN c.content ILIKE :token_pattern THEN 70
                ELSE 10
            END AS score
        FROM document_chunks c
        WHERE c.tenant_id = :tenant_id
          AND c.kb_id IN :kb_ids
          AND (
                c.content ILIKE :exact_pattern
                OR c.content ILIKE :token_pattern
          )
        ORDER BY score DESC, c.created_at DESC
        LIMIT :top_k
        """
    ).bindparams(bindparam("kb_ids", expanding=True))

    # 兜底首词匹配，减轻全量短语匹配召回不足的问题。
    first_token = query.split()[0] if query.split() else query
    rows = db.execute(
        sql,
        {
            "tenant_id": tenant_id,
            "kb_ids": kb_ids,
            "exact_pattern": f"%{query}%",
            "token_pattern": f"%{first_token}%",
            "top_k": top_k,
        },
    ).mappings().all()

    return [
        {
            "chunk_id": row["chunk_id"],
            "document_id": row["document_id"],
            "document_version_id": row["document_version_id"],
            "kb_id": row["kb_id"],
            "score": int(row["score"]),
            "snippet": row["snippet"],
        }
        for row in rows
    ]
