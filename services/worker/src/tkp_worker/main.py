"""改进的入库工作进程 - 集成真实文档解析和 OpenAI embeddings。

主要改进:
1. 支持 PDF、Word、PowerPoint 等多种格式解析
2. 使用 OpenAI embeddings API 生成真实向量
3. 智能文本切片，保持段落完整性
4. 将向量存储到 document_chunks.embedding 列
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import create_engine, text
from tkp_worker.chunker import create_chunker
from tkp_worker.config import get_settings
from tkp_worker.embeddings import create_embedding_service
from tkp_worker.parsers import default_parser_registry

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


def _read_object_bytes_from_storage(
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
    """从存储后端读取对象字节。"""
    from pathlib import Path

    if backend == "local":
        path = Path(storage_root).joinpath(object_key)
        if not path.exists():
            raise FileNotFoundError(f"object not found: {path}")
        return path.read_bytes()

    if backend == "minio":
        if not endpoint or not access_key or not secret_key:
            raise RuntimeError("minio backend requires endpoint/access_key/secret_key")
        try:
            from minio import Minio
        except ImportError as exc:
            raise RuntimeError("minio backend requires 'minio' package") from exc

        client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure, region=region)
        obj = client.get_object(bucket_name, object_key)
        try:
            return obj.read()
        finally:
            obj.close()
            obj.release_conn()

    if backend == "oss":
        if not endpoint or not access_key or not secret_key:
            raise RuntimeError("oss backend requires endpoint/access_key/secret_key")
        try:
            import oss2
        except ImportError as exc:
            raise RuntimeError("oss backend requires 'oss2' package") from exc

        endpoint_url = endpoint
        if not endpoint_url.startswith("http://") and not endpoint_url.startswith("https://"):
            endpoint_url = f"https://{endpoint_url}" if secure else f"http://{endpoint_url}"
        auth = oss2.Auth(access_key, secret_key)
        bucket = oss2.Bucket(auth, endpoint_url, bucket_name)
        return bucket.get_object(object_key).read()

    raise ValueError(f"unsupported storage backend: {backend}")


def _extract_filename_from_key(object_key: str) -> str:
    """从对象键中提取文件名。"""
    return object_key.split("/")[-1] if "/" in object_key else object_key


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
    """抢占下一条可执行任务。"""
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
    """刷新任务心跳。"""
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
    error_lower = error_message.lower()
    non_retryable_markers = (
        "model_not_found",
        "405 not allowed",
        "invalid api key",
        "incorrect api key",
        "authentication",
        "unauthorized",
        "permission denied",
        "quota exceeded",
    )
    is_non_retryable = any(marker in error_lower for marker in non_retryable_markers)
    should_retry = (attempt_count < max_attempts) and (not is_non_retryable)
    delay = min(base_seconds * (2 ** max(0, attempt_count - 1)), max_seconds)

    if should_retry:
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
        logger.warning("job will retry: id=%s, attempt=%d/%d, delay=%ds", job_id, attempt_count, max_attempts, delay)
    else:
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
        if is_non_retryable:
            logger.error("job moved to dead_letter (non-retryable): id=%s, attempts=%d", job_id, attempt_count)
        else:
            logger.error("job moved to dead_letter: id=%s, attempts=%d", job_id, attempt_count)

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


def _process_job_with_real_embeddings(
    conn,
    job: dict[str, Any],
    *,
    settings,
    embedding_service,
    chunker,
    worker_id: str,
) -> None:
    """执行单条入库任务 - 使用真实的文档解析和 OpenAI embeddings。"""
    job_id: UUID = job["id"]
    document_id: UUID = job["document_id"]
    document_version_id: UUID = job["document_version_id"]

    # 查询文档版本信息
    row = conn.execute(
        text(
            """
            SELECT d.tenant_id, d.workspace_id, d.kb_id, d.metadata AS document_metadata,
                   dv.object_key,
                   COALESCE(NULLIF(d.source_uri, ''), d.title) AS filename
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
    filename: str | None = row["filename"]

    if not object_key:
        raise RuntimeError("document version object_key is empty")

    # 更新文档状态为处理中
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

    # Step 1: 读取文件
    _touch_heartbeat(conn, job_id, worker_id)
    logger.info("reading object: job_id=%s, object_key=%s", job_id, object_key)

    file_bytes = _read_object_bytes_from_storage(
        backend=settings.storage_backend,
        storage_root=settings.storage_root,
        object_key=object_key,
        bucket_name=settings.storage_bucket,
        endpoint=settings.storage_endpoint,
        access_key=settings.storage_access_key,
        secret_key=settings.storage_secret_key,
        secure=settings.storage_secure,
        region=settings.storage_region,
    )

    # Step 2: 解析文档
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

    actual_filename = filename or _extract_filename_from_key(object_key)
    logger.info("parsing document: job_id=%s, filename=%s, size=%d bytes", job_id, actual_filename, len(file_bytes))

    try:
        text_content = default_parser_registry.parse(file_bytes, actual_filename)
    except Exception as exc:
        raise RuntimeError(f"Document parsing failed for {actual_filename}: {exc}") from exc

    if not text_content.strip():
        raise RuntimeError("Document has no extractable text content")

    logger.info("parsed document: job_id=%s, text_length=%d chars", job_id, len(text_content))

    # Step 3: 文本切片
    conn.execute(
        text(
            """
            UPDATE ingestion_jobs
            SET stage = 'chunking', progress = 40, heartbeat_at = now(), updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": str(job_id)},
    )

    chunks = chunker.chunk_text(text_content)
    if not chunks:
        raise RuntimeError("Document chunking produced no chunks")

    logger.info("chunked document: job_id=%s, chunks=%d", job_id, len(chunks))

    # Step 4: 生成向量
    conn.execute(
        text(
            """
            UPDATE ingestion_jobs
            SET stage = 'embedding', progress = 60, heartbeat_at = now(), updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": str(job_id)},
    )

    logger.info("generating embeddings: job_id=%s, chunks=%d", job_id, len(chunks))
    embeddings = embedding_service.embed_batch(chunks)

    if len(embeddings) != len(chunks):
        raise RuntimeError(f"Embedding count mismatch: got {len(embeddings)}, expected {len(chunks)}")

    # Step 5: 清理旧数据（幂等性）
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

    # Step 6: 插入切片和向量
    conn.execute(
        text(
            """
            UPDATE ingestion_jobs
            SET stage = 'indexing', progress = 80, heartbeat_at = now(), updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": str(job_id)},
    )

    from uuid import uuid4

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
            :content,
            :token_count,
            CAST(:metadata AS jsonb),
            :embedding::vector,
            :embedding_model,
            now(),
            now()
        )
        """
    )

    for idx, (chunk_text, embedding_vector) in enumerate(zip(chunks, embeddings)):
        token_count = embedding_service.count_tokens(chunk_text)
        chunk_metadata = {
            "source": "worker",
            "filename": actual_filename,
            "chunk_index": idx,
            "total_chunks": len(chunks),
        }

        # 将向量转换为 pgvector 格式
        vector_str = "[" + ",".join(str(v) for v in embedding_vector) + "]"

        conn.execute(
            insert_stmt,
            {
                "id": str(uuid4()),
                "tenant_id": str(tenant_id),
                "workspace_id": str(workspace_id),
                "kb_id": str(kb_id),
                "document_id": str(document_id),
                "document_version_id": str(document_version_id),
                "chunk_no": idx,
                "content": chunk_text,
                "token_count": token_count,
                "metadata": json.dumps(chunk_metadata),
                "embedding": vector_str,
                "embedding_model": settings.openai_embedding_model,
            },
        )

    logger.info("inserted chunks: job_id=%s, count=%d", job_id, len(chunks))

    # Step 7: 更新文档状态
    conn.execute(
        text(
            """
            UPDATE document_versions
            SET parse_status = 'completed', chunk_count = :chunk_count
            WHERE id = :document_version_id
            """
        ),
        {"document_version_id": str(document_version_id), "chunk_count": len(chunks)},
    )

    conn.execute(
        text(
            """
            UPDATE documents
            SET status = 'ready', chunk_count = :chunk_count, updated_at = now()
            WHERE id = :document_id
            """
        ),
        {"document_id": str(document_id), "chunk_count": len(chunks)},
    )


def main() -> None:
    """工作进程主循环。"""
    _setup_logging()
    settings = get_settings()

    logger.info("starting worker: id=%s", settings.worker_id)
    logger.info("database: %s", settings.database_url.split("@")[-1] if "@" in settings.database_url else "***")
    logger.info("storage: backend=%s, bucket=%s", settings.storage_backend, settings.storage_bucket)
    logger.info("embedding: model=%s, dimensions=%d", settings.openai_embedding_model, settings.openai_embedding_dimensions)

    engine = create_engine(settings.database_url, pool_pre_ping=True)

    # 初始化服务
    embedding_service = create_embedding_service(
        api_key=settings.resolved_openai_embedding_api_key,
        base_url=settings.resolved_openai_embedding_base_url,
        model=settings.openai_embedding_model,
    )
    chunker = create_chunker(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
    )

    logger.info("worker ready, polling for jobs...")

    while True:
        claimed = None
        try:
            with engine.begin() as conn:
                claimed = _claim_next_job(conn, settings.worker_id, settings.worker_lock_timeout_seconds)

            if not claimed:
                time.sleep(settings.worker_poll_interval_seconds)
                continue

            logger.info("claimed job: id=%s, document_id=%s", claimed["id"], claimed["document_id"])

            with engine.begin() as conn:
                _process_job_with_real_embeddings(
                    conn,
                    claimed,
                    settings=settings,
                    embedding_service=embedding_service,
                    chunker=chunker,
                    worker_id=settings.worker_id,
                )
                _mark_success(conn, claimed["id"])

            logger.info("completed job: id=%s", claimed["id"])

        except KeyboardInterrupt:
            logger.info("worker stopped by user")
            return

        except Exception as exc:
            if not claimed:
                logger.exception("worker loop error without claimed job")
                time.sleep(settings.worker_poll_interval_seconds)
                continue

            err = str(exc)[:2000]
            logger.exception("job failed: id=%s, error=%s", claimed["id"], err)

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
