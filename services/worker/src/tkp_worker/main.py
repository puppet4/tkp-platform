"""入库工作进程。

主流程:
1) 抢占一条待处理任务(queued/retrying)
2) 读取文档版本 object_key
3) 解析 + 切片 + 回写 document_chunks
4) 成功则 completed，失败则 retrying/dead_letter
"""

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import create_engine, text

from tkp_worker.config import get_settings

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


def _read_text_from_object(storage_root: str, object_key: str, parser_type: str | None) -> str:
    """按对象键读取文件并执行基础解析。"""
    path = Path(storage_root).joinpath(object_key)
    if not path.exists():
        raise FileNotFoundError(f"object not found: {path}")

    parser = parser_type or "generic"
    if parser in {"markdown", "generic"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if parser == "pdf":
        raise RuntimeError("pdf parser not configured")
    if parser == "image":
        raise RuntimeError("image parser/ocr not configured")
    return path.read_text(encoding="utf-8", errors="ignore")


def _chunk_text(content: str, chunk_size: int = 900, overlap: int = 120) -> list[str]:
    """将文本切分为重叠块。"""
    text_content = content.strip()
    if not text_content:
        return []

    chunks: list[str] = []
    start = 0
    total = len(text_content)
    while start < total:
        end = min(total, start + chunk_size)
        chunk = text_content[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= total:
            break
        # 通过 overlap 保留上下文连续性，提升检索质量。
        start = max(0, end - overlap)
    return chunks


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


def _process_job(conn, job: dict[str, Any], storage_root: str, worker_id: str) -> None:
    """执行单条入库任务。"""
    job_id: UUID = job["id"]
    document_id: UUID = job["document_id"]
    document_version_id: UUID = job["document_version_id"]

    # 通过版本表反查对象键与解析器类型。
    row = conn.execute(
        text(
            """
            SELECT d.tenant_id, d.workspace_id, d.kb_id, dv.object_key, dv.parser_type
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
    content = _read_text_from_object(storage_root, object_key, parser_type)

    conn.execute(
        text(
            """
            UPDATE ingestion_jobs
            SET stage = 'chunking', progress = 45, heartbeat_at = now(), updated_at = now()
            WHERE id = :job_id
            """
        ),
        {"job_id": str(job_id)},
    )

    chunks = _chunk_text(content)
    if not chunks:
        raise RuntimeError("document has no parseable content")

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
            now()
        )
        """
    )

    for i, chunk in enumerate(chunks, start=1):
        conn.execute(
            insert_stmt,
            {
                "id": str(uuid4()),
                "tenant_id": str(tenant_id),
                "workspace_id": str(workspace_id),
                "kb_id": str(kb_id),
                "document_id": str(document_id),
                "document_version_id": str(document_version_id),
                "chunk_no": i,
                "content": chunk,
                "token_count": len(chunk.split()),
                "metadata": json.dumps({}),
            },
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
                    storage_root=settings.storage_root,
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
