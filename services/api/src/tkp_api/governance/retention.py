"""数据保留策略模块。

管理不同类型数据的保留期限和自动清理。
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger("tkp_api.governance.retention")


class RetentionPolicy:
    """数据保留策略。"""

    def __init__(
        self,
        *,
        resource_type: str,
        retention_days: int,
        auto_delete: bool = False,
        archive_before_delete: bool = True,
    ):
        """初始化保留策略。

        Args:
            resource_type: 资源类型
            retention_days: 保留天数（-1 表示永久保留）
            auto_delete: 是否自动删除过期数据
            archive_before_delete: 删除前是否归档
        """
        self.resource_type = resource_type
        self.retention_days = retention_days
        self.auto_delete = auto_delete
        self.archive_before_delete = archive_before_delete


# 默认保留策略
DEFAULT_RETENTION_POLICIES = {
    "audit_logs": RetentionPolicy(
        resource_type="audit_logs",
        retention_days=365,  # 审计日志保留1年
        auto_delete=False,
        archive_before_delete=True,
    ),
    "retrieval_logs": RetentionPolicy(
        resource_type="retrieval_logs",
        retention_days=90,  # 检索日志保留90天
        auto_delete=True,
        archive_before_delete=False,
    ),
    "conversations": RetentionPolicy(
        resource_type="conversations",
        retention_days=180,  # 对话保留180天
        auto_delete=False,
        archive_before_delete=True,
    ),
    "agent_runs": RetentionPolicy(
        resource_type="agent_runs",
        retention_days=90,  # Agent 运行记录保留90天
        auto_delete=True,
        archive_before_delete=False,
    ),
    "ingestion_jobs": RetentionPolicy(
        resource_type="ingestion_jobs",
        retention_days=30,  # 接入任务保留30天
        auto_delete=True,
        archive_before_delete=False,
    ),
    "deletion_requests": RetentionPolicy(
        resource_type="deletion_requests",
        retention_days=730,  # 删除请求保留2年（合规要求）
        auto_delete=False,
        archive_before_delete=True,
    ),
    "deletion_proofs": RetentionPolicy(
        resource_type="deletion_proofs",
        retention_days=-1,  # 删除证明永久保留
        auto_delete=False,
        archive_before_delete=False,
    ),
}

_RESOURCE_TABLES = {
    "audit_logs": "audit_logs",
    "retrieval_logs": "retrieval_logs",
    "conversations": "conversations",
    "agent_runs": "agent_runs",
    "ingestion_jobs": "ingestion_jobs",
    "deletion_requests": "deletion_requests",
    "deletion_proofs": "deletion_proofs",
}


class RetentionService:
    """数据保留服务。"""

    def __init__(self, db: Session):
        """初始化保留服务。"""
        self.db = db
        self.policies = DEFAULT_RETENTION_POLICIES.copy()

    def set_policy(self, policy: RetentionPolicy):
        """设置保留策略。"""
        self.policies[policy.resource_type] = policy
        logger.info(
            "retention policy set: resource_type=%s, retention_days=%d",
            policy.resource_type,
            policy.retention_days,
        )

    def get_policy(self, resource_type: str) -> RetentionPolicy | None:
        """获取保留策略。"""
        return self.policies.get(resource_type)

    def _resolve_table_name(self, resource_type: str) -> str | None:
        """将资源类型映射为受控表名，避免 SQL 注入。"""
        if resource_type not in _RESOURCE_TABLES:
            return None
        return _RESOURCE_TABLES[resource_type]

    def find_expired_records(
        self,
        resource_type: str,
        tenant_id: UUID | None = None,
    ) -> list[dict[str, Any]]:
        """查找过期记录。

        Args:
            resource_type: 资源类型
            tenant_id: 租户 ID（可选）

        Returns:
            过期记录列表
        """
        policy = self.get_policy(resource_type)
        if not policy or policy.retention_days < 0:
            return []

        cutoff_date = datetime.now(timezone.utc) - timedelta(days=policy.retention_days)

        table_name = self._resolve_table_name(resource_type)
        if table_name is None:
            logger.error("invalid retention resource_type: %s", resource_type)
            return []

        # 构建查询
        query_str = f"""
            SELECT id, tenant_id, created_at
            FROM {table_name}
            WHERE created_at < :cutoff_date
        """

        params: dict[str, Any] = {"cutoff_date": cutoff_date}

        if tenant_id:
            query_str += " AND tenant_id = :tenant_id"
            params["tenant_id"] = str(tenant_id)

        query_str += " ORDER BY created_at LIMIT 1000"

        try:
            result = self.db.execute(text(query_str), params)
            records = []
            for row in result:
                records.append(
                    {
                        "id": row.id,
                        "tenant_id": row.tenant_id,
                        "created_at": row.created_at,
                    }
                )

            logger.info(
                "found %d expired records: resource_type=%s, cutoff_date=%s",
                len(records),
                resource_type,
                cutoff_date,
            )
            return records
        except Exception as exc:
            logger.exception("failed to find expired records: %s", exc)
            return []

    def archive_records(
        self,
        resource_type: str,
        record_ids: list[UUID],
    ) -> bool:
        """归档记录。

        Args:
            resource_type: 资源类型
            record_ids: 记录 ID 列表

        Returns:
            是否归档成功
        """
        if not record_ids:
            return True

        table_name = self._resolve_table_name(resource_type)
        if table_name is None:
            logger.error("invalid retention resource_type: %s", resource_type)
            return False

        # 创建归档表（如果不存在）
        archive_table = f"{table_name}_archive"

        try:
            # 复制数据到归档表
            query = text(
                f"""
                INSERT INTO {archive_table}
                SELECT *, CURRENT_TIMESTAMP as archived_at
                FROM {table_name}
                WHERE id = ANY(:record_ids)
            """
            )

            self.db.execute(query, {"record_ids": [str(rid) for rid in record_ids]})
            self.db.commit()

            logger.info(
                "archived %d records: resource_type=%s",
                len(record_ids),
                resource_type,
            )
            return True
        except Exception as exc:
            logger.exception("failed to archive records: %s", exc)
            self.db.rollback()
            return False

    def delete_expired_records(
        self,
        resource_type: str,
        tenant_id: UUID | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """删除过期记录。

        Args:
            resource_type: 资源类型
            tenant_id: 租户 ID（可选）
            dry_run: 是否仅模拟运行

        Returns:
            包含 deleted_count、archived_count 的字典
        """
        policy = self.get_policy(resource_type)
        if not policy:
            return {"error": f"no policy found for {resource_type}"}

        table_name = self._resolve_table_name(resource_type)
        if table_name is None:
            return {"error": f"invalid resource_type: {resource_type}"}

        if not policy.auto_delete:
            return {"error": f"auto_delete not enabled for {resource_type}"}

        # 查找过期记录
        expired_records = self.find_expired_records(resource_type, tenant_id)

        if not expired_records:
            return {"deleted_count": 0, "archived_count": 0}

        record_ids = [UUID(str(r["id"])) for r in expired_records]

        if dry_run:
            return {
                "dry_run": True,
                "would_delete": len(record_ids),
                "would_archive": len(record_ids) if policy.archive_before_delete else 0,
            }

        # 归档（如果需要）
        archived_count = 0
        if policy.archive_before_delete:
            if not self.archive_records(resource_type, record_ids):
                return {"error": f"archive failed for {resource_type}"}
            archived_count = len(record_ids)

        # 删除记录
        try:
            query = text(
                f"""
                DELETE FROM {table_name}
                WHERE id = ANY(:record_ids)
            """
            )

            result = self.db.execute(query, {"record_ids": [str(rid) for rid in record_ids]})
            self.db.commit()

            deleted_count = int(getattr(result, "rowcount", 0) or 0)
            logger.info(
                "deleted %d expired records: resource_type=%s",
                deleted_count,
                resource_type,
            )

            return {
                "deleted_count": deleted_count,
                "archived_count": archived_count,
            }
        except Exception as exc:
            logger.exception("failed to delete expired records: %s", exc)
            self.db.rollback()
            return {"error": str(exc)}

    def cleanup_all_expired(self, tenant_id: UUID | None = None, dry_run: bool = False) -> dict[str, Any]:
        """清理所有过期数据。

        Args:
            tenant_id: 租户 ID（可选）
            dry_run: 是否仅模拟运行

        Returns:
            各资源类型的清理结果
        """
        results = {}

        for resource_type, policy in self.policies.items():
            if policy.auto_delete:
                result = self.delete_expired_records(resource_type, tenant_id, dry_run)
                results[resource_type] = result

        return results
