"""智能体运行规划服务。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from tkp_api.core.config import get_settings
from tkp_api.models.enums import AgentRunStatus
from tkp_api.services.rag_client import post_rag_json


def _local_plan(task: str, kb_ids: list[UUID], tool_policy: dict[str, Any]) -> dict[str, Any]:
    """本地兜底规划。"""
    return {
        "plan_json": {
            "task": task,
            "kb_ids": [str(kb_id) for kb_id in kb_ids],
            "tool_policy": tool_policy,
            "source": "api-local",
        },
        "tool_calls": [],
        "status": AgentRunStatus.QUEUED,
    }


def build_agent_plan(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    task: str,
    kb_ids: list[UUID],
    conversation_id: UUID | None,
    tool_policy: dict[str, Any],
) -> dict[str, Any]:
    """构建智能体运行计划。"""
    _ = db
    settings = get_settings()
    if not settings.rag_base_url:
        return _local_plan(task, kb_ids, tool_policy)

    remote_data = post_rag_json(
        settings.rag_base_url,
        "/internal/agent/plan",
        payload={
            "tenant_id": str(tenant_id),
            "user_id": str(user_id),
            "task": task,
            "kb_ids": [str(kb_id) for kb_id in kb_ids],
            "conversation_id": str(conversation_id) if conversation_id else None,
            "tool_policy": tool_policy,
        },
        timeout_seconds=settings.rag_timeout_seconds,
        internal_token=settings.internal_service_token,
        max_retries=settings.rag_max_retries,
        retry_backoff_seconds=settings.rag_retry_backoff_seconds,
        circuit_fail_threshold=settings.rag_circuit_breaker_fail_threshold,
        circuit_open_seconds=settings.rag_circuit_breaker_open_seconds,
    )

    plan_json = remote_data.get("plan_json", {})
    tool_calls = remote_data.get("tool_calls", [])
    status_value = str(remote_data.get("status") or AgentRunStatus.QUEUED)
    try:
        status_enum = AgentRunStatus(status_value)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "RAG_UPSTREAM_INVALID_RESPONSE",
                "message": "RAG 返回了非法的智能体状态值。",
                "details": {"reason": "invalid_agent_status", "status": status_value},
            },
        ) from exc

    if not isinstance(plan_json, dict) or not isinstance(tool_calls, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": "RAG_UPSTREAM_INVALID_RESPONSE",
                "message": "RAG 返回的智能体规划结构不完整。",
                "details": {"reason": "invalid_agent_plan_payload"},
            },
        )
    return {"plan_json": plan_json, "tool_calls": tool_calls, "status": status_enum}
