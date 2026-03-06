"""数据删除证明流程（GDPR 合规）。

提供数据删除请求、审批、执行、证明生成的完整流程。
"""

import hashlib
import logging
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("tkp_api.governance.deletion")


class DeletionRequest:
    """数据删除请求。"""

    def __init__(
        self,
        *,
        request_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        resource_type: str,
        resource_id: UUID,
        reason: str,
        requested_at: datetime,
        status: str = "pending",
    ):
        """初始化删除请求。"""
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.user_id = user_id
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.reason = reason
        self.requested_at = requested_at
        self.status = status


class DeletionProof:
    """数据删除证明。"""

    def __init__(
        self,
        *,
        proof_id: UUID,
        request_id: UUID,
        tenant_id: UUID,
        resource_type: str,
        resource_id: UUID,
        deleted_at: datetime,
        deleted_by: UUID,
        data_hash: str,
        proof_hash: str,
    ):
        """初始化删除证明。"""
        self.proof_id = proof_id
        self.request_id = request_id
        self.tenant_id = tenant_id
        self.resource_type = resource_type
        self.resource_id = resource_id
        self.deleted_at = deleted_at
        self.deleted_by = deleted_by
        self.data_hash = data_hash
        self.proof_hash = proof_hash


class DeletionService:
    """数据删除服务。"""

    def __init__(self, db: Session):
        """初始化删除服务。"""
        self.db = db

    def create_deletion_request(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        resource_type: str,
        resource_id: UUID,
        reason: str,
    ) -> DeletionRequest:
        """创建删除请求。

        Args:
            tenant_id: 租户 ID
            user_id: 请求用户 ID
            resource_type: 资源类型（document/user/conversation）
            resource_id: 资源 ID
            reason: 删除原因

        Returns:
            删除请求对象
        """
        request_id = uuid4()
        requested_at = datetime.utcnow()

        # 插入删除请求记录
        query = text(
            """
            INSERT INTO deletion_requests (
                id, tenant_id, user_id, resource_type, resource_id,
                reason, status, requested_at, created_at
            ) VALUES (
                :id, :tenant_id, :user_id, :resource_type, :resource_id,
                :reason, :status, :requested_at, :created_at
            )
        """
        )

        self.db.execute(
            query,
            {
                "id": str(request_id),
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "resource_type": resource_type,
                "resource_id": str(resource_id),
                "reason": reason,
                "status": "pending",
                "requested_at": requested_at,
                "created_at": requested_at,
            },
        )
        self.db.commit()

        logger.info(
            "deletion request created: request_id=%s, resource=%s/%s",
            request_id,
            resource_type,
            resource_id,
        )

        return DeletionRequest(
            request_id=request_id,
            tenant_id=tenant_id,
            user_id=user_id,
            resource_type=resource_type,
            resource_id=resource_id,
            reason=reason,
            requested_at=requested_at,
            status="pending",
        )

    def approve_deletion_request(self, request_id: UUID, approved_by: UUID) -> bool:
        """批准删除请求。

        Args:
            request_id: 请求 ID
            approved_by: 批准人 ID

        Returns:
            是否批准成功
        """
        query = text(
            """
            UPDATE deletion_requests
            SET status = 'approved',
                approved_by = :approved_by,
                approved_at = :approved_at
            WHERE id = :request_id AND status = 'pending'
        """
        )

        result = self.db.execute(
            query,
            {
                "request_id": str(request_id),
                "approved_by": str(approved_by),
                "approved_at": datetime.utcnow(),
            },
        )
        self.db.commit()

        success = result.rowcount > 0
        if success:
            logger.info("deletion request approved: request_id=%s", request_id)
        else:
            logger.warning("deletion request not found or already processed: request_id=%s", request_id)

        return success

    def reject_deletion_request(self, request_id: UUID, rejected_by: UUID, reject_reason: str) -> bool:
        """拒绝删除请求。

        Args:
            request_id: 请求 ID
            rejected_by: 拒绝人 ID
            reject_reason: 拒绝原因

        Returns:
            是否拒绝成功
        """
        query = text(
            """
            UPDATE deletion_requests
            SET status = 'rejected',
                rejected_by = :rejected_by,
                rejected_at = :rejected_at,
                reject_reason = :reject_reason
            WHERE id = :request_id AND status = 'pending'
        """
        )

        result = self.db.execute(
            query,
            {
                "request_id": str(request_id),
                "rejected_by": str(rejected_by),
                "rejected_at": datetime.utcnow(),
                "reject_reason": reject_reason,
            },
        )
        self.db.commit()

        success = result.rowcount > 0
        if success:
            logger.info("deletion request rejected: request_id=%s", request_id)

        return success

    def execute_deletion(self, request_id: UUID, executed_by: UUID) -> DeletionProof | None:
        """执行删除操作并生成证明。

        Args:
            request_id: 请求 ID
            executed_by: 执行人 ID

        Returns:
            删除证明对象，失败返回 None
        """
        # 获取删除请求
        query = text(
            """
            SELECT id, tenant_id, resource_type, resource_id
            FROM deletion_requests
            WHERE id = :request_id AND status = 'approved'
        """
        )

        result = self.db.execute(query, {"request_id": str(request_id)})
        row = result.fetchone()

        if not row:
            logger.warning("deletion request not found or not approved: request_id=%s", request_id)
            return None

        tenant_id = UUID(row.tenant_id)
        resource_type = row.resource_type
        resource_id = UUID(row.resource_id)

        # 获取资源数据快照（用于生成哈希）
        data_snapshot = self._get_resource_snapshot(resource_type, resource_id)
        if not data_snapshot:
            logger.error("resource not found: %s/%s", resource_type, resource_id)
            return None

        # 计算数据哈希
        data_hash = self._calculate_hash(data_snapshot)

        # 执行删除
        deleted = self._delete_resource(resource_type, resource_id, tenant_id)
        if not deleted:
            logger.error("failed to delete resource: %s/%s", resource_type, resource_id)
            return None

        # 生成删除证明
        proof_id = uuid4()
        deleted_at = datetime.utcnow()

        # 计算证明哈希（包含所有关键信息）
        proof_data = f"{proof_id}{request_id}{resource_type}{resource_id}{deleted_at.isoformat()}{data_hash}"
        proof_hash = hashlib.sha256(proof_data.encode()).hexdigest()

        # 保存删除证明
        query = text(
            """
            INSERT INTO deletion_proofs (
                id, request_id, tenant_id, resource_type, resource_id,
                deleted_at, deleted_by, data_hash, proof_hash, created_at
            ) VALUES (
                :id, :request_id, :tenant_id, :resource_type, :resource_id,
                :deleted_at, :deleted_by, :data_hash, :proof_hash, :created_at
            )
        """
        )

        self.db.execute(
            query,
            {
                "id": str(proof_id),
                "request_id": str(request_id),
                "tenant_id": str(tenant_id),
                "resource_type": resource_type,
                "resource_id": str(resource_id),
                "deleted_at": deleted_at,
                "deleted_by": str(executed_by),
                "data_hash": data_hash,
                "proof_hash": proof_hash,
                "created_at": deleted_at,
            },
        )

        # 更新删除请求状态
        query = text(
            """
            UPDATE deletion_requests
            SET status = 'completed',
                executed_by = :executed_by,
                executed_at = :executed_at
            WHERE id = :request_id
        """
        )

        self.db.execute(
            query,
            {
                "request_id": str(request_id),
                "executed_by": str(executed_by),
                "executed_at": deleted_at,
            },
        )

        self.db.commit()

        logger.info(
            "deletion executed and proof generated: request_id=%s, proof_id=%s",
            request_id,
            proof_id,
        )

        return DeletionProof(
            proof_id=proof_id,
            request_id=request_id,
            tenant_id=tenant_id,
            resource_type=resource_type,
            resource_id=resource_id,
            deleted_at=deleted_at,
            deleted_by=executed_by,
            data_hash=data_hash,
            proof_hash=proof_hash,
        )

    def _get_resource_snapshot(self, resource_type: str, resource_id: UUID) -> dict[str, Any] | None:
        """获取资源数据快照。"""
        if resource_type == "document":
            query = text("SELECT * FROM documents WHERE id = :id")
        elif resource_type == "user":
            query = text("SELECT * FROM users WHERE id = :id")
        elif resource_type == "conversation":
            query = text("SELECT * FROM conversations WHERE id = :id")
        else:
            logger.error("unsupported resource type: %s", resource_type)
            return None

        result = self.db.execute(query, {"id": str(resource_id)})
        row = result.fetchone()

        if not row:
            return None

        return dict(row._mapping)

    def _calculate_hash(self, data: dict[str, Any]) -> str:
        """计算数据哈希。"""
        import json

        # 排序键以确保一致性
        sorted_data = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(sorted_data.encode()).hexdigest()

    def _delete_resource(self, resource_type: str, resource_id: UUID, tenant_id: UUID) -> bool:
        """删除资源及其关联数据。"""
        try:
            if resource_type == "document":
                # 删除文档及其所有关联数据
                self.db.execute(
                    text("DELETE FROM document_chunks WHERE document_version_id IN (SELECT id FROM document_versions WHERE document_id = :id)"),
                    {"id": str(resource_id)},
                )
                self.db.execute(
                    text("DELETE FROM document_versions WHERE document_id = :id"),
                    {"id": str(resource_id)},
                )
                self.db.execute(
                    text("DELETE FROM documents WHERE id = :id AND tenant_id = :tenant_id"),
                    {"id": str(resource_id), "tenant_id": str(tenant_id)},
                )
            elif resource_type == "user":
                # 删除用户数据（保留审计日志）
                self.db.execute(
                    text("DELETE FROM tenant_memberships WHERE user_id = :id"),
                    {"id": str(resource_id)},
                )
                self.db.execute(
                    text("DELETE FROM kb_memberships WHERE user_id = :id"),
                    {"id": str(resource_id)},
                )
                self.db.execute(
                    text("DELETE FROM users WHERE id = :id"),
                    {"id": str(resource_id)},
                )
            elif resource_type == "conversation":
                # 删除对话及消息
                self.db.execute(
                    text("DELETE FROM messages WHERE conversation_id = :id"),
                    {"id": str(resource_id)},
                )
                self.db.execute(
                    text("DELETE FROM conversations WHERE id = :id AND tenant_id = :tenant_id"),
                    {"id": str(resource_id), "tenant_id": str(tenant_id)},
                )
            else:
                return False

            return True
        except Exception as exc:
            logger.exception("failed to delete resource: %s", exc)
            self.db.rollback()
            return False

    def verify_deletion_proof(self, proof_id: UUID) -> bool:
        """验证删除证明的完整性。

        Args:
            proof_id: 证明 ID

        Returns:
            证明是否有效
        """
        query = text(
            """
            SELECT id, request_id, resource_type, resource_id,
                   deleted_at, data_hash, proof_hash
            FROM deletion_proofs
            WHERE id = :proof_id
        """
        )

        result = self.db.execute(query, {"proof_id": str(proof_id)})
        row = result.fetchone()

        if not row:
            return False

        # 重新计算证明哈希
        proof_data = f"{row.id}{row.request_id}{row.resource_type}{row.resource_id}{row.deleted_at.isoformat()}{row.data_hash}"
        calculated_hash = hashlib.sha256(proof_data.encode()).hexdigest()

        # 验证哈希是否匹配
        return calculated_hash == row.proof_hash
