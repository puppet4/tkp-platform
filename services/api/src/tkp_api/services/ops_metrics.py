"""运行态可观测指标聚合。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.models.enums import IngestionJobStatus
from tkp_api.models.knowledge import IngestionJob, RetrievalLog


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


def build_retrieval_quality_metrics(
    db: Session,
    *,
    tenant_id: UUID,
    window_hours: int = 24,
) -> dict[str, Any]:
    """按租户聚合检索质量指标。"""
    now = datetime.now(timezone.utc)
    window_from = now - timedelta(hours=window_hours)

    rows = db.execute(
        select(
            RetrievalLog.latency_ms,
            RetrievalLog.result_chunks,
        ).where(
            RetrievalLog.tenant_id == tenant_id,
            RetrievalLog.created_at >= window_from,
        )
    ).all()

    total_queries = len(rows)
    query_with_hits = 0
    latency_values: list[int] = []
    total_hits = 0
    cited_hits = 0

    for latency_ms_raw, result_chunks_raw in rows:
        latency_values.append(max(0, int(latency_ms_raw or 0)))
        result_chunks = result_chunks_raw if isinstance(result_chunks_raw, list) else []
        if result_chunks:
            query_with_hits += 1
        total_hits += len(result_chunks)
        for hit in result_chunks:
            if isinstance(hit, dict) and isinstance(hit.get("citation"), dict):
                cited_hits += 1

    zero_hit_queries = max(0, total_queries - query_with_hits)
    zero_hit_rate = float(zero_hit_queries) / float(total_queries) if total_queries > 0 else 0.0
    citation_coverage_rate = float(cited_hits) / float(total_hits) if total_hits > 0 else 1.0
    avg_latency_ms = int(sum(latency_values) / len(latency_values)) if latency_values else None

    return {
        "tenant_id": str(tenant_id),
        "window_hours": int(window_hours),
        "query_total": total_queries,
        "query_with_hits": query_with_hits,
        "zero_hit_queries": zero_hit_queries,
        "zero_hit_rate": round(zero_hit_rate, 6),
        "hit_total": total_hits,
        "hit_with_citation": cited_hits,
        "citation_coverage_rate": round(citation_coverage_rate, 6),
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": _p95(latency_values),
    }


def _slo_status(current: float, target: float, *, mode: str) -> str:
    """根据阈值比较结果输出状态。"""
    if mode == "lte":
        return "pass" if current <= target else "fail"
    return "pass" if current >= target else "fail"


def build_mvp_slo_summary(
    db: Session,
    *,
    tenant_id: UUID,
    window_hours: int = 24,
    ingestion_failure_rate_target: float = 0.10,
    ingestion_p95_latency_target_ms: int = 300000,
    retrieval_zero_hit_rate_target: float = 0.30,
    retrieval_p95_latency_target_ms: int = 3000,
    retrieval_citation_coverage_target: float = 0.95,
) -> dict[str, Any]:
    """构建 MVP 阶段 SLO 摘要。"""
    ingestion = build_ingestion_metrics(db, tenant_id=tenant_id, window_hours=window_hours)
    retrieval = build_retrieval_quality_metrics(db, tenant_id=tenant_id, window_hours=window_hours)

    ingestion_p95_current = float(ingestion["p95_latency_ms_last_window"] or 0)
    retrieval_p95_current = float(retrieval["p95_latency_ms"] or 0)

    checks = [
        {
            "code": "INGESTION_FAILURE_RATE",
            "name": "入库窗口失败率",
            "status": _slo_status(
                float(ingestion["failure_rate_last_window"]),
                float(max(0.0, ingestion_failure_rate_target)),
                mode="lte",
            ),
            "current": round(float(ingestion["failure_rate_last_window"]), 6),
            "target": round(float(max(0.0, ingestion_failure_rate_target)), 6),
            "operator": "<=",
        },
        {
            "code": "INGESTION_P95_LATENCY_MS",
            "name": "入库P95耗时",
            "status": _slo_status(
                ingestion_p95_current,
                float(max(1, ingestion_p95_latency_target_ms)),
                mode="lte",
            ),
            "current": int(ingestion_p95_current),
            "target": int(max(1, ingestion_p95_latency_target_ms)),
            "operator": "<=",
        },
        {
            "code": "RETRIEVAL_ZERO_HIT_RATE",
            "name": "检索零命中率",
            "status": _slo_status(
                float(retrieval["zero_hit_rate"]),
                float(max(0.0, retrieval_zero_hit_rate_target)),
                mode="lte",
            ),
            "current": round(float(retrieval["zero_hit_rate"]), 6),
            "target": round(float(max(0.0, retrieval_zero_hit_rate_target)), 6),
            "operator": "<=",
        },
        {
            "code": "RETRIEVAL_P95_LATENCY_MS",
            "name": "检索P95耗时",
            "status": _slo_status(
                retrieval_p95_current,
                float(max(1, retrieval_p95_latency_target_ms)),
                mode="lte",
            ),
            "current": int(retrieval_p95_current),
            "target": int(max(1, retrieval_p95_latency_target_ms)),
            "operator": "<=",
        },
        {
            "code": "RETRIEVAL_CITATION_COVERAGE",
            "name": "检索引用覆盖率",
            "status": _slo_status(
                float(retrieval["citation_coverage_rate"]),
                float(max(0.0, retrieval_citation_coverage_target)),
                mode="gte",
            ),
            "current": round(float(retrieval["citation_coverage_rate"]), 6),
            "target": round(float(max(0.0, retrieval_citation_coverage_target)), 6),
            "operator": ">=",
        },
    ]

    overall_status = "pass" if all(item["status"] == "pass" for item in checks) else "fail"
    return {
        "tenant_id": str(tenant_id),
        "window_hours": int(window_hours),
        "overall_status": overall_status,
        "checks": checks,
        "ingestion_metrics": ingestion,
        "retrieval_quality": retrieval,
    }
