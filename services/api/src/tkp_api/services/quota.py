"""配额与限流服务。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tkp_api.models.agent import AgentRun
from tkp_api.models.audit import AuditLog
from tkp_api.models.conversation import Message
from tkp_api.models.enums import MessageRole
from tkp_api.models.knowledge import Document, KnowledgeBase, RetrievalLog
from tkp_api.models.quota import QuotaPolicy
from tkp_api.models.workspace import Workspace


class QuotaMetric(StrEnum):
    """配额指标编码。"""

    RETRIEVAL_REQUESTS = "retrieval.requests"
    CHAT_TOKENS = "chat.tokens"
    AGENT_RUNS = "agent.runs"
    DOCUMENT_UPLOADS = "document.uploads"


_SUPPORTED_SCOPE_BY_METRIC: dict[str, set[str]] = {
    QuotaMetric.RETRIEVAL_REQUESTS.value: {"tenant"},
    QuotaMetric.CHAT_TOKENS.value: {"tenant"},
    QuotaMetric.AGENT_RUNS.value: {"tenant"},
    QuotaMetric.DOCUMENT_UPLOADS.value: {"tenant", "workspace"},
}


def _normalize_scope_id(*, tenant_id: UUID, scope_type: str, scope_id: UUID | None) -> UUID:
    if scope_type == "tenant":
        return tenant_id
    if scope_type == "workspace":
        if scope_id is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="workspace scope_id required")
        return scope_id
    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid scope_type")


def _validate_metric_scope(metric_code: str, scope_type: str) -> None:
    supported_scopes = _SUPPORTED_SCOPE_BY_METRIC.get(metric_code)
    if supported_scopes is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid metric_code")
    if scope_type not in supported_scopes:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "INVALID_QUOTA_SCOPE",
                "message": "该指标不支持当前配额范围。",
                "details": {
                    "metric_code": metric_code,
                    "scope_type": scope_type,
                    "supported_scopes": sorted(supported_scopes),
                },
            },
        )


def upsert_quota_policy(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    metric_code: str,
    scope_type: str,
    scope_id: UUID | None,
    limit_value: int,
    window_minutes: int,
    enabled: bool,
) -> dict[str, object]:
    """创建或更新配额策略。"""
    _validate_metric_scope(metric_code, scope_type)
    normalized_scope_id = _normalize_scope_id(tenant_id=tenant_id, scope_type=scope_type, scope_id=scope_id)

    if scope_type == "workspace":
        workspace = db.get(Workspace, normalized_scope_id)
        if not workspace or workspace.tenant_id != tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="workspace not found")

    stmt = (
        select(QuotaPolicy)
        .where(QuotaPolicy.tenant_id == tenant_id)
        .where(QuotaPolicy.scope_type == scope_type)
        .where(QuotaPolicy.scope_id == normalized_scope_id)
        .where(QuotaPolicy.metric_code == metric_code)
        .limit(1)
    )
    row = db.execute(stmt).scalar_one_or_none()
    if row is None:
        row = QuotaPolicy(
            tenant_id=tenant_id,
            scope_type=scope_type,
            scope_id=normalized_scope_id,
            metric_code=metric_code,
            limit_value=limit_value,
            window_minutes=window_minutes,
            enabled=enabled,
            created_by=user_id,
            updated_by=user_id,
        )
        db.add(row)
    else:
        row.limit_value = limit_value
        row.window_minutes = window_minutes
        row.enabled = enabled
        row.updated_by = user_id

    db.flush()
    return _quota_row_to_dict(row)


def list_quota_policies(db: Session, *, tenant_id: UUID) -> list[dict[str, object]]:
    """按租户列出配额策略。"""
    rows = (
        db.execute(
            select(QuotaPolicy)
            .where(QuotaPolicy.tenant_id == tenant_id)
            .order_by(QuotaPolicy.scope_type.asc(), QuotaPolicy.metric_code.asc(), QuotaPolicy.created_at.desc())
        )
        .scalars()
        .all()
    )
    return [_quota_row_to_dict(row) for row in rows]


def _window_since(minutes: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=max(1, minutes))


def _usage_in_window(
    db: Session,
    *,
    tenant_id: UUID,
    scope_type: str,
    scope_id: UUID,
    metric_code: str,
    window_minutes: int,
) -> int:
    since = _window_since(window_minutes)

    if metric_code == QuotaMetric.RETRIEVAL_REQUESTS.value:
        stmt = (
            select(func.count())
            .select_from(RetrievalLog)
            .where(RetrievalLog.tenant_id == tenant_id)
            .where(RetrievalLog.created_at >= since)
        )
        return int(db.execute(stmt).scalar_one() or 0)

    if metric_code == QuotaMetric.CHAT_TOKENS.value:
        rows = (
            db.execute(
                select(Message.usage)
                .where(Message.tenant_id == tenant_id)
                .where(Message.role == MessageRole.ASSISTANT)
                .where(Message.created_at >= since)
            )
            .scalars()
            .all()
        )
        total = 0
        for usage in rows:
            if isinstance(usage, dict):
                value = usage.get("total_tokens")
                if isinstance(value, (int, float)):
                    total += int(value)
        return total

    if metric_code == QuotaMetric.AGENT_RUNS.value:
        stmt = (
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.tenant_id == tenant_id)
            .where(AgentRun.created_at >= since)
        )
        return int(db.execute(stmt).scalar_one() or 0)

    if metric_code == QuotaMetric.DOCUMENT_UPLOADS.value:
        stmt = (
            select(func.count())
            .select_from(Document)
            .where(Document.tenant_id == tenant_id)
            .where(Document.created_at >= since)
        )
        if scope_type == "workspace":
            stmt = stmt.where(Document.workspace_id == scope_id)
        return int(db.execute(stmt).scalar_one() or 0)

    raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid metric_code")


def _quota_row_to_dict(row: QuotaPolicy) -> dict[str, object]:
    return {
        "id": str(row.id),
        "tenant_id": str(row.tenant_id),
        "scope_type": row.scope_type,
        "scope_id": str(row.scope_id),
        "metric_code": row.metric_code,
        "limit_value": int(row.limit_value),
        "window_minutes": int(row.window_minutes),
        "enabled": bool(row.enabled),
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def _raise_quota_exceeded(
    *,
    metric_code: str,
    scope_type: str,
    scope_id: UUID,
    limit_value: int,
    used_value: int,
    projected_value: int,
    window_minutes: int,
) -> None:
    raise HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail={
            "code": "QUOTA_EXCEEDED",
            "message": "配额已超限，请稍后重试或联系管理员调整策略。",
            "details": {
                "reason": "quota_exceeded",
                "metric_code": metric_code,
                "scope_type": scope_type,
                "scope_id": str(scope_id),
                "limit_value": int(limit_value),
                "used_value": int(used_value),
                "projected_value": int(projected_value),
                "window_minutes": int(window_minutes),
            },
        },
    )


def enforce_quota(
    db: Session,
    *,
    tenant_id: UUID,
    metric_code: str,
    projected_increment: int,
    workspace_id: UUID | None = None,
    actor_user_id: UUID | None = None,
) -> None:
    """执行配额检查，超限时抛出 429。"""
    if projected_increment <= 0:
        return

    scope_pairs: list[tuple[str, UUID]] = [("tenant", tenant_id)]
    if workspace_id is not None:
        scope_pairs.append(("workspace", workspace_id))

    for scope_type, scope_id in scope_pairs:
        try:
            _validate_metric_scope(metric_code, scope_type)
        except HTTPException:
            continue
        row = (
            db.execute(
                select(QuotaPolicy)
                .where(QuotaPolicy.tenant_id == tenant_id)
                .where(QuotaPolicy.scope_type == scope_type)
                .where(QuotaPolicy.scope_id == scope_id)
                .where(QuotaPolicy.metric_code == metric_code)
                .where(QuotaPolicy.enabled.is_(True))
                .limit(1)
            )
            .scalar_one_or_none()
        )
        if row is None:
            continue

        used_value = _usage_in_window(
            db,
            tenant_id=tenant_id,
            scope_type=scope_type,
            scope_id=scope_id,
            metric_code=metric_code,
            window_minutes=int(row.window_minutes),
        )
        projected_value = used_value + projected_increment
        if projected_value <= int(row.limit_value):
            continue

        db.add(
            AuditLog(
                tenant_id=tenant_id,
                actor_user_id=actor_user_id,
                action="quota.exceeded",
                resource_type="quota_policy",
                resource_id=str(row.id),
                after_json={
                    "metric_code": metric_code,
                    "scope_type": scope_type,
                    "scope_id": str(scope_id),
                    "limit_value": int(row.limit_value),
                    "used_value": int(used_value),
                    "projected_value": int(projected_value),
                    "window_minutes": int(row.window_minutes),
                },
                ip=None,
                user_agent=None,
            )
        )
        db.commit()
        _raise_quota_exceeded(
            metric_code=metric_code,
            scope_type=scope_type,
            scope_id=scope_id,
            limit_value=int(row.limit_value),
            used_value=int(used_value),
            projected_value=int(projected_value),
            window_minutes=int(row.window_minutes),
        )


def list_quota_alerts(
    db: Session,
    *,
    tenant_id: UUID,
    limit: int = 20,
    window_hours: int = 24,
) -> list[dict[str, object]]:
    """读取窗口内配额超限告警事件。"""
    since = datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))
    rows = (
        db.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant_id)
            .where(AuditLog.action == "quota.exceeded")
            .where(AuditLog.created_at >= since)
            .order_by(AuditLog.created_at.desc())
            .limit(max(1, min(limit, 200)))
        )
        .scalars()
        .all()
    )

    data: list[dict[str, object]] = []
    for row in rows:
        payload = row.after_json if isinstance(row.after_json, dict) else {}
        data.append(
            {
                "alert_id": str(row.id),
                "metric_code": str(payload.get("metric_code") or ""),
                "scope_type": str(payload.get("scope_type") or "tenant"),
                "scope_id": str(payload.get("scope_id") or tenant_id),
                "limit_value": int(payload.get("limit_value") or 0),
                "used_value": int(payload.get("used_value") or 0),
                "projected_value": int(payload.get("projected_value") or 0),
                "window_minutes": int(payload.get("window_minutes") or 0),
                "created_at": row.created_at,
            }
        )
    return data


def resolve_workspace_scope_for_kbs(
    db: Session,
    *,
    tenant_id: UUID,
    kb_ids: list[UUID],
) -> UUID | None:
    """根据 KB 列表推导唯一 workspace_id（无唯一结果则返回 None）。"""
    if not kb_ids:
        return None
    rows = (
        db.execute(
            select(KnowledgeBase.workspace_id)
            .where(KnowledgeBase.tenant_id == tenant_id)
            .where(KnowledgeBase.id.in_(kb_ids))
        )
        .scalars()
        .all()
    )
    unique_ids = {item for item in rows if item is not None}
    if len(unique_ids) != 1:
        return None
    return next(iter(unique_ids))
