"""成本计量聚合服务。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tkp_api.models.agent import AgentRun
from tkp_api.models.conversation import Message
from tkp_api.models.enums import MessageRole
from tkp_api.models.knowledge import RetrievalLog

_PROMPT_TOKEN_UNIT_COST = 0.000001
_COMPLETION_TOKEN_UNIT_COST = 0.000002


def build_tenant_cost_summary(db: Session, *, tenant_id: UUID, window_hours: int = 24) -> dict[str, object]:
    """汇总租户维度成本与用量。"""
    since = datetime.now(timezone.utc) - timedelta(hours=max(1, window_hours))

    retrieval_request_total = int(
        db.execute(
            select(func.count())
            .select_from(RetrievalLog)
            .where(RetrievalLog.tenant_id == tenant_id)
            .where(RetrievalLog.created_at >= since)
        ).scalar_one()
        or 0
    )

    usage_rows = (
        db.execute(
            select(Message.usage)
            .where(Message.tenant_id == tenant_id)
            .where(Message.role == MessageRole.ASSISTANT)
            .where(Message.created_at >= since)
        )
        .scalars()
        .all()
    )

    chat_completion_total = len(usage_rows)
    prompt_tokens_total = 0
    completion_tokens_total = 0
    total_tokens = 0
    for usage in usage_rows:
        if not isinstance(usage, dict):
            continue
        prompt_tokens_total += int(usage.get("prompt_tokens") or 0)
        completion_tokens_total += int(usage.get("completion_tokens") or 0)
        total_tokens += int(usage.get("total_tokens") or 0)

    agent_run_total = int(
        db.execute(
            select(func.count())
            .select_from(AgentRun)
            .where(AgentRun.tenant_id == tenant_id)
            .where(AgentRun.created_at >= since)
        ).scalar_one()
        or 0
    )

    agent_cost_total = float(
        db.execute(
            select(func.coalesce(func.sum(AgentRun.cost), 0))
            .where(AgentRun.tenant_id == tenant_id)
            .where(AgentRun.created_at >= since)
        ).scalar_one()
        or 0
    )

    chat_estimated_cost = (prompt_tokens_total * _PROMPT_TOKEN_UNIT_COST) + (
        completion_tokens_total * _COMPLETION_TOKEN_UNIT_COST
    )
    estimated_total_cost = round(chat_estimated_cost + agent_cost_total, 6)

    return {
        "tenant_id": str(tenant_id),
        "window_hours": int(window_hours),
        "retrieval_request_total": retrieval_request_total,
        "chat_completion_total": chat_completion_total,
        "prompt_tokens_total": int(prompt_tokens_total),
        "completion_tokens_total": int(completion_tokens_total),
        "total_tokens": int(total_tokens),
        "agent_run_total": agent_run_total,
        "agent_cost_total": round(agent_cost_total, 6),
        "chat_estimated_cost": round(chat_estimated_cost, 6),
        "estimated_total_cost": estimated_total_cost,
    }
