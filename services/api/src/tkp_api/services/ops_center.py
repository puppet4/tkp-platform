"""Phase 3 运维中心服务。"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib import error as urlerror
from urllib import request as urlrequest
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tkp_api.models.agent import AgentRun
from tkp_api.models.conversation import Conversation, Message
from tkp_api.models.enums import IngestionJobStatus, MessageRole
from tkp_api.models.knowledge import Document, IngestionJob, RetrievalLog
from tkp_api.models.ops import OpsAlertWebhook, OpsDeletionProof, OpsIncidentTicket, OpsReleaseRollout
from tkp_api.models.tenant import User
from tkp_api.models.workspace import Workspace
from tkp_api.services.cost import build_tenant_cost_summary
from tkp_api.services.ops_metrics import build_ingestion_alerts, build_ingestion_metrics, \
    build_retrieval_quality_metrics

_PROMPT_TOKEN_UNIT_COST = 0.000001
_COMPLETION_TOKEN_UNIT_COST = 0.000002


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().isoformat().replace("+00:00", "Z")


def _safe_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _incident_to_dict(row: OpsIncidentTicket) -> dict[str, Any]:
    return {
        "ticket_id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "source_code": row.source_code,
        "severity": row.severity,
        "status": row.status,
        "title": row.title,
        "summary": row.summary,
        "diagnosis": _safe_dict(row.diagnosis_json),
        "context": _safe_dict(row.context_json),
        "assignee_user_id": str(row.assignee_user_id) if row.assignee_user_id else None,
        "resolution_note": row.resolution_note,
        "created_by": str(row.created_by) if row.created_by else None,
        "resolved_at": row.resolved_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _webhook_to_dict(row: OpsAlertWebhook) -> dict[str, Any]:
    return {
        "webhook_id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "name": row.name,
        "url": row.url,
        "enabled": bool(row.enabled),
        "event_types": list(row.event_types or []),
        "timeout_seconds": int(row.timeout_seconds),
        "last_status_code": row.last_status_code,
        "last_error": row.last_error,
        "last_notified_at": row.last_notified_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _rollout_to_dict(row: OpsReleaseRollout) -> dict[str, Any]:
    return {
        "rollout_id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "version": row.version,
        "strategy": row.strategy,
        "status": row.status,
        "risk_level": row.risk_level,
        "canary_percent": int(row.canary_percent),
        "scope": _safe_dict(row.scope_json),
        "rollback_of": str(row.rollback_of) if row.rollback_of else None,
        "approved_by": str(row.approved_by) if row.approved_by else None,
        "note": row.note,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _proof_to_dict(row: OpsDeletionProof) -> dict[str, Any]:
    return {
        "proof_id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "resource_type": row.resource_type,
        "resource_id": row.resource_id,
        "subject_hash": row.subject_hash,
        "signature": row.signature,
        "deleted_by": str(row.deleted_by) if row.deleted_by else None,
        "deleted_at": row.deleted_at,
        "ticket_id": str(row.ticket_id) if row.ticket_id else None,
        "proof_payload": _safe_dict(row.proof_payload),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def build_ops_overview(db: Session, *, tenant_id: UUID, window_hours: int = 24) -> dict[str, Any]:
    """构建租户运维概览。"""
    ingestion_metrics = build_ingestion_metrics(db, tenant_id=tenant_id, window_hours=window_hours)
    ingestion_alerts = build_ingestion_alerts(ingestion_metrics)
    retrieval_quality = build_retrieval_quality_metrics(db, tenant_id=tenant_id, window_hours=window_hours)
    cost_summary = build_tenant_cost_summary(db, tenant_id=tenant_id, window_hours=window_hours)

    incident_open_total = int(
        db.execute(
            select(func.count())
            .select_from(OpsIncidentTicket)
            .where(
                OpsIncidentTicket.tenant_id == tenant_id,
                OpsIncidentTicket.status.in_(["open", "acknowledged"]),
            )
        ).scalar_one()
        or 0
    )
    incident_critical_total = int(
        db.execute(
            select(func.count())
            .select_from(OpsIncidentTicket)
            .where(
                OpsIncidentTicket.tenant_id == tenant_id,
                OpsIncidentTicket.status.in_(["open", "acknowledged"]),
                OpsIncidentTicket.severity == "critical",
            )
        ).scalar_one()
        or 0
    )
    webhook_enabled_total = int(
        db.execute(
            select(func.count())
            .select_from(OpsAlertWebhook)
            .where(OpsAlertWebhook.tenant_id == tenant_id, OpsAlertWebhook.enabled.is_(True))
        ).scalar_one()
        or 0
    )
    estimated_total_cost_raw = cost_summary.get("estimated_total_cost")
    if isinstance(estimated_total_cost_raw, (int, float)):
        estimated_total_cost = float(estimated_total_cost_raw)
    elif isinstance(estimated_total_cost_raw, str):
        try:
            estimated_total_cost = float(estimated_total_cost_raw)
        except ValueError:
            estimated_total_cost = 0.0
    else:
        estimated_total_cost = 0.0

    return {
        "tenant_id": str(tenant_id),
        "window_hours": int(window_hours),
        "generated_at": _utc_now(),
        "ingestion_alert_status": ingestion_alerts["overall_status"],
        "ingestion_backlog_total": int(ingestion_metrics["backlog_total"]),
        "ingestion_failure_rate": float(ingestion_metrics["failure_rate_last_window"]),
        "retrieval_zero_hit_rate": float(retrieval_quality["zero_hit_rate"]),
        "estimated_total_cost": estimated_total_cost,
        "incident_open_total": incident_open_total,
        "incident_critical_open_total": incident_critical_total,
        "webhook_enabled_total": webhook_enabled_total,
    }


def build_tenant_health(db: Session, *, tenant_id: UUID, window_hours: int = 24) -> list[dict[str, Any]]:
    """按 workspace 汇总租户健康状态。"""
    since = _utc_now() - timedelta(hours=max(1, window_hours))

    workspaces = (
        db.execute(
            select(Workspace)
            .where(Workspace.tenant_id == tenant_id)
            .order_by(Workspace.created_at.asc())
        )
        .scalars()
        .all()
    )

    items: list[dict[str, Any]] = []
    for ws in workspaces:
        doc_rows = db.execute(
            select(Document.status).where(Document.tenant_id == tenant_id, Document.workspace_id == ws.id)
        ).all()
        document_total = len(doc_rows)
        document_ready = sum(1 for (status,) in doc_rows if status == "ready")

        dead_letter_jobs = int(
            db.execute(
                select(func.count())
                .select_from(IngestionJob)
                .where(
                    IngestionJob.tenant_id == tenant_id,
                    IngestionJob.workspace_id == ws.id,
                    IngestionJob.status == IngestionJobStatus.DEAD_LETTER,
                    IngestionJob.updated_at >= since,
                )
            ).scalar_one()
            or 0
        )

        retrieval_rows = db.execute(
            select(RetrievalLog.result_chunks).where(
                RetrievalLog.tenant_id == tenant_id,
                RetrievalLog.created_at >= since,
            )
        ).all()
        # 当前表结构中 retrieval_log 不含 workspace_id，暂以租户窗口指标兜底。
        retrieval_total = len(retrieval_rows)
        retrieval_zero_hit = sum(1 for (chunks,) in retrieval_rows if not isinstance(chunks, list) or len(chunks) == 0)

        ready_ratio = float(document_ready) / float(document_total) if document_total > 0 else 1.0
        zero_hit_rate = float(retrieval_zero_hit) / float(retrieval_total) if retrieval_total > 0 else 0.0

        status = "healthy"
        if dead_letter_jobs > 0 or ready_ratio < 0.8 or zero_hit_rate >= 0.5:
            status = "critical"
        elif ready_ratio < 0.95 or zero_hit_rate >= 0.3:
            status = "warn"

        items.append(
            {
                "workspace_id": str(ws.id),
                "workspace_name": ws.name,
                "workspace_status": ws.status,
                "document_total": document_total,
                "document_ready": document_ready,
                "document_ready_ratio": round(ready_ratio, 6),
                "dead_letter_jobs": dead_letter_jobs,
                "retrieval_queries": retrieval_total,
                "retrieval_zero_hit": retrieval_zero_hit,
                "retrieval_zero_hit_rate": round(zero_hit_rate, 6),
                "status": status,
            }
        )

    return items


def build_cost_leaderboard(
    db: Session,
    *,
    tenant_id: UUID,
    window_hours: int = 24,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """按用户维度输出成本榜单。"""
    since = _utc_now() - timedelta(hours=max(1, window_hours))

    users = {
        str(row.id): row
        for row in db.execute(select(User).where(User.id.is_not(None))).scalars().all()
    }

    retrieval_counter: dict[str, int] = {}
    retrieval_rows = db.execute(
        select(RetrievalLog.user_id).where(RetrievalLog.tenant_id == tenant_id, RetrievalLog.created_at >= since)
    ).all()
    for (user_id,) in retrieval_rows:
        key = str(user_id)
        retrieval_counter[key] = retrieval_counter.get(key, 0) + 1

    token_usage: dict[str, dict[str, int]] = {}
    usage_rows = db.execute(
        select(Conversation.user_id, Message.usage)
        .join(Message, Message.conversation_id == Conversation.id)
        .where(
            Conversation.tenant_id == tenant_id,
            Message.role == MessageRole.ASSISTANT,
            Message.created_at >= since,
        )
    ).all()
    for user_id, usage in usage_rows:
        key = str(user_id)
        token_usage.setdefault(key, {"prompt": 0, "completion": 0, "total": 0})
        if not isinstance(usage, dict):
            continue
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        total = int(usage.get("total_tokens") or (prompt + completion))
        token_usage[key]["prompt"] += prompt
        token_usage[key]["completion"] += completion
        token_usage[key]["total"] += total

    agent_usage: dict[str, dict[str, float]] = {}
    agent_rows = db.execute(
        select(AgentRun.user_id, AgentRun.cost)
        .where(AgentRun.tenant_id == tenant_id, AgentRun.created_at >= since)
    ).all()
    for user_id, cost in agent_rows:
        key = str(user_id)
        agent_usage.setdefault(key, {"runs": 0.0, "cost": 0.0})
        agent_usage[key]["runs"] += 1
        agent_usage[key]["cost"] += float(cost or 0.0)

    ranked: list[dict[str, Any]] = []
    user_ids = set(retrieval_counter.keys()) | set(token_usage.keys()) | set(agent_usage.keys())
    for user_id in user_ids:
        usage = token_usage.get(user_id, {"prompt": 0, "completion": 0, "total": 0})
        agent = agent_usage.get(user_id, {"runs": 0.0, "cost": 0.0})
        chat_cost = (usage["prompt"] * _PROMPT_TOKEN_UNIT_COST) + (usage["completion"] * _COMPLETION_TOKEN_UNIT_COST)
        estimated_total = chat_cost + float(agent["cost"])

        user = users.get(user_id)
        ranked.append(
            {
                "user_id": user_id,
                "display_name": user.display_name if user else "unknown",
                "email": user.email if user else "",
                "retrieval_requests": int(retrieval_counter.get(user_id, 0)),
                "chat_total_tokens": int(usage["total"]),
                "agent_runs": int(agent["runs"]),
                "agent_cost_total": round(float(agent["cost"]), 6),
                "estimated_total_cost": round(float(estimated_total), 6),
            }
        )

    ranked.sort(
        key=lambda item: (
            float(item["estimated_total_cost"]),
            int(item["retrieval_requests"]),
            int(item["chat_total_tokens"]),
        ),
        reverse=True,
    )

    return ranked[: max(1, limit)]


def build_incident_diagnosis(db: Session, *, tenant_id: UUID, window_hours: int = 24) -> list[dict[str, Any]]:
    """构建当前租户异常诊断项。"""
    ingestion_metrics = build_ingestion_metrics(db, tenant_id=tenant_id, window_hours=window_hours)
    retrieval_quality = build_retrieval_quality_metrics(db, tenant_id=tenant_id, window_hours=window_hours)

    items: list[dict[str, Any]] = []

    dead_letter = int(ingestion_metrics["dead_letter_last_window"])
    if dead_letter > 0:
        items.append(
            {
                "source_code": "INGESTION_DEAD_LETTER",
                "severity": "critical",
                "title": "发现 dead-letter 任务",
                "summary": f"最近 {window_hours} 小时出现 {dead_letter} 个 dead-letter 任务。",
                "suggestion": "优先排查解析失败文档，执行手工 retry 或 dead-letter 关闭。",
                "context": {
                    "dead_letter_last_window": dead_letter,
                    "stale_processing_jobs": int(ingestion_metrics["stale_processing_jobs"]),
                },
            }
        )

    failure_rate = float(ingestion_metrics["failure_rate_last_window"])
    if failure_rate >= 0.1:
        items.append(
            {
                "source_code": "INGESTION_FAILURE_RATE",
                "severity": "critical" if failure_rate >= 0.2 else "warn",
                "title": "入库失败率偏高",
                "summary": f"最近窗口失败率为 {round(failure_rate, 6)}。",
                "suggestion": "检查异常文档样本与 worker 错误日志，确认重试策略是否需要调优。",
                "context": {
                    "failure_rate_last_window": round(failure_rate, 6),
                    "completed_last_window": int(ingestion_metrics["completed_last_window"]),
                    "dead_letter_last_window": dead_letter,
                },
            }
        )

    stale_processing = int(ingestion_metrics["stale_processing_jobs"])
    if stale_processing > 0:
        items.append(
            {
                "source_code": "INGESTION_STALE_PROCESSING",
                "severity": "warn",
                "title": "存在疑似卡住任务",
                "summary": f"检测到 {stale_processing} 个 processing 任务超时。",
                "suggestion": "检查 worker 心跳与锁释放，必要时对任务执行手动 dead-letter 与重试。",
                "context": {"stale_processing_jobs": stale_processing},
            }
        )

    zero_hit_rate = float(retrieval_quality["zero_hit_rate"])
    if zero_hit_rate >= 0.3:
        items.append(
            {
                "source_code": "RETRIEVAL_ZERO_HIT",
                "severity": "warn" if zero_hit_rate < 0.5 else "critical",
                "title": "检索零命中率偏高",
                "summary": f"最近窗口零命中率为 {round(zero_hit_rate, 6)}。",
                "suggestion": "优先检查知识库入库状态与查询改写策略，补齐高频问题文档。",
                "context": {
                    "query_total": int(retrieval_quality["query_total"]),
                    "zero_hit_queries": int(retrieval_quality["zero_hit_queries"]),
                    "zero_hit_rate": round(zero_hit_rate, 6),
                },
            }
        )

    if not items:
        items.append(
            {
                "source_code": "OPS_HEALTHY",
                "severity": "info",
                "title": "未发现关键异常",
                "summary": "当前窗口内未发现需要工单化处理的告警项。",
                "suggestion": "保持常规巡检节奏即可。",
                "context": {"window_hours": int(window_hours)},
            }
        )

    return items


def create_incident_ticket(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    source_code: str,
    severity: str,
    title: str,
    summary: str,
    diagnosis: dict[str, Any] | None,
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """创建运维工单。"""
    row = OpsIncidentTicket(
        tenant_id=tenant_id,
        source_code=source_code.strip(),
        severity=severity,
        status="open",
        title=title.strip(),
        summary=summary.strip(),
        diagnosis_json=diagnosis or {},
        context_json=context or {},
        created_by=user_id,
    )
    db.add(row)
    db.flush()
    return _incident_to_dict(row)


def list_incident_tickets(
    db: Session,
    *,
    tenant_id: UUID,
    status: str | None = None,
    severity: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """分页查询运维工单。"""
    stmt = select(OpsIncidentTicket).where(OpsIncidentTicket.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(OpsIncidentTicket.status == status)
    if severity:
        stmt = stmt.where(OpsIncidentTicket.severity == severity)

    rows = (
        db.execute(stmt.order_by(OpsIncidentTicket.created_at.desc()).offset(offset).limit(limit))
        .scalars()
        .all()
    )
    return [_incident_to_dict(row) for row in rows]


def update_incident_ticket(
    db: Session,
    *,
    tenant_id: UUID,
    ticket_id: UUID,
    status: str | None,
    assignee_user_id: UUID | None,
    resolution_note: str | None,
) -> dict[str, Any] | None:
    """更新工单状态与处理信息。"""
    row = db.get(OpsIncidentTicket, ticket_id)
    if not row or row.tenant_id != tenant_id:
        return None

    if status is not None:
        row.status = status
        if status == "resolved":
            row.resolved_at = _utc_now_iso()
        elif row.resolved_at:
            row.resolved_at = None
    if assignee_user_id is not None:
        row.assignee_user_id = assignee_user_id
    if resolution_note is not None:
        row.resolution_note = resolution_note.strip() or None

    db.flush()
    return _incident_to_dict(row)


def upsert_alert_webhook(
    db: Session,
    *,
    tenant_id: UUID,
    name: str,
    url: str,
    secret: str | None,
    enabled: bool,
    event_types: list[str],
    timeout_seconds: int,
) -> dict[str, Any]:
    """按 name 创建或更新 webhook。"""
    row = (
        db.execute(
            select(OpsAlertWebhook)
            .where(OpsAlertWebhook.tenant_id == tenant_id, OpsAlertWebhook.name == name.strip())
            .limit(1)
        )
        .scalar_one_or_none()
    )

    normalized_events = sorted({item.strip() for item in event_types if item and item.strip()})

    if row is None:
        row = OpsAlertWebhook(
            tenant_id=tenant_id,
            name=name.strip(),
            url=url.strip(),
            secret=secret,
            enabled=enabled,
            event_types=normalized_events,
            timeout_seconds=timeout_seconds,
        )
        db.add(row)
    else:
        row.url = url.strip()
        row.secret = secret
        row.enabled = enabled
        row.event_types = normalized_events
        row.timeout_seconds = timeout_seconds

    db.flush()
    return _webhook_to_dict(row)


def list_alert_webhooks(db: Session, *, tenant_id: UUID) -> list[dict[str, Any]]:
    """查询租户告警 webhook 列表。"""
    rows = (
        db.execute(
            select(OpsAlertWebhook)
            .where(OpsAlertWebhook.tenant_id == tenant_id)
            .order_by(OpsAlertWebhook.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_webhook_to_dict(row) for row in rows]


def dispatch_alerts(
    db: Session,
    *,
    tenant_id: UUID,
    event_type: str,
    severity: str,
    title: str,
    message: str,
    attributes: dict[str, Any] | None,
    dry_run: bool,
) -> dict[str, Any]:
    """分发告警到匹配的 webhook。"""
    webhooks = (
        db.execute(
            select(OpsAlertWebhook)
            .where(OpsAlertWebhook.tenant_id == tenant_id, OpsAlertWebhook.enabled.is_(True))
            .order_by(OpsAlertWebhook.created_at.asc())
        )
        .scalars()
        .all()
    )

    payload = {
        "tenant_id": str(tenant_id),
        "event_type": event_type,
        "severity": severity,
        "title": title,
        "message": message,
        "attributes": attributes or {},
        "sent_at": _utc_now_iso(),
    }

    results: list[dict[str, Any]] = []
    delivered_count = 0

    for row in webhooks:
        subscribed = list(row.event_types or [])
        if subscribed and event_type not in subscribed:
            continue

        if dry_run:
            results.append(
                {
                    "webhook_id": str(row.id),
                    "name": row.name,
                    "url": row.url,
                    "status_code": None,
                    "delivered": False,
                    "error": None,
                    "dry_run": True,
                }
            )
            continue

        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "X-TKP-Event-Type": event_type,
            "X-TKP-Severity": severity,
        }
        if row.secret:
            signature = hmac.new(row.secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
            headers["X-TKP-Signature"] = signature

        request = urlrequest.Request(
            row.url,
            data=body,
            headers=headers,
            method="POST",
        )

        status_code: int | None = None
        error_msg: str | None = None
        delivered = False

        try:
            with urlrequest.urlopen(request, timeout=max(1, int(row.timeout_seconds))) as resp:
                status_code = int(getattr(resp, "status", 200) or 200)
                delivered = 200 <= status_code < 300
        except urlerror.HTTPError as exc:
            status_code = int(exc.code)
            error_msg = str(exc.reason or "http error")
        except Exception as exc:  # noqa: BLE001
            error_msg = str(exc)

        row.last_status_code = status_code
        row.last_error = error_msg
        row.last_notified_at = _utc_now_iso()

        if delivered:
            delivered_count += 1

        results.append(
            {
                "webhook_id": str(row.id),
                "name": row.name,
                "url": row.url,
                "status_code": status_code,
                "delivered": delivered,
                "error": error_msg,
                "dry_run": False,
            }
        )

    db.flush()
    return {
        "tenant_id": str(tenant_id),
        "event_type": event_type,
        "severity": severity,
        "dry_run": dry_run,
        "matched_webhook_total": len(results),
        "delivered_total": delivered_count,
        "results": results,
    }


def create_release_rollout(
    db: Session,
    *,
    tenant_id: UUID,
    approved_by: UUID,
    version: str,
    strategy: str,
    risk_level: str,
    canary_percent: int,
    scope: dict[str, Any] | None,
    note: str | None,
) -> dict[str, Any]:
    """创建发布记录。"""
    row = OpsReleaseRollout(
        tenant_id=tenant_id,
        version=version.strip(),
        strategy=strategy,
        status="running",
        risk_level=risk_level,
        canary_percent=max(0, min(100, int(canary_percent))),
        scope_json=scope or {},
        approved_by=approved_by,
        note=(note or "").strip() or None,
        started_at=_utc_now_iso(),
    )
    db.add(row)
    db.flush()
    return _rollout_to_dict(row)


def list_release_rollouts(
    db: Session,
    *,
    tenant_id: UUID,
    status: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """分页查询发布记录。"""
    stmt = select(OpsReleaseRollout).where(OpsReleaseRollout.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(OpsReleaseRollout.status == status)
    rows = (
        db.execute(stmt.order_by(OpsReleaseRollout.created_at.desc()).offset(offset).limit(limit))
        .scalars()
        .all()
    )
    return [_rollout_to_dict(row) for row in rows]


def rollback_release_rollout(
    db: Session,
    *,
    tenant_id: UUID,
    approved_by: UUID,
    rollout_id: UUID,
    reason: str,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """执行回滚并创建回滚流水。"""
    target = db.get(OpsReleaseRollout, rollout_id)
    if not target or target.tenant_id != tenant_id:
        return None, None

    before = _rollout_to_dict(target)
    target.status = "rolled_back"
    target.completed_at = _utc_now_iso()

    rollback_row = OpsReleaseRollout(
        tenant_id=tenant_id,
        version=f"{target.version}-rollback",
        strategy=target.strategy,
        status="completed",
        risk_level="high",
        canary_percent=0,
        scope_json={"rollback_target": str(target.id), **_safe_dict(target.scope_json)},
        rollback_of=target.id,
        approved_by=approved_by,
        note=(reason or "").strip() or "manual rollback",
        started_at=_utc_now_iso(),
        completed_at=_utc_now_iso(),
    )
    db.add(rollback_row)
    db.flush()
    return before, _rollout_to_dict(rollback_row)


def create_deletion_proof(
    db: Session,
    *,
    tenant_id: UUID,
    deleted_by: UUID,
    resource_type: str,
    resource_id: str,
    ticket_id: UUID | None,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """创建删除证明。"""
    deleted_at = _utc_now_iso()
    subject_raw = f"{tenant_id}:{resource_type}:{resource_id}:{deleted_at}"
    subject_hash = hashlib.sha256(subject_raw.encode("utf-8")).hexdigest()
    signature_raw = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "resource_type": resource_type,
            "resource_id": resource_id,
            "deleted_by": str(deleted_by),
            "deleted_at": deleted_at,
            "subject_hash": subject_hash,
            "payload": payload or {},
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    signature = hashlib.sha256(signature_raw.encode("utf-8")).hexdigest()

    row = OpsDeletionProof(
        tenant_id=tenant_id,
        resource_type=resource_type,
        resource_id=resource_id.strip(),
        subject_hash=subject_hash,
        signature=signature,
        deleted_by=deleted_by,
        deleted_at=deleted_at,
        ticket_id=ticket_id,
        proof_payload=payload or {},
    )
    db.add(row)
    db.flush()
    return _proof_to_dict(row)


def list_deletion_proofs(
    db: Session,
    *,
    tenant_id: UUID,
    resource_type: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """分页查询删除证明。"""
    stmt = select(OpsDeletionProof).where(OpsDeletionProof.tenant_id == tenant_id)
    if resource_type:
        stmt = stmt.where(OpsDeletionProof.resource_type == resource_type)

    rows = (
        db.execute(stmt.order_by(OpsDeletionProof.created_at.desc()).offset(offset).limit(limit))
        .scalars()
        .all()
    )
    return [_proof_to_dict(row) for row in rows]


def build_security_baseline(db: Session, *, tenant_id: UUID) -> dict[str, Any]:
    """输出安全基线最小集状态。"""
    critical_open_incidents = int(
        db.execute(
            select(func.count())
            .select_from(OpsIncidentTicket)
            .where(
                OpsIncidentTicket.tenant_id == tenant_id,
                OpsIncidentTicket.status.in_(["open", "acknowledged"]),
                OpsIncidentTicket.severity == "critical",
            )
        ).scalar_one()
        or 0
    )
    deletion_proof_total = int(
        db.execute(select(func.count()).select_from(OpsDeletionProof).where(OpsDeletionProof.tenant_id == tenant_id)).scalar_one()
        or 0
    )

    checks = [
        {
            "code": "RLS_READY",
            "name": "行级隔离策略（RLS）",
            "status": "planned",
            "message": "当前版本使用应用层租户隔离，RLS 进入上线前启用清单。",
        },
        {
            "code": "PII_MASKING",
            "name": "PII 脱敏策略",
            "status": "pass",
            "message": "对外运行手册使用脱敏口径，默认隐藏敏感身份字段。",
        },
        {
            "code": "DELETION_PROOF",
            "name": "删除证明流程",
            "status": "pass",
            "message": f"已记录 {deletion_proof_total} 条删除证明。",
        },
        {
            "code": "CRITICAL_INCIDENT",
            "name": "未关闭关键故障",
            "status": "warn" if critical_open_incidents > 0 else "pass",
            "message": f"当前未关闭 critical 工单数：{critical_open_incidents}。",
        },
    ]

    overall_status = "pass"
    if any(item["status"] == "warn" for item in checks):
        overall_status = "warn"

    return {
        "tenant_id": str(tenant_id),
        "overall_status": overall_status,
        "checks": checks,
    }


def get_public_sla_spec() -> dict[str, Any]:
    """返回对外 SLA/SLO 口径。"""
    return {
        "version": "2026-03-phase4",
        "service_tier": "standard",
        "availability_sla": {"target": "99.9%", "window": "monthly"},
        "support_sla": {
            "critical_response_minutes": 30,
            "high_response_hours": 4,
            "normal_response_hours": 24,
        },
        "slo": [
            {"code": "ingestion.failure_rate", "target": "<= 10%"},
            {"code": "retrieval.p95_latency_ms", "target": "<= 3000"},
            {"code": "retrieval.citation_coverage", "target": ">= 95%"},
        ],
        "updated_at": _utc_now_iso(),
    }


def get_runbook_summary() -> dict[str, Any]:
    """返回生产运行手册摘要。"""
    return {
        "version": "2026-03-phase4",
        "oncall": {
            "rotation": "24x7 weekly",
            "handoff_required": True,
            "critical_page_channel": "webhook+phone",
        },
        "playbooks": [
            {"code": "INGESTION_DEAD_LETTER", "title": "入库死信排障", "target_minutes": 10},
            {"code": "RETRIEVAL_ZERO_HIT", "title": "检索零命中排障", "target_minutes": 15},
            {"code": "RELEASE_ROLLBACK", "title": "发布回滚流程", "target_minutes": 20},
        ],
        "documents": [
            {"name": "Release Checklist", "path": "docs/release-checklist.md"},
            {"name": "Security Baseline", "path": "docs/security-baseline.md"},
            {"name": "SLA SLO Policy", "path": "docs/sla-slo-policy.md"},
            {"name": "Ops Runbook", "path": "docs/operations-runbook.md"},
        ],
        "updated_at": _utc_now_iso(),
    }
