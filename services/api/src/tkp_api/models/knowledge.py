"""知识域模型。

包含知识库、文档、版本、切片、向量、入库任务与检索日志。
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from tkp_api.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from tkp_api.models.enums import (
    DocumentStatus,
    IngestionJobStatus,
    KBRole,
    KBStatus,
    MembershipStatus,
    ParseStatus,
    SourceType,
)


class KnowledgeBase(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """知识库实体，归属租户与工作空间。"""

    __tablename__ = "knowledge_bases"
    __table_args__ = (UniqueConstraint("tenant_id", "workspace_id", "name", name="uk_kb_name"),)

    # 冗余租户 ID，用于多租户隔离过滤。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 所属工作空间 ID。
    workspace_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 知识库名称（工作空间内可读）。
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    # 知识库描述。
    description: Mapped[str | None] = mapped_column(Text)
    # 默认向量模型标识。
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    # 检索策略配置，如 top_k、重排开关等。
    retrieval_strategy: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # 知识库状态（active/archived）。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=KBStatus.ACTIVE)
    # 创建人用户 ID。
    created_by: Mapped[UUID | None] = mapped_column()


class KBMembership(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """知识库成员关系。"""

    __tablename__ = "kb_memberships"
    __table_args__ = (UniqueConstraint("kb_id", "user_id", name="uk_kb_membership"),)

    # 冗余租户 ID，用于快速过滤。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 目标知识库 ID。
    kb_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 目标用户 ID。
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 知识库角色（kb_owner/kb_editor/kb_viewer）。
    role: Mapped[str] = mapped_column(String(32), nullable=False, default=KBRole.VIEWER)
    # 成员关系状态（active/invited/disabled）。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=MembershipStatus.ACTIVE)

class Document(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """文档主记录。"""

    __tablename__ = "documents"

    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 所属工作空间 ID。
    workspace_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 所属知识库 ID。
    kb_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 文档标题，通常取文件名或来源标题。
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    # 文档来源类型（upload/url/notion/git）。
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default=SourceType.UPLOAD)
    # 来源地址或对象名。
    source_uri: Mapped[str | None] = mapped_column(Text)
    # 当前生效版本号，随上传/重建推进。
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 文档状态（pending/processing/ready/failed）。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=DocumentStatus.PENDING)
    # 文档扩展元数据（关键词、来源语言等）。
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    # 创建人用户 ID。
    created_by: Mapped[UUID | None] = mapped_column()


class DocumentVersion(Base, UUIDPrimaryKeyMixin):
    """文档版本记录，用于可回溯入库。"""

    __tablename__ = "document_versions"
    __table_args__ = (UniqueConstraint("document_id", "version", name="uk_document_version"),)

    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 所属文档 ID。
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 文档版本号（同一文档内递增）。
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    # 对象存储中的物理对象键。
    object_key: Mapped[str | None] = mapped_column(Text)
    # 解析器类型（markdown/pdf/image/generic）。
    parser_type: Mapped[str | None] = mapped_column(String(64))
    # 解析状态（pending/success/failed）。
    parse_status: Mapped[str] = mapped_column(String(32), nullable=False, default=ParseStatus.PENDING)
    # 上传内容校验和，用于排错与去重参考。
    checksum: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

class DocumentChunk(Base, UUIDPrimaryKeyMixin):
    """切片记录，检索最小粒度。"""

    __tablename__ = "document_chunks"
    __table_args__ = (UniqueConstraint("document_version_id", "chunk_no", name="uk_chunk_no"),)

    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 所属工作空间 ID。
    workspace_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 所属知识库 ID。
    kb_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 所属文档 ID。
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 所属文档版本 ID。
    document_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 切片序号（同一版本内唯一）。
    chunk_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # 父切片 ID，用于层次化切分场景。
    parent_chunk_id: Mapped[UUID | None] = mapped_column()
    # 标题层级路径（如章节路径），可选。
    title_path: Mapped[str | None] = mapped_column(Text)
    # 切片正文内容。
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # 粗略 token 数，用于后续召回与费用估算。
    token_count: Mapped[int] = mapped_column(Integer, nullable=False)
    # 切片元数据。
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

class ChunkEmbedding(Base):
    """切片向量记录。"""

    __tablename__ = "chunk_embeddings"

    # 切片主键作为向量表主键，保持一对一关系。
    chunk_id: Mapped[UUID] = mapped_column(primary_key=True, nullable=False)
    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 所属知识库 ID。
    kb_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 生成该向量时使用的模型标识。
    embedding_model: Mapped[str] = mapped_column(String(128), nullable=False)
    # 向量字段，当前维度 1536。
    vector: Mapped[list[float]] = mapped_column(Vector(1536), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

class IngestionJob(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """异步入库任务。"""

    __tablename__ = "ingestion_jobs"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key", name="uk_ingestion_job_idempotency"),)

    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 所属工作空间 ID。
    workspace_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 所属知识库 ID。
    kb_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 关联文档 ID。
    document_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 关联文档版本 ID。
    document_version_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 幂等键，用于避免重复创建任务。
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # 任务状态（queued/processing/retrying/completed/dead_letter）。
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=IngestionJobStatus.QUEUED)
    # 任务阶段（loading/chunking/completed/failed）。
    stage: Mapped[str] = mapped_column(String(64), nullable=False, default="queued")
    # 任务进度（0-100）。
    progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 已尝试次数。
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # 最大尝试次数。
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    # 下次允许执行时间（用于重试退避）。
    next_run_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # 锁定时间，配合 locked_by 实现任务占有。
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 持锁工作进程标识。
    locked_by: Mapped[str | None] = mapped_column(String(128))
    # 最近心跳时间，用于判断是否超时失联。
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 任务开始时间。
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 任务完成时间（成功或死信）。
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # 错误详情摘要。
    error: Mapped[str | None] = mapped_column(Text)

class RetrievalLog(Base, UUIDPrimaryKeyMixin):
    """检索日志。"""

    __tablename__ = "retrieval_logs"

    # 所属租户 ID。
    tenant_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 查询发起用户 ID。
    user_id: Mapped[UUID] = mapped_column(nullable=False, index=True)
    # 原始查询文本。
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    # 实际执行检索的知识库 ID 列表。
    kb_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    # 请求 top_k 参数。
    top_k: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    # 过滤条件 JSON。
    filter_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    # 命中结果快照，便于回放与审计。
    result_chunks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    # 检索耗时毫秒数。
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
