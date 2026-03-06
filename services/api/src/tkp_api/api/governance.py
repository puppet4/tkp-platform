"""数据治理 API 端点。"""

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from tkp_api.db.session import get_db
from tkp_api.middleware.auth import get_current_user
from tkp_api.governance.deletion import DeletionService
from tkp_api.governance.retention import RetentionService
from tkp_api.governance.pii import get_pii_masker
from tkp_api.models.enums import TenantRole

logger = logging.getLogger("tkp_api.api.governance")

router = APIRouter(prefix="/api/governance", tags=["governance"])


def require_admin_role(current_user: dict) -> None:
    """检查用户是否有管理员权限。

    Args:
        current_user: 当前用户信息

    Raises:
        HTTPException: 如果用户没有管理员权限
    """
    tenant_role = current_user.get("tenant_role")
    if tenant_role not in [TenantRole.OWNER.value, TenantRole.ADMIN.value]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="需要管理员权限才能执行此操作",
        )


@router.post("/deletion/requests")
async def create_deletion_request(
    resource_type: str,
    resource_id: UUID,
    reason: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """创建数据删除请求。"""
    service = DeletionService(db)

    try:
        request = service.create_deletion_request(
            tenant_id=UUID(current_user["tenant_id"]),
            user_id=UUID(current_user["user_id"]),
            resource_type=resource_type,
            resource_id=resource_id,
            reason=reason,
        )

        return {
            "request_id": str(request.request_id),
            "status": request.status,
            "requested_at": request.requested_at.isoformat(),
        }
    except Exception as exc:
        logger.exception("failed to create deletion request: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create deletion request: {exc}",
        )


@router.post("/deletion/requests/{request_id}/approve")
async def approve_deletion_request(
    request_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批准数据删除请求（需要管理员权限）。"""
    require_admin_role(current_user)

    service = DeletionService(db)

    try:
        success = service.approve_deletion_request(
            request_id=request_id,
            approved_by=UUID(current_user["user_id"]),
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
            detail=f"Failed to approve deletion request: {exc}",
        )


@router.post("/deletion/requests/{request_id}/reject")
async def reject_deletion_request(
    request_id: UUID,
    reject_reason: str,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """拒绝数据删除请求（需要管理员权限）。"""
    require_admin_role(current_user)

    service = DeletionService(db)

    try:
        success = service.reject_deletion_request(
            request_id=request_id,
            rejected_by=UUID(current_user["user_id"]),
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
            detail=f"Failed to reject deletion request: {exc}",
        )


@router.post("/deletion/requests/{request_id}/execute")
async def execute_deletion(
    request_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """执行数据删除并生成证明（需要管理员权限）。"""
    require_admin_role(current_user)

    service = DeletionService(db)

    try:
        proof = service.execute_deletion(
            request_id=request_id,
            executed_by=UUID(current_user["user_id"]),
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
            detail=f"Failed to execute deletion: {exc}",
        )


@router.get("/deletion/proofs/{proof_id}")
async def get_deletion_proof(
    proof_id: UUID,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """获取数据删除证明。"""
    service = DeletionService(db)

    try:
        proof = service.get_deletion_proof(proof_id)

        if not proof:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Deletion proof not found",
            )

        # 验证租户权限
        if str(proof.tenant_id) != current_user["tenant_id"]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied",
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
            detail=f"Failed to get deletion proof: {exc}",
        )


@router.post("/retention/cleanup")
async def cleanup_expired_data(
    resource_type: str,
    dry_run: bool = True,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """清理过期数据（需要管理员权限）。"""
    require_admin_role(current_user)

    service = RetentionService(db)

    try:
        result = service.delete_expired_records(
            resource_type=resource_type,
            tenant_id=UUID(current_user["tenant_id"]),
            dry_run=dry_run,
        )

        return result
    except Exception as exc:
        logger.exception("failed to cleanup expired data: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to cleanup expired data: {exc}",
        )


@router.post("/pii/mask")
async def mask_pii_data(
    text: str,
    pii_types: list[str] | None = None,
    current_user: dict = Depends(get_current_user),
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
            detail=f"Failed to mask PII: {exc}",
        )
