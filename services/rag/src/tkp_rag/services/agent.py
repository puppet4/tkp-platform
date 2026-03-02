"""RAG 侧智能体规划服务。"""

from __future__ import annotations

from typing import Any
from uuid import UUID


def build_plan(
    *,
    tenant_id: UUID,
    user_id: UUID,
    task: str,
    kb_ids: list[UUID],
    conversation_id: UUID | None,
    tool_policy: dict[str, Any],
) -> dict[str, Any]:
    """生成最小可执行规划结果。"""
    plan_json: dict[str, Any] = {
        "source": "rag",
        "tenant_id": str(tenant_id),
        "user_id": str(user_id),
        "task": task,
        "kb_ids": [str(kb_id) for kb_id in kb_ids],
        "conversation_id": str(conversation_id) if conversation_id else None,
        "tool_policy": tool_policy,
        "steps": [
            {"order": 1, "name": "retrieve", "description": "检索相关知识片段"},
            {"order": 2, "name": "synthesize", "description": "基于检索结果生成执行建议"},
        ],
    }
    return {"plan_json": plan_json, "tool_calls": [], "status": "queued"}

