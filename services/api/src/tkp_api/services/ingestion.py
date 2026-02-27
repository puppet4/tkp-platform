"""入库任务服务。"""

import hashlib
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.core.config import get_settings
from tkp_api.models.enums import IngestionJobStatus
from tkp_api.models.knowledge import IngestionJob


def build_job_idempotency_key(
    tenant_id: UUID,
    workspace_id: UUID,
    kb_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
    action: str,
    client_key: str | None,
) -> str:
    """构造入库任务幂等键。"""
    # 客户端传幂等键时仍拼接文档维度，避免不同文档误用同一键导致冲突。
    if client_key:
        basis = (
            f"{tenant_id}:{workspace_id}:{kb_id}:{document_id}:{document_version_id}:{action}:{client_key}"
        )
    else:
        basis = f"{tenant_id}:{workspace_id}:{kb_id}:{document_id}:{document_version_id}:{action}"

    # 统一使用 SHA-256 并截断到 64 位，兼顾碰撞风险与字段长度。
    digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()
    return digest[:64]


def enqueue_ingestion_job(
    db: Session,
    *,
    tenant_id: UUID,
    workspace_id: UUID,
    kb_id: UUID,
    document_id: UUID,
    document_version_id: UUID,
    action: str,
    client_idempotency_key: str | None,
) -> IngestionJob:
    """创建入库任务，若命中幂等键则复用已有任务。"""
    settings = get_settings()

    idempotency_key = build_job_idempotency_key(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        kb_id=kb_id,
        document_id=document_id,
        document_version_id=document_version_id,
        action=action,
        client_key=client_idempotency_key,
    )

    existing = db.execute(
        select(IngestionJob)
        .where(IngestionJob.tenant_id == tenant_id)
        .where(IngestionJob.idempotency_key == idempotency_key)
    ).scalar_one_or_none()
    if existing:
        # 幂等命中直接复用旧任务，避免重复入队和重复处理。
        return existing

    # 首次创建任务时，初始状态为 queued，等待 worker 抢占执行。
    job = IngestionJob(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        kb_id=kb_id,
        document_id=document_id,
        document_version_id=document_version_id,
        idempotency_key=idempotency_key,
        status=IngestionJobStatus.QUEUED,
        stage="queued",
        progress=0,
        attempt_count=0,
        max_attempts=settings.ingestion_default_max_attempts,
        next_run_at=datetime.now(timezone.utc),
    )
    db.add(job)
    db.flush()
    return job
