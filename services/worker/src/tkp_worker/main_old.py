"""入库工作进程。

主流程:
1) 抢占一条待处理任务(queued/retrying)
2) 读取文档版本 object_key
3) 解析 + 切片 + 回写 document_chunks
4) 成功则 completed，失败则 retrying/dead_letter
"""

import json
import hashlib
import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text

from tkp_worker.config import get_settings
from tkp_worker.parsers import default_parser_registry
from tkp_worker.chunker import create_chunker
from tkp_worker.embeddings import create_embedding_service

logger = logging.getLogger("tkp_worker")


def _setup_logging() -> None:
    """初始化日志输出格式与级别。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


def _now_iso() -> str:
    """返回当前 UTC 时间的 ISO 字符串。"""
    return datetime.now(timezone.utc).isoformat()


def _build_minio_client(*, endpoint: str, access_key: str, secret_key: str, secure: bool, region: str | None = None):
    """构建 MinIO 客户端（延迟导入）。"""
    try:
        from minio import Minio
    except ModuleNotFoundError as exc:
        raise RuntimeError("minio backend requires package 'minio'") from exc
    return Minio(
        endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
        region=region,
    )


def _build_oss_bucket(*, endpoint: str, access_key: str, secret_key: str, bucket_name: str, secure: bool):
    """构建阿里云 OSS Bucket 客户端（延迟导入）。"""
    try:
        import oss2
    except ModuleNotFoundError as exc:
        raise RuntimeError("oss backend requires package 'oss2'") from exc

    endpoint_url = endpoint
    if not endpoint_url.startswith("http://") and not endpoint_url.startswith("https://"):
        endpoint_url = f"https://{endpoint_url}" if secure else f"http://{endpoint_url}"
    auth = oss2.Auth(access_key, secret_key)
    return oss2.Bucket(auth, endpoint_url, bucket_name)


def _read_object_bytes(
    *,
    backend: str,
    storage_root: str,
    object_key: str,
    bucket_name: str,
    endpoint: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    secure: bool = False,
    region: str | None = None,
) -> bytes:
    """按后端配置读取对象字节。"""
    if backend == "local":
        path = Path(storage_root).joinpath(object_key)
        if not path.exists():
            raise FileNotFoundError(f"object not found: {path}")
        return path.read_bytes()

    if backend == "minio":
        if not endpoint or not access_key or not secret_key:
            raise RuntimeError("minio backend requires endpoint/access_key/secret_key")
        client = _build_minio_client(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region,
        )
        obj = client.get_object(bucket_name, object_key)
        try:
            return obj.read()
        finally:
            obj.close()
            obj.release_conn()

    if backend == "oss":
        if not endpoint or not access_key or not secret_key:
            raise RuntimeError("oss backend requires endpoint/access_key/secret_key")
        bucket = _build_oss_bucket(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            bucket_name=bucket_name,
            secure=secure,
        )
        return bucket.get_object(object_key).read()

    raise RuntimeError(f"unsupported storage backend: {backend}")


def _read_text_from_object(
    *,
    backend: str,
    storage_root: str,
    object_key: str,
    parser_type: str | None,
    bucket_name: str,
    endpoint: str | None = None,
    access_key: str | None = None,
    secret_key: str | None = None,
    secure: bool = False,
    region: str | None = None,
) -> str:
    """按对象键读取文件并执行智能解析。"""
    payload = _read_object_bytes(
        backend=backend,
        storage_root=storage_root,
        object_key=object_key,
        bucket_name=bucket_name,
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
        region=region,
    )

    # 从 object_key 提取文件名用于格式检测
    filename = object_key.split("/")[-1] if "/" in object_key else object_key

    # 使用智能解析器注册表
    try:
        if default_parser_registry.is_supported(filename):
            text = default_parser_registry.parse(payload, filename)
            logger.info("parsed document: filename=%s, length=%d", filename, len(text))
            return text
        else:
            # 回退到简单文本解析
            logger.warning("unsupported file type, using fallback: %s", filename)
            return payload.decode("utf-8", errors="ignore")
    except Exception as exc:
        logger.exception("parser failed for %s, using fallback", filename)
        return payload.decode("utf-8", errors="ignore")


def _chunk_text(content: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    """使用智能切片器将文本切分为重叠块。"""
    settings = get_settings()
    chunker = create_chunker(chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap)
    return chunker.chunk_text(content)


def _embed_text(content: str, *, embedding_service, dim: int = 1536) -> list[float]:
    """使用 OpenAI embeddings API 生成真实向量。"""
    try:
        return embedding_service.embed_text(content)
    except Exception as exc:
        logger.exception("embedding generation failed, using fallback hash: %s", exc)
        # 回退到哈希向量（保持系统可用性）
        return _embed_text_fallback(content, dim=dim)


def _embed_text_fallback(content: str, *, dim: int = 1536) -> list[float]:
    """使用确定性哈希算法生成向量（回退方案）。"""
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
    """将向量转为 pgvector 字面量字符串。"""
    return "[" + ",".join(f"{value:.6f}" for value in vector) + "]"


def _normalize_metadata(raw: object) -> dict[str, object]:
    """将任意 metadata 入参归一化为字典。"""
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


def _claim_next_job(conn, worker_id: str, lock_timeout_seconds: int) -> dict[str, Any] | None:
    """抢占下一条可执行任务。

    关键点：
    1. `FOR UPDATE SKIP LOCKED` 避免并发工作进程重复领取同一任务。
    2. 允许抢占超时锁，处理工作进程异常退出场景。
    """
    stmt = text(
        """
        WITH candidate AS (
            SELECT id
            FROM ingestion_jobs
            WHERE status IN ('queued', 'retrying')
              AND next_run_at <= now()
              AND (
                  locked_at IS NULL
                  OR locked_at < now() - make_interval(secs => :lock_timeout_seconds)
              )
            ORDER BY created_at
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        UPDATE ingestion_jobs AS j
        SET status = 'processing',
            stage = 'loading',
            progress = 5,
            locked_at = now(),
            locked_by = :worker_id,
            heartbeat_at = now(),
            started_at = COALESCE(started_at, now()),
            attempt_count = j.attempt_count + 1,
            updated_at = now(),
            error = NULL
        FROM candidate
        WHERE j.id = candidate.id
        RETURNING
            j.id,
            j.tenant_id,
            j.workspace_id,
            j.kb_id,
            j.document_id,
            j.document_version_id,
            j.attempt_count,
            j.max_attempts
        """
    )
    row = conn.execute(
        stmt,
        {
            "worker_id": worker_id,
            "lock_timeout_seconds": lock_timeout_seconds,
        },
    ).mappings().first()
    return dict(row) if row else None


def _touch_heartbeat(conn, job_id: UUID, worker_id: str) -> None:
    """刷新任务心跳，标记工作进程仍在处理。"""
    conn.execute(
        text(
            """
            UPDATE ingestion_jobs
            SET heartbeat_at = now(), updated_at = now(), locked_by = :worker_id
            WHERE id = :job_id
            """
        ),
        {"job_id": str(job_id), "worker_id": worker_id},
    )


def _mark_success(conn, job_id: UUID) -> None:
    """将任务标记为完成态。"""
    conn.execute(
        text(
            """
            UPDATE ingestion_jobs
            SET status = 'completed',
                stage = 'completed',
                progress = 100,
                finished_at = now(),
                heartbeat_at = now(),
                locked_at = NULL,
                locked_by = NULL,
                updated_at = now(),
                error = NULL
            WHERE id = :job_id
            """
        ),
        {"job_id": str(job_id)},
    )


def _mark_failure(
    conn,
    *,
    job_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
    attempt_count: int,
    max_attempts: int,
    base_seconds: int,
    max_seconds: int,
    error_message: str,
) -> None:
    """按重试策略处理失败任务。"""
    should_retry = attempt_count < max_attempts
    delay = min(base_seconds * (2 ** max(0, attempt_count - 1)), max_seconds)

    if should_retry:
        # 可重试失败：回退到 retrying 并设置下次执行时间。
        conn.execute(
            text(
                """
                UPDATE ingestion_jobs
                SET status = 'retrying',
                    stage = 'failed',
                    progress = 0,
                    error = :error_message,
                    next_run_at = now() + make_interval(secs => :delay_seconds),
                    heartbeat_at = now(),
                    locked_at = NULL,
                    locked_by = NULL,
                    updated_at = now()
                WHERE id = :job_id
                """
            ),
            {
                "job_id": str(job_id),
                "error_message": error_message,
                "delay_seconds": delay,
            },
        )

        # 将版本与文档状态恢复为 pending，等待重试重新处理。
        conn.execute(
            text(
                """
                UPDATE document_versions
                SET parse_status = 'pending'
                WHERE id = :document_version_id
                """
            ),
            {"document_version_id": str(document_version_id)},
        )
        conn.execute(
            text(
                """
                UPDATE documents
                SET status = 'pending', updated_at = now()
                WHERE id = :document_id
                """
            ),
            {"document_id": str(document_id)},
        )
        return

    # 超过最大重试：进入死信队列，等待人工排查。
    conn.execute(
        text(
            """
            UPDATE ingestion_jobs
            SET status = 'dead_letter',
                stage = 'failed',
                progress = 0,
                error = :error_message,
                finished_at = now(),
                heartbeat_at = now(),
                locked_at = NULL,
                locked_by = NULL,
                updated_at = now()
            WHERE id = :job_id
            """
        ),
        {
            "job_id": str(job_id),
            "error_message": error_message,
        },
    )
    conn.execute(
        text(
            """
            UPDATE document_versions
            SET parse_status = 'failed'
            WHERE id = :document_version_id
            """
        ),
        {"document_version_id": str(document_version_id)},
    )
    conn.execute(
        text(
            """
            UPDATE documents
            SET status = 'failed', updated_at = now()
            WHERE id = :document_id
            """
        ),
        {"document_id": str(document_id)},
    )


def _process_job(
    conn,
    job: dict[str, Any],
    *,
    storage_backend: str,
    storage_root: str,
    storage_bucket: str,
    storage_endpoint: str | None,
    storage_access_key: str | None,
    storage_secret_key: str | None,
    storage_secure: bool,
    storage_region: str | None,
    worker_id: str,
) -> None:
    """执行单条入库任务。"""
    job_id: UUID = job["id"]
    document_id: UUID = job["document_id"]
    document_version_id: UUID = job["document_version_id"]

    # 通过版本表反查对象键与解析器类型。
    row = conn.execute(
        text(
            """
            SELECT d.tenant_id, d.workspace_id, d.kb_id, d.metadata AS document_metadata, dv.object_key, dv.parser_type
            FROM document_versions dv
            JOIN documents d ON d.id = dv.document_id
            WHERE dv.id = :document_version_id
            """
        ),
        {"document_version_id": str(document_version_id)},
    ).mappings().first()
    if not row:
        raise RuntimeError(f"document version not found: {document_version_id}")

    tenant_id: UUID = row["tenant_id"]
    workspace_id: UUID = row["workspace_id"]
    kb_id: UUID = row["kb_id"]
    document_metadata = _normalize_metadata(row["document_metadata"])
    object_key: str | None = row["object_key"]
    parser_type: str | None = row["parser_type"]

    if not object_key:
        raise RuntimeError("document version object_key is empty")

    # 先更新文档状态，便于前台展示“处理中”。
    conn.execute(
        text(
            """
            UPDATE documents
            SET status = 'processing', updated_at = now()
            WHERE id = :document_id
            """
        ),
        {"document_id": str(document_id)},
    )

    _touch_heartbeat(conn, job_id, worker_id)
    content = _read_text_from_object(
        backend=storage_backend,
        storage_root=storage_root,
        object_key=object_key,
        parser_type=parser_type,
        bucket_name=storage_bucket,
        endpoint=storage_endpoint,
        access_key=storage_access_key,
        secret_key=storage_secret_key,
        secure=storage_secure,
        region=storage_region,
    )

    conn.execute(
        text(
            """
            UPDATE ingestion_jobs
            SET stage = 'parsing', progress = 20, heartbeat_at = now(), updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": str(job_id)},
    )

    conn.execute(
        text(
            """
            UPDATE document_versions
            SET parse_status = 'pending'
            WHERE id = :document_version_id
            """
        ),
        {"document_version_id": str(document_version_id)},
    )

    chunks = _chunk_text(content)
    if not chunks:
        raise RuntimeError("document has no parseable content")

    conn.execute(
        text(
            """
            UPDATE ingestion_jobs
            SET stage = 'chunking', progress = 55, heartbeat_at = now(), updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": str(job_id)},
    )

    # 重跑时先清理同版本旧切片，保证幂等覆盖。
    conn.execute(
        text(
            """
            DELETE FROM chunk_embeddings
            WHERE chunk_id IN (
                SELECT id FROM document_chunks WHERE document_version_id = :document_version_id
            )
            """
        ),
        {"document_version_id": str(document_version_id)},
    )
    conn.execute(
        text("DELETE FROM document_chunks WHERE document_version_id = :document_version_id"),
        {"document_version_id": str(document_version_id)},
    )

    insert_stmt = text(
        """
        INSERT INTO document_chunks (
            id,
            tenant_id,
            workspace_id,
            kb_id,
            document_id,
            document_version_id,
            chunk_no,
            parent_chunk_id,
            title_path,
            content,
            token_count,
            metadata,
            embedding,
            embedding_model,
            embedded_at,
            created_at
        ) VALUES (
            :id,
            :tenant_id,
            :workspace_id,
            :kb_id,
            :document_id,
            :document_version_id,
            :chunk_no,
            NULL,
            NULL,
            :content,
            :token_count,
            CAST(:metadata AS jsonb),
            CAST(:embedding AS vector),
            :embedding_model,
            now(),
            now()
        )
        """
    )

    embedding_model = (
        conn.execute(
            text(
                """
                SELECT embedding_model
                FROM knowledge_bases
                WHERE id = :kb_id
                LIMIT 1
                """
            ),
            {"kb_id": str(kb_id)},
        ).scalar_one_or_none()
        or "local-hash-1536"
    )

    conn.execute(
        text(
            """
            UPDATE ingestion_jobs
            SET stage = 'embedding', progress = 75, heartbeat_at = now(), updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": str(job_id)},
    )

    # 初始化 embedding 服务
    settings = get_settings()
    embedding_service = create_embedding_service(
        api_key=settings.openai_api_key,
        model=settings.openai_embedding_model,
    )

    # 批量生成向量（提升性能）
    logger.info("generating embeddings for %d chunks", len(chunks))
    try:
        embeddings = embedding_service.embed_batch(chunks)
    except Exception as exc:
        logger.exception("batch embedding failed, falling back to individual: %s", exc)
        embeddings = [_embed_text(chunk, embedding_service=embedding_service) for chunk in chunks]

    # 插入切片和向量
    for i, (chunk, embedding) in enumerate(zip(chunks, embeddings), start=1):
        chunk_id = str(uuid4())
        conn.execute(
            insert_stmt,
            {
                "id": chunk_id,
                "tenant_id": str(tenant_id),
                "workspace_id": str(workspace_id),
                "kb_id": str(kb_id),
                "document_id": str(document_id),
                "document_version_id": str(document_version_id),
                "chunk_no": i,
                "content": chunk,
                "token_count": embedding_service.count_tokens(chunk),
                "metadata": json.dumps(document_metadata, ensure_ascii=False),
                "embedding": _vector_to_pg_literal(embedding),
                "embedding_model": embedding_model,
            },
        )

    conn.execute(
        text(
            """
            UPDATE ingestion_jobs
            SET stage = 'indexing', progress = 90, heartbeat_at = now(), updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": str(job_id)},
    )

    # 切片写入成功后，刷新版本与文档状态。
    conn.execute(
        text(
            """
            UPDATE document_versions
            SET parse_status = 'success'
            WHERE id = :document_version_id
            """
        ),
        {"document_version_id": str(document_version_id)},
    )
    conn.execute(
        text(
            """
            UPDATE documents
            SET status = 'ready', updated_at = now()
            WHERE id = :document_id
            """
        ),
        {"document_id": str(document_id)},
    )


def main() -> None:
    """工作进程主循环。"""
    _setup_logging()
    settings = get_settings()
    engine = create_engine(settings.database_url, future=True, pool_pre_ping=True)

    logger.info("worker started worker_id=%s at=%s", settings.worker_id, _now_iso())

    while True:
        claimed: dict[str, Any] | None = None
        try:
            with engine.begin() as conn:
                claimed = _claim_next_job(
                    conn,
                    worker_id=settings.worker_id,
                    lock_timeout_seconds=settings.worker_lock_timeout_seconds,
                )

            if not claimed:
                # 没有可执行任务时短暂休眠，降低数据库轮询压力。
                time.sleep(settings.worker_poll_interval_seconds)
                continue

            logger.info(
                "claimed job id=%s document_id=%s version_id=%s attempt=%s/%s",
                claimed["id"],
                claimed["document_id"],
                claimed["document_version_id"],
                claimed["attempt_count"],
                claimed["max_attempts"],
            )

            with engine.begin() as conn:
                _process_job(
                    conn,
                    claimed,
                    storage_backend=settings.storage_backend,
                    storage_root=settings.storage_root,
                    storage_bucket=settings.storage_bucket,
                    storage_endpoint=settings.storage_endpoint,
                    storage_access_key=settings.storage_access_key,
                    storage_secret_key=settings.storage_secret_key,
                    storage_secure=settings.storage_secure,
                    storage_region=settings.storage_region,
                    worker_id=settings.worker_id,
                )
                _mark_success(conn, claimed["id"])

            logger.info("completed job id=%s", claimed["id"])
        except KeyboardInterrupt:
            logger.info("worker stopped")
            return
        except Exception as exc:
            if not claimed:
                # 抢占前出现异常，记录后进入下一轮轮询。
                logger.exception("worker loop error without claimed job")
                time.sleep(settings.worker_poll_interval_seconds)
                continue

            err = str(exc)[:2000]
            logger.exception("job failed id=%s error=%s", claimed["id"], err)
            with engine.begin() as conn:
                _mark_failure(
                    conn,
                    job_id=claimed["id"],
                    document_id=claimed["document_id"],
                    document_version_id=claimed["document_version_id"],
                    attempt_count=claimed["attempt_count"],
                    max_attempts=claimed["max_attempts"],
                    base_seconds=settings.ingestion_retry_base_seconds,
                    max_seconds=settings.ingestion_retry_max_seconds,
                    error_message=err,
                )


if __name__ == "__main__":
    main()
