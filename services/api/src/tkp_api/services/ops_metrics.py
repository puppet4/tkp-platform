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


def _normalize_threshold_pair(
    *,
    warn: float,
    critical: float,
) -> tuple[float, float]:
    """保证告警阈值满足 warn <= critical。"""
    if critical < warn:
        return critical, warn
    return warn, critical


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


def build_ingestion_alerts(
    metrics: dict[str, Any],
    *,
    backlog_warn: int = 20,
    backlog_critical: int = 50,
    failure_rate_warn: float = 0.05,
    failure_rate_critical: float = 0.2,
    stale_warn: int = 1,
    stale_critical: int = 3,
) -> dict[str, Any]:
    """根据入库指标计算告警状态，供监控系统直接拉取。"""
    backlog_warn_norm, backlog_critical_norm = _normalize_threshold_pair(
        warn=float(max(0, backlog_warn)),
        critical=float(max(0, backlog_critical)),
    )
    failure_warn_norm, failure_critical_norm = _normalize_threshold_pair(
        warn=float(max(0.0, failure_rate_warn)),
        critical=float(max(0.0, failure_rate_critical)),
    )
    stale_warn_norm, stale_critical_norm = _normalize_threshold_pair(
        warn=float(max(0, stale_warn)),
        critical=float(max(0, stale_critical)),
    )

    def _status(current: float, warn: float, critical: float) -> str:
        if current >= critical:
            return "critical"
        if current >= warn:
            return "warn"
        return "ok"

    rules: list[dict[str, Any]] = []

    backlog_value = float(metrics.get("backlog_total") or 0)
    backlog_status = _status(backlog_value, backlog_warn_norm, backlog_critical_norm)
    rules.append(
        {
            "code": "BACKLOG",
            "name": "入库任务积压",
            "status": backlog_status,
            "current": int(backlog_value),
            "warn_threshold": int(backlog_warn_norm),
            "critical_threshold": int(backlog_critical_norm),
            "message": f"当前积压任务 {int(backlog_value)}。",
        }
    )

    failure_value = float(metrics.get("failure_rate_last_window") or 0.0)
    failure_status = _status(failure_value, failure_warn_norm, failure_critical_norm)
    rules.append(
        {
            "code": "FAILURE_RATE",
            "name": "窗口失败率",
            "status": failure_status,
            "current": round(failure_value, 6),
            "warn_threshold": round(failure_warn_norm, 6),
            "critical_threshold": round(failure_critical_norm, 6),
            "message": f"窗口失败率 {round(failure_value, 6)}。",
        }
    )

    stale_value = float(metrics.get("stale_processing_jobs") or 0)
    stale_status = _status(stale_value, stale_warn_norm, stale_critical_norm)
    rules.append(
        {
            "code": "STALE_PROCESSING",
            "name": "疑似卡住任务",
            "status": stale_status,
            "current": int(stale_value),
            "warn_threshold": int(stale_warn_norm),
            "critical_threshold": int(stale_critical_norm),
            "message": f"疑似卡住任务 {int(stale_value)}。",
        }
    )

    overall_status = "ok"
    if any(item["status"] == "critical" for item in rules):
        overall_status = "critical"
    elif any(item["status"] == "warn" for item in rules):
        overall_status = "warn"

    return {
        "tenant_id": metrics["tenant_id"],
        "overall_status": overall_status,
        "rules": rules,
    }
