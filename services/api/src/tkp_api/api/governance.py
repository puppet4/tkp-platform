"""数据治理 API 端点。"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from tkp_api.db.session import get_db
from tkp_api.dependencies import RequestContext, get_request_context
from tkp_api.governance.deletion import DeletionService
from tkp_api.governance.pii import get_pii_masker
from tkp_api.governance.retention import RetentionService
from tkp_api.models.enums import TenantRole
from tkp_api.services import PermissionAction, require_tenant_action
from tkp_api.utils.response import success
from tkp_api.utils.permissions import is_admin_role

logger = logging.getLogger("tkp_api.api.governance")

router = APIRouter(prefix="/governance", tags=["governance"])
HTTP_422_UNPROCESSABLE = getattr(
    status,
    "HTTP_422_UNPROCESSABLE_CONTENT",
    status.HTTP_422_UNPROCESSABLE_ENTITY,
)


@router.post("/deletion/requests")
async def create_deletion_request(
    payload: DeletionRequestCreate,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """创建数据删除请求。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.GOVERNANCE_DELETION_REQUEST_CREATE,
    )
    service = DeletionService(db)

    try:
        req = service.create_deletion_request(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            resource_type=payload.resource_type,
            resource_id=payload.resource_id,
            reason=payload.reason,
        )
        return success(
            request,
            {
                "request_id": str(req.request_id),
                "status": req.status,
                "requested_at": req.requested_at.isoformat(),
            },
        )
    except ValueError as exc:
        detail = str(exc)
        code = HTTP_422_UNPROCESSABLE if "unsupported resource type" in detail else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=detail) from exc
    except Exception as exc:
        logger.exception("failed to create deletion request: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create deletion request",
        ) from exc


@router.get("/deletion/requests")
async def list_deletion_requests(
    request: Request,
    deletion_status: str | None = Query(default=None, alias="status"),
    status_filter: str | None = Query(default=None),
    limit: int = 50,
    offset: int = 0,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """分页查询数据删除请求。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.GOVERNANCE_DELETION_REQUEST_READ,
    )
    service = DeletionService(db)
    try:
        effective_status = deletion_status or status_filter
        data = service.list_deletion_requests(
            tenant_id=ctx.tenant_id,
            status=effective_status,
            limit=limit,
            offset=offset,
            requester_user_id=None if is_admin_role(ctx) else ctx.user_id,
        )
        return success(
            request,
            {"requests": data},
            meta={"total": len(data), "limit": limit, "offset": offset},
        )
    except Exception as exc:
        logger.exception("failed to list deletion requests: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list deletion requests",
        ) from exc


@router.post("/deletion/requests/{request_id}/approve")
async def approve_deletion_request(
    request_id: UUID,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """批准数据删除请求（需要管理员权限）。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.GOVERNANCE_DELETION_REQUEST_REVIEW,
    )
    service = DeletionService(db)

    try:
        result = service.approve_deletion_request(
            request_id=request_id,
            tenant_id=ctx.tenant_id,
            approved_by=ctx.user_id,
        )
        if not result:
            state = service.get_deletion_request_state(request_id=request_id, tenant_id=ctx.tenant_id)
            if state is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deletion request not found")
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Deletion request is already {state}")
        return success(request, {"status": "approved"})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("failed to approve deletion request: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to approve deletion request",
        ) from exc


@router.post("/deletion/requests/{request_id}/reject")
async def reject_deletion_request(
    request_id: UUID,
    payload: DeletionRequestReject,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """拒绝数据删除请求（需要管理员权限）。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.GOVERNANCE_DELETION_REQUEST_REVIEW,
    )
    service = DeletionService(db)

    try:
        result = service.reject_deletion_request(
            request_id=request_id,
            tenant_id=ctx.tenant_id,
            rejected_by=ctx.user_id,
            reject_reason=payload.reason,
        )
        if not result:
            state = service.get_deletion_request_state(request_id=request_id, tenant_id=ctx.tenant_id)
            if state is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deletion request not found")
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Deletion request is already {state}")
        return success(request, {"status": "rejected"})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("failed to reject deletion request: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to reject deletion request",
        ) from exc


@router.post("/deletion/requests/{request_id}/execute")
async def execute_deletion(
    request_id: UUID,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """执行数据删除并生成证明（需要管理员权限）。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.GOVERNANCE_DELETION_EXECUTE,
    )
    service = DeletionService(db)

    try:
        proof = service.execute_deletion(
            request_id=request_id,
            tenant_id=ctx.tenant_id,
            executed_by=ctx.user_id,
        )
        if not proof:
            state = service.get_deletion_request_state(request_id=request_id, tenant_id=ctx.tenant_id)
            if state is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deletion request not found")
            if state != "approved":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Deletion request is {state}")
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Deletion execution failed")

        return success(
            request,
            {
                "proof_id": str(proof.proof_id),
                "deleted_at": proof.deleted_at.isoformat(),
                "proof_hash": proof.proof_hash,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("failed to execute deletion: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to execute deletion",
        ) from exc


@router.post("/deletion/requests/{request_id}/cancel")
async def cancel_deletion_request(
    request_id: UUID,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """取消待处理删除请求。管理员可取消任意请求，普通用户仅可取消自己的请求。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.GOVERNANCE_DELETION_REQUEST_CREATE,
    )
    service = DeletionService(db)
    is_admin = _is_admin_role(ctx)
    try:
        result = service.cancel_deletion_request(
            request_id=request_id,
            tenant_id=ctx.tenant_id,
            requester_user_id=ctx.user_id,
            is_admin=is_admin,
        )
        if not result:
            state = service.get_deletion_request_state(request_id=request_id, tenant_id=ctx.tenant_id)
            if state is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Deletion request not found")
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Deletion request is already {state}")
        return success(request, {"status": "cancelled"})
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("failed to cancel deletion request: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cancel deletion request",
        ) from exc


@router.get("/deletion/proofs/{proof_id}")
async def get_deletion_proof(
    proof_id: UUID,
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """获取数据删除证明。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.GOVERNANCE_DELETION_REQUEST_READ,
    )
    service = DeletionService(db)

    try:
        proof = service.get_deletion_proof(proof_id=proof_id, tenant_id=ctx.tenant_id)
        if not proof:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deletion proof not found",
            )

        return success(
            request,
            {
                "proof_id": str(proof.proof_id),
                "request_id": str(proof.request_id),
                "resource_type": proof.resource_type,
                "resource_id": str(proof.resource_id),
                "deleted_at": proof.deleted_at.isoformat(),
                "data_hash": proof.data_hash,
                "proof_hash": proof.proof_hash,
            },
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("failed to get deletion proof: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get deletion proof",
        ) from exc


@router.post("/retention/cleanup")
async def cleanup_expired_data(
    resource_type: str,
    request: Request,
    dry_run: bool = True,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """清理过期数据（需要管理员权限）。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.GOVERNANCE_RETENTION_CLEANUP,
    )
    service = RetentionService(db)

    try:
        result = service.delete_expired_records(
            resource_type=resource_type,
            tenant_id=ctx.tenant_id,
            dry_run=dry_run,
        )
        if "error" in result:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(result["error"]))
        return success(request, result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("failed to cleanup expired data: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to cleanup expired data",
        ) from exc


@router.post("/pii/mask")
async def mask_pii_data(
    text: str,
    request: Request,
    pii_types: list[str] | None = None,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """脱敏文本中的 PII。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.GOVERNANCE_PII_MASK,
    )
    try:
        masker = get_pii_masker()
        masked_text = masker.mask_text(text, pii_types)
        return success(
            request,
            {
                "original_length": len(text),
                "masked_text": masked_text,
                "masked_length": len(masked_text),
            },
        )
    except Exception as exc:
        logger.exception("failed to mask PII: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mask PII",
        ) from exc


@router.get("/retention/policies")
async def list_retention_policies(
    request: Request,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询保留策略列表。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.GOVERNANCE_RETENTION_CLEANUP,
    )
    service = RetentionService(db)

    policies = [
        {
            "resource_type": policy.resource_type,
            "retention_days": policy.retention_days,
            "auto_delete": policy.auto_delete,
            "archive_before_delete": policy.archive_before_delete,
        }
        for policy in service.policies.values()
    ]

    return success(request, {"policies": policies})


@router.post("/retention/policies")
async def create_retention_policy(
    resource_type: str,
    retention_days: int,
    request: Request,
    auto_delete: bool = False,
    archive_before_delete: bool = False,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """创建或更新保留策略。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.GOVERNANCE_RETENTION_CLEANUP,
    )

    from tkp_api.governance.retention import RetentionPolicy

    service = RetentionService(db)
    policy = RetentionPolicy(
        resource_type=resource_type,
        retention_days=retention_days,
        auto_delete=auto_delete,
        archive_before_delete=archive_before_delete,
    )
    service.set_policy(policy)

    return success(
        request,
        {
            "resource_type": policy.resource_type,
            "retention_days": policy.retention_days,
            "auto_delete": policy.auto_delete,
            "archive_before_delete": policy.archive_before_delete,
        },
    )


@router.put("/retention/policies/{resource_type}")
async def update_retention_policy(
    resource_type: str,
    retention_days: int,
    request: Request,
    auto_delete: bool = False,
    archive_before_delete: bool = False,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """更新保留策略。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.GOVERNANCE_RETENTION_CLEANUP,
    )

    from tkp_api.governance.retention import RetentionPolicy

    service = RetentionService(db)
    policy = RetentionPolicy(
        resource_type=resource_type,
        retention_days=retention_days,
        auto_delete=auto_delete,
        archive_before_delete=archive_before_delete,
    )
    service.set_policy(policy)

    return success(
        request,
        {
            "resource_type": policy.resource_type,
            "retention_days": policy.retention_days,
            "auto_delete": policy.auto_delete,
            "archive_before_delete": policy.archive_before_delete,
        },
    )
