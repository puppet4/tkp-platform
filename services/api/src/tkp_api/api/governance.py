"""数据治理 API 端点。"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from tkp_api.db.session import get_db
from tkp_api.dependencies import RequestContext, get_request_context
from tkp_api.governance.deletion import DeletionService
from tkp_api.governance.pii import get_pii_masker
from tkp_api.governance.retention import RetentionService
from tkp_api.models.enums import TenantRole

logger = logging.getLogger("tkp_api.api.governance")

router = APIRouter(prefix="/governance", tags=["governance"])
HTTP_422_UNPROCESSABLE = getattr(
    status,
    "HTTP_422_UNPROCESSABLE_CONTENT",
    status.HTTP_422_UNPROCESSABLE_ENTITY,
)


def require_admin_role(ctx: RequestContext) -> None:
    """检查用户是否有管理员权限。"""
    if ctx.tenant_role not in {TenantRole.OWNER, TenantRole.ADMIN, TenantRole.OWNER.value, TenantRole.ADMIN.value}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限才能执行此操作",
        )


@router.post("/deletion/requests")
async def create_deletion_request(
    resource_type: str,
    resource_id: UUID,
    reason: str,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """创建数据删除请求。"""
    service = DeletionService(db)

    try:
        request = service.create_deletion_request(
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            reason=reason,
        )
        return {
            "request_id": str(request.request_id),
            "status": request.status,
            "requested_at": request.requested_at.isoformat(),
        }
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
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """分页查询数据删除请求。"""
    service = DeletionService(db)
    try:
        data = service.list_deletion_requests(
            tenant_id=ctx.tenant_id,
            status=status_filter,
            limit=limit,
            offset=offset,
        )
        return {"requests": data, "total": len(data), "limit": limit, "offset": offset}
    except Exception as exc:
        logger.exception("failed to list deletion requests: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to list deletion requests",
        ) from exc


@router.post("/deletion/requests/{request_id}/approve")
async def approve_deletion_request(
    request_id: UUID,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """批准数据删除请求（需要管理员权限）。"""
    require_admin_role(ctx)
    service = DeletionService(db)

    try:
        success = service.approve_deletion_request(
            request_id=request_id,
            tenant_id=ctx.tenant_id,
            approved_by=ctx.user_id,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deletion request not found or already processed",
            )
        return {"status": "approved"}
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
    reject_reason: str,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """拒绝数据删除请求（需要管理员权限）。"""
    require_admin_role(ctx)
    service = DeletionService(db)

    try:
        success = service.reject_deletion_request(
            request_id=request_id,
            tenant_id=ctx.tenant_id,
            rejected_by=ctx.user_id,
            reject_reason=reject_reason,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deletion request not found or already processed",
            )
        return {"status": "rejected"}
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
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """执行数据删除并生成证明（需要管理员权限）。"""
    require_admin_role(ctx)
    service = DeletionService(db)

    try:
        proof = service.execute_deletion(
            request_id=request_id,
            tenant_id=ctx.tenant_id,
            executed_by=ctx.user_id,
        )
        if not proof:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deletion request not found or not approved",
            )

        return {
            "proof_id": str(proof.proof_id),
            "deleted_at": proof.deleted_at.isoformat(),
            "proof_hash": proof.proof_hash,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("failed to execute deletion: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to execute deletion",
        ) from exc


@router.get("/deletion/proofs/{proof_id}")
async def get_deletion_proof(
    proof_id: UUID,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """获取数据删除证明。"""
    service = DeletionService(db)

    try:
        proof = service.get_deletion_proof(proof_id=proof_id, tenant_id=ctx.tenant_id)
        if not proof:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deletion proof not found",
            )

        return {
            "proof_id": str(proof.proof_id),
            "request_id": str(proof.request_id),
            "resource_type": proof.resource_type,
            "resource_id": str(proof.resource_id),
            "deleted_at": proof.deleted_at.isoformat(),
            "data_hash": proof.data_hash,
            "proof_hash": proof.proof_hash,
        }
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
    dry_run: bool = True,
    ctx: RequestContext = Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """清理过期数据（需要管理员权限）。"""
    require_admin_role(ctx)
    service = RetentionService(db)

    try:
        result = service.delete_expired_records(
            resource_type=resource_type,
            tenant_id=ctx.tenant_id,
            dry_run=dry_run,
        )
        if "error" in result:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(result["error"]))
        return result
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
    pii_types: list[str] | None = None,
    _: RequestContext = Depends(get_request_context),
):
    """脱敏文本中的 PII。"""
    try:
        masker = get_pii_masker()
        masked_text = masker.mask_text(text, pii_types)
        return {
            "original_length": len(text),
            "masked_text": masked_text,
            "masked_length": len(masked_text),
        }
    except Exception as exc:
        logger.exception("failed to mask PII: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to mask PII",
        ) from exc
