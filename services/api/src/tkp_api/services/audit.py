"""审计服务。"""

from typing import Any
from uuid import UUID

from fastapi import Request
from sqlalchemy.orm import Session

from tkp_api.models.audit import AuditLog


def _client_ip(request: Request) -> str | None:
    """从代理头或连接信息中提取客户端 IP。"""
    # 优先读取反向代理透传头，兼容网关/负载均衡场景。
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


def audit_log(
    db: Session,
    request: Request,
    tenant_id: UUID,
    actor_user_id: UUID | None,
    action: str,
    resource_type: str,
    resource_id: str,
    before_json: dict[str, Any] | None = None,
    after_json: dict[str, Any] | None = None,
) -> None:
    """写入统一审计日志。"""
    db.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            before_json=before_json,
            after_json=after_json,
            ip=_client_ip(request),
            user_agent=request.headers.get("user-agent"),
        )
    )
