"""运行态可观测指标聚合。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.models.enums import IngestionJobStatus
from tkp_api.models.knowledge import IngestionJob


def _normalize_datetime(value: datetime | None) -> datetime | None:
    """归一化时间为 UTC，兼容 sqlite 返回的 naive datetime。"""
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _p95(values: list[int]) -> int | None:
    """计算整数列表的 p95。"""
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, ceil(len(ordered) * 0.95) - 1)
    return ordered[index]


def build_ingestion_metrics(
    db: Session,
    *,
    tenant_id: UUID,
    window_hours: int = 24,
    stale_seconds: int = 120,
) -> dict[str, Any]:
    """按租户聚合入库任务运行指标。"""
    rows = db.execute(
        select(
            IngestionJob.status,
            IngestionJob.started_at,
            IngestionJob.finished_at,
            IngestionJob.heartbeat_at,
        ).where(IngestionJob.tenant_id == tenant_id)
    ).all()

    now = datetime.now(timezone.utc)
    window_from = now - timedelta(hours=window_hours)
    stale_from = now - timedelta(seconds=stale_seconds)

    status_counts: dict[str, int] = {
        IngestionJobStatus.QUEUED: 0,
        IngestionJobStatus.PROCESSING: 0,
        IngestionJobStatus.RETRYING: 0,
        IngestionJobStatus.COMPLETED: 0,
        IngestionJobStatus.DEAD_LETTER: 0,
    }
    completed_last_window = 0
    dead_letter_last_window = 0
    stale_processing_jobs = 0
    latency_ms_last_window: list[int] = []

    for status_raw, started_at_raw, finished_at_raw, heartbeat_at_raw in rows:
        status = str(status_raw)
        if status in status_counts:
            status_counts[status] += 1

        started_at = _normalize_datetime(started_at_raw)
        finished_at = _normalize_datetime(finished_at_raw)
        heartbeat_at = _normalize_datetime(heartbeat_at_raw)

        if status == IngestionJobStatus.COMPLETED and finished_at and finished_at >= window_from:
            completed_last_window += 1
            if started_at:
                latency_ms_last_window.append(max(0, int((finished_at - started_at).total_seconds() * 1000)))
        elif status == IngestionJobStatus.DEAD_LETTER and finished_at and finished_at >= window_from:
            dead_letter_last_window += 1

        if status == IngestionJobStatus.PROCESSING:
            if heartbeat_at is None or heartbeat_at < stale_from:
                stale_processing_jobs += 1

    terminal_count_last_window = completed_last_window + dead_letter_last_window
    failure_rate_last_window = (
        float(dead_letter_last_window) / float(terminal_count_last_window) if terminal_count_last_window > 0 else 0.0
    )

    avg_latency_ms_last_window = (
        int(sum(latency_ms_last_window) / len(latency_ms_last_window)) if latency_ms_last_window else None
    )

    return {
        "tenant_id": str(tenant_id),
        "window_hours": int(window_hours),
        "queued": status_counts[IngestionJobStatus.QUEUED],
        "processing": status_counts[IngestionJobStatus.PROCESSING],
        "retrying": status_counts[IngestionJobStatus.RETRYING],
        "completed": status_counts[IngestionJobStatus.COMPLETED],
        "dead_letter": status_counts[IngestionJobStatus.DEAD_LETTER],
        "backlog_total": status_counts[IngestionJobStatus.QUEUED] + status_counts[IngestionJobStatus.RETRYING],
        "completed_last_window": completed_last_window,
        "dead_letter_last_window": dead_letter_last_window,
        "failure_rate_last_window": round(failure_rate_last_window, 6),
        "avg_latency_ms_last_window": avg_latency_ms_last_window,
        "p95_latency_ms_last_window": _p95(latency_ms_last_window),
        "stale_processing_jobs": stale_processing_jobs,
    }
