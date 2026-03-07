"""数据删除证明流程（GDPR 合规）。"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import Session

logger = logging.getLogger("tkp_api.governance.deletion")

_SUPPORTED_RESOURCE_TYPES = {"document", "user", "conversation"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_missing_table_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return "no such table" in message or ("does not exist" in message and ("deletion_" in message))


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
        """创建删除请求。"""
        if resource_type not in _SUPPORTED_RESOURCE_TYPES:
            raise ValueError(f"unsupported resource type: {resource_type}")

        if not self._resource_exists_in_tenant(resource_type, resource_id, tenant_id):
            raise ValueError(f"resource not found in tenant: {resource_type}/{resource_id}")

        request_id = uuid4()
        requested_at = _utcnow()

        self.db.execute(
            text(
                """
                INSERT INTO deletion_requests (
                    id, tenant_id, user_id, resource_type, resource_id,
                    reason, status, requested_at, created_at, updated_at
                ) VALUES (
                    :id, :tenant_id, :user_id, :resource_type, :resource_id,
                    :reason, :status, :requested_at, :created_at, :updated_at
                )
            """
            ),
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
                "updated_at": requested_at,
            },
        )
        self.db.commit()

        logger.info("deletion request created: request_id=%s, resource=%s/%s", request_id, resource_type, resource_id)
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

    def approve_deletion_request(self, *, request_id: UUID, tenant_id: UUID, approved_by: UUID) -> bool:
        """批准删除请求。"""
        try:
            now = _utcnow()
            result = self.db.execute(
                text(
                    """
                    UPDATE deletion_requests
                    SET status = 'approved',
                        approved_by = :approved_by,
                        approved_at = :approved_at,
                        updated_at = :updated_at
                    WHERE id = :request_id
                      AND tenant_id = :tenant_id
                      AND status = 'pending'
                """
                ),
                {
                    "request_id": str(request_id),
                    "tenant_id": str(tenant_id),
                    "approved_by": str(approved_by),
                    "approved_at": now,
                    "updated_at": now,
                },
            )
        except (OperationalError, ProgrammingError) as exc:
            if _is_missing_table_error(exc):
                self.db.rollback()
                logger.warning("skip approve deletion request because governance tables are not initialized: %s", exc)
                return False
            raise
        self.db.commit()
        success = result.rowcount > 0
        if success:
            logger.info("deletion request approved: request_id=%s tenant_id=%s", request_id, tenant_id)
        return success

    def reject_deletion_request(
        self,
        *,
        request_id: UUID,
        tenant_id: UUID,
        rejected_by: UUID,
        reject_reason: str,
    ) -> bool:
        """拒绝删除请求。"""
        try:
            now = _utcnow()
            result = self.db.execute(
                text(
                    """
                    UPDATE deletion_requests
                    SET status = 'rejected',
                        rejected_by = :rejected_by,
                        rejected_at = :rejected_at,
                        reject_reason = :reject_reason,
                        updated_at = :updated_at
                    WHERE id = :request_id
                      AND tenant_id = :tenant_id
                      AND status = 'pending'
                """
                ),
                {
                    "request_id": str(request_id),
                    "tenant_id": str(tenant_id),
                    "rejected_by": str(rejected_by),
                    "rejected_at": now,
                    "reject_reason": reject_reason,
                    "updated_at": now,
                },
            )
        except (OperationalError, ProgrammingError) as exc:
            if _is_missing_table_error(exc):
                self.db.rollback()
                logger.warning("skip reject deletion request because governance tables are not initialized: %s", exc)
                return False
            raise
        self.db.commit()
        success = result.rowcount > 0
        if success:
            logger.info("deletion request rejected: request_id=%s tenant_id=%s", request_id, tenant_id)
        return success

    def execute_deletion(self, *, request_id: UUID, tenant_id: UUID, executed_by: UUID) -> DeletionProof | None:
        """执行删除并生成证明。"""
        try:
            row = self.db.execute(
                text(
                    """
                    SELECT id, tenant_id, resource_type, resource_id
                    FROM deletion_requests
                    WHERE id = :request_id
                      AND tenant_id = :tenant_id
                      AND status = 'approved'
                """
                ),
                {"request_id": str(request_id), "tenant_id": str(tenant_id)},
            ).fetchone()
        except (OperationalError, ProgrammingError) as exc:
            if _is_missing_table_error(exc):
                self.db.rollback()
                logger.warning("skip execute deletion because governance tables are not initialized: %s", exc)
                return None
            raise
        if not row:
            logger.warning("deletion request not found/approved: request_id=%s tenant_id=%s", request_id, tenant_id)
            return None

        resource_type = row.resource_type
        resource_id = UUID(str(row.resource_id))
        data_snapshot = self._get_resource_snapshot(resource_type=resource_type, resource_id=resource_id, tenant_id=tenant_id)
        if not data_snapshot:
            logger.error("resource not found in tenant: %s/%s tenant=%s", resource_type, resource_id, tenant_id)
            return None

        data_hash = self._calculate_hash(data_snapshot)
        if not self._delete_resource(resource_type=resource_type, resource_id=resource_id, tenant_id=tenant_id):
            logger.error("failed to delete resource: %s/%s tenant=%s", resource_type, resource_id, tenant_id)
            return None

        proof_id = uuid4()
        deleted_at = _utcnow()
        proof_data = f"{proof_id}{request_id}{resource_type}{resource_id}{deleted_at.isoformat()}{data_hash}"
        proof_hash = hashlib.sha256(proof_data.encode()).hexdigest()

        try:
            self.db.execute(
                text(
                    """
                    INSERT INTO deletion_proofs (
                        id, request_id, tenant_id, resource_type, resource_id,
                        deleted_at, deleted_by, data_hash, proof_hash, created_at
                    ) VALUES (
                        :id, :request_id, :tenant_id, :resource_type, :resource_id,
                        :deleted_at, :deleted_by, :data_hash, :proof_hash, :created_at
                    )
                """
                ),
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

            self.db.execute(
                text(
                    """
                    UPDATE deletion_requests
                    SET status = 'completed',
                        executed_by = :executed_by,
                        executed_at = :executed_at,
                        updated_at = :updated_at
                    WHERE id = :request_id
                      AND tenant_id = :tenant_id
                      AND status = 'approved'
                """
                ),
                {
                    "request_id": str(request_id),
                    "tenant_id": str(tenant_id),
                    "executed_by": str(executed_by),
                    "executed_at": deleted_at,
                    "updated_at": deleted_at,
                },
            )
        except (OperationalError, ProgrammingError) as exc:
            if _is_missing_table_error(exc):
                self.db.rollback()
                logger.warning("skip save deletion proof because governance tables are not initialized: %s", exc)
                return None
            raise

        self.db.commit()
        logger.info("deletion executed and proof generated: request_id=%s, proof_id=%s", request_id, proof_id)
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

    def get_deletion_proof(self, *, proof_id: UUID, tenant_id: UUID | None = None) -> DeletionProof | None:
        """读取删除证明。"""
        try:
            if tenant_id is None:
                row = self.db.execute(
                    text(
                        """
                        SELECT id, request_id, tenant_id, resource_type, resource_id,
                               deleted_at, deleted_by, data_hash, proof_hash
                        FROM deletion_proofs
                        WHERE id = :proof_id
                    """
                    ),
                    {"proof_id": str(proof_id)},
                ).fetchone()
            else:
                row = self.db.execute(
                    text(
                        """
                        SELECT id, request_id, tenant_id, resource_type, resource_id,
                               deleted_at, deleted_by, data_hash, proof_hash
                        FROM deletion_proofs
                        WHERE id = :proof_id
                          AND tenant_id = :tenant_id
                    """
                    ),
                    {"proof_id": str(proof_id), "tenant_id": str(tenant_id)},
                ).fetchone()
        except (OperationalError, ProgrammingError) as exc:
            if _is_missing_table_error(exc):
                self.db.rollback()
                logger.warning("skip get deletion proof because governance tables are not initialized: %s", exc)
                return None
            raise

        if not row:
            return None

        return DeletionProof(
            proof_id=UUID(str(row.id)),
            request_id=UUID(str(row.request_id)),
            tenant_id=UUID(str(row.tenant_id)),
            resource_type=row.resource_type,
            resource_id=UUID(str(row.resource_id)),
            deleted_at=row.deleted_at,
            deleted_by=UUID(str(row.deleted_by)),
            data_hash=row.data_hash,
            proof_hash=row.proof_hash,
        )

    def _resource_exists_in_tenant(self, resource_type: str, resource_id: UUID, tenant_id: UUID) -> bool:
        if resource_type == "document":
            row = self.db.execute(
                text("SELECT 1 FROM documents WHERE id = :id AND tenant_id = :tenant_id"),
                {"id": str(resource_id), "tenant_id": str(tenant_id)},
            ).fetchone()
            return row is not None
        if resource_type == "conversation":
            row = self.db.execute(
                text("SELECT 1 FROM conversations WHERE id = :id AND tenant_id = :tenant_id"),
                {"id": str(resource_id), "tenant_id": str(tenant_id)},
            ).fetchone()
            return row is not None
        if resource_type == "user":
            row = self.db.execute(
                text("SELECT 1 FROM tenant_memberships WHERE user_id = :id AND tenant_id = :tenant_id"),
                {"id": str(resource_id), "tenant_id": str(tenant_id)},
            ).fetchone()
            return row is not None
        return False

    def _get_resource_snapshot(self, *, resource_type: str, resource_id: UUID, tenant_id: UUID) -> dict[str, Any] | None:
        """获取资源数据快照。"""
        if resource_type == "document":
            row = self.db.execute(
                text("SELECT * FROM documents WHERE id = :id AND tenant_id = :tenant_id"),
                {"id": str(resource_id), "tenant_id": str(tenant_id)},
            ).fetchone()
        elif resource_type == "user":
            row = self.db.execute(
                text(
                    """
                    SELECT u.id, u.email, u.display_name, u.status, :tenant_id::uuid AS tenant_id
                    FROM users u
                    WHERE u.id = :id
                      AND EXISTS (
                        SELECT 1
                        FROM tenant_memberships tm
                        WHERE tm.user_id = u.id AND tm.tenant_id = :tenant_id
                      )
                """
                ),
                {"id": str(resource_id), "tenant_id": str(tenant_id)},
            ).fetchone()
        elif resource_type == "conversation":
            row = self.db.execute(
                text("SELECT * FROM conversations WHERE id = :id AND tenant_id = :tenant_id"),
                {"id": str(resource_id), "tenant_id": str(tenant_id)},
            ).fetchone()
        else:
            return None

        if not row:
            return None
        return dict(row._mapping)

    def _calculate_hash(self, data: dict[str, Any]) -> str:
        """计算数据哈希。"""
        sorted_data = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(sorted_data.encode()).hexdigest()

    def _delete_resource(self, *, resource_type: str, resource_id: UUID, tenant_id: UUID) -> bool:
        """删除资源及其关联数据。"""
        try:
            rid = str(resource_id)
            tid = str(tenant_id)

            if resource_type == "document":
                self.db.execute(
                    text(
                        """
                        DELETE FROM chunk_embeddings
                        WHERE chunk_id IN (
                            SELECT id
                            FROM document_chunks
                            WHERE document_version_id IN (
                                SELECT id
                                FROM document_versions
                                WHERE document_id = :id
                            )
                        )
                    """
                    ),
                    {"id": rid},
                )
                self.db.execute(
                    text(
                        """
                        DELETE FROM document_chunks
                        WHERE document_version_id IN (
                            SELECT id
                            FROM document_versions
                            WHERE document_id = :id
                        )
                    """
                    ),
                    {"id": rid},
                )
                self.db.execute(text("DELETE FROM document_versions WHERE document_id = :id"), {"id": rid})
                self.db.execute(text("DELETE FROM ingestion_jobs WHERE tenant_id = :tenant_id AND document_id = :id"), {"tenant_id": tid, "id": rid})
                self.db.execute(text("DELETE FROM documents WHERE id = :id AND tenant_id = :tenant_id"), {"id": rid, "tenant_id": tid})
                return True

            if resource_type == "conversation":
                self.db.execute(
                    text(
                        """
                        DELETE FROM feedback_replays
                        WHERE feedback_id IN (
                            SELECT id
                            FROM user_feedbacks
                            WHERE tenant_id = :tenant_id
                              AND conversation_id = :id
                        )
                    """
                    ),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text("DELETE FROM user_feedbacks WHERE tenant_id = :tenant_id AND conversation_id = :id"),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text(
                        """
                        DELETE FROM agent_recoveries
                        WHERE tenant_id = :tenant_id
                          AND agent_run_id IN (
                            SELECT id FROM agent_runs WHERE tenant_id = :tenant_id AND conversation_id = :id
                          )
                    """
                    ),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text(
                        """
                        DELETE FROM agent_checkpoints
                        WHERE tenant_id = :tenant_id
                          AND agent_run_id IN (
                            SELECT id FROM agent_runs WHERE tenant_id = :tenant_id AND conversation_id = :id
                          )
                    """
                    ),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text("DELETE FROM agent_runs WHERE tenant_id = :tenant_id AND conversation_id = :id"),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text("DELETE FROM messages WHERE tenant_id = :tenant_id AND conversation_id = :id"),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text("DELETE FROM conversations WHERE id = :id AND tenant_id = :tenant_id"),
                    {"id": rid, "tenant_id": tid},
                )
                return True

            if resource_type == "user":
                self.db.execute(
                    text(
                        """
                        DELETE FROM feedback_replays
                        WHERE feedback_id IN (
                            SELECT id
                            FROM user_feedbacks
                            WHERE tenant_id = :tenant_id
                              AND user_id = :id
                        )
                    """
                    ),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text("DELETE FROM user_feedbacks WHERE tenant_id = :tenant_id AND user_id = :id"),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text("DELETE FROM retrieval_logs WHERE tenant_id = :tenant_id AND user_id = :id"),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text(
                        """
                        DELETE FROM agent_recoveries
                        WHERE tenant_id = :tenant_id
                          AND agent_run_id IN (
                            SELECT id FROM agent_runs WHERE tenant_id = :tenant_id AND user_id = :id
                          )
                    """
                    ),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text(
                        """
                        DELETE FROM agent_checkpoints
                        WHERE tenant_id = :tenant_id
                          AND agent_run_id IN (
                            SELECT id FROM agent_runs WHERE tenant_id = :tenant_id AND user_id = :id
                          )
                    """
                    ),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text("DELETE FROM agent_runs WHERE tenant_id = :tenant_id AND user_id = :id"),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text(
                        """
                        DELETE FROM messages
                        WHERE tenant_id = :tenant_id
                          AND conversation_id IN (
                            SELECT id
                            FROM conversations
                            WHERE tenant_id = :tenant_id
                              AND user_id = :id
                          )
                    """
                    ),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text("DELETE FROM conversations WHERE tenant_id = :tenant_id AND user_id = :id"),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text("DELETE FROM workspace_memberships WHERE tenant_id = :tenant_id AND user_id = :id"),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text("DELETE FROM kb_memberships WHERE tenant_id = :tenant_id AND user_id = :id"),
                    {"tenant_id": tid, "id": rid},
                )
                self.db.execute(
                    text("DELETE FROM tenant_memberships WHERE tenant_id = :tenant_id AND user_id = :id"),
                    {"tenant_id": tid, "id": rid},
                )

                remaining = self.db.execute(
                    text("SELECT COUNT(*) FROM tenant_memberships WHERE user_id = :id"),
                    {"id": rid},
                ).scalar_one()
                if int(remaining or 0) == 0:
                    self.db.execute(text("DELETE FROM workspace_memberships WHERE user_id = :id"), {"id": rid})
                    self.db.execute(text("DELETE FROM kb_memberships WHERE user_id = :id"), {"id": rid})
                    self.db.execute(text("DELETE FROM tenant_memberships WHERE user_id = :id"), {"id": rid})
                    self.db.execute(text("DELETE FROM user_credentials WHERE user_id = :id"), {"id": rid})
                    self.db.execute(text("DELETE FROM users WHERE id = :id"), {"id": rid})
                return True

            return False
        except Exception as exc:
            logger.exception("failed to delete resource: %s", exc)
            self.db.rollback()
            return False

    def verify_deletion_proof(self, proof_id: UUID) -> bool:
        """验证删除证明完整性。"""
        try:
            row = self.db.execute(
                text(
                    """
                    SELECT id, request_id, resource_type, resource_id, deleted_at, data_hash, proof_hash
                    FROM deletion_proofs
                    WHERE id = :proof_id
                """
                ),
                {"proof_id": str(proof_id)},
            ).fetchone()
        except (OperationalError, ProgrammingError) as exc:
            if _is_missing_table_error(exc):
                self.db.rollback()
                logger.warning("skip verify deletion proof because governance tables are not initialized: %s", exc)
                return False
            raise
        if not row:
            return False

        proof_data = f"{row.id}{row.request_id}{row.resource_type}{row.resource_id}{row.deleted_at.isoformat()}{row.data_hash}"
        calculated_hash = hashlib.sha256(proof_data.encode()).hexdigest()
        return calculated_hash == row.proof_hash
