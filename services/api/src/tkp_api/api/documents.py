"""文档接入与入库任务接口。"""

import hashlib
import json
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Path, Query, Request, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from tkp_api.core.exceptions import DocumentValidationException
from tkp_api.db.session import get_db
from tkp_api.dependencies import get_request_context
from tkp_api.models.enums import DocumentStatus, IngestionJobStatus, ParseStatus, SourceType
from tkp_api.models.knowledge import ChunkEmbedding, Document, DocumentChunk, DocumentVersion, IngestionJob
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.document import DocumentUpdateRequest, IngestionJobDeadLetterRequest
from tkp_api.schemas.responses import (
    DocumentChunkPageData,
    DocumentData,
    DocumentVersionData,
    DocumentUploadData,
    IngestionJobData,
    ReindexData,
)
from tkp_api.services import (
    PermissionAction,
    audit_log,
    enqueue_ingestion_job,
    ensure_document_read_access,
    ensure_kb_read_access,
    ensure_kb_write_access,
    infer_parser_type,
    persist_upload,
    require_tenant_action,
)
from tkp_api.services.quota import QuotaMetric, enforce_quota
from tkp_api.utils.response import success

router = APIRouter(tags=["documents"])

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def validate_upload_file(file: UploadFile, content: bytes) -> None:
    """基础上传校验，防止空文件与超大文件直接入库。"""
    filename = (file.filename or "").strip()
    if not filename:
        raise DocumentValidationException("文件名不能为空", details={"field": "filename"})
    if not content:
        raise DocumentValidationException("文件内容不能为空", details={"field": "content"})
    if len(content) > _MAX_UPLOAD_BYTES:
        raise DocumentValidationException(
            f"文件大小超过限制（最大 {_MAX_UPLOAD_BYTES // 1024 // 1024} MB）",
            details={"field": "content", "size": len(content), "max_size": _MAX_UPLOAD_BYTES},
        )


@router.post(
    "/knowledge-bases/{kb_id}/documents",
    summary="上传文档",
    description="向知识库上传文件，创建或升级文档版本，并异步入队入库任务。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[DocumentUploadData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def upload_document(
    request: Request,
    kb_id: UUID = Path(..., description="目标知识库 ID。"),
    file: UploadFile = File(..., description="待上传文档文件。"),
    metadata: str | None = Form(default=None, description="可选 JSON 字符串元数据。"),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="可选幂等键，用于重复请求去重。",
    ),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """上传文档并创建异步入库任务。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_WRITE,
    )
    # 入口先校验写权限，确保只有有权限的用户可以触发入库。
    kb, _, _ = ensure_kb_write_access(
        db,
        tenant_id=ctx.tenant_id,
        kb_id=kb_id,
        user_id=ctx.user_id,
    )
    enforce_quota(
        db,
        tenant_id=ctx.tenant_id,
        metric_code=QuotaMetric.DOCUMENT_UPLOADS.value,
        projected_increment=1,
        workspace_id=kb.workspace_id,
        actor_user_id=ctx.user_id,
    )

    # 解析可选元数据 JSON，失败时返回 422，避免脏数据入库。
    metadata_dict = {}
    if metadata:
        try:
            metadata_dict = json.loads(metadata)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="invalid metadata") from exc

    # 上传文件内容一次性读入，后续用于校验和计算与落盘。
    content = await file.read()

    # 验证文件安全性
    validate_upload_file(file, content)

    checksum = hashlib.sha256(content).hexdigest()
    source_uri = file.filename or "upload.bin"

    try:
        # 以 tenant + workspace + kb + source_uri 识别同源文档，实现"同文件升级版本"语义。
        document = (
            db.execute(
                select(Document)
                .where(Document.tenant_id == ctx.tenant_id)
                .where(Document.workspace_id == kb.workspace_id)
                .where(Document.kb_id == kb_id)
                .where(Document.source_type == SourceType.UPLOAD)
                .where(Document.source_uri == source_uri)
                .where(Document.status != DocumentStatus.DELETED)
            )
            .scalar_one_or_none()
        )

        if document:
            # 命中已有文档：递增版本号并重置状态，触发新一轮入库。
            document.current_version += 1
            document.title = source_uri
            document.status = DocumentStatus.PENDING
            document.metadata_ = metadata_dict
            version_no = document.current_version
        else:
            # 首次上传：创建文档主记录。
            document = Document(
                tenant_id=ctx.tenant_id,
                workspace_id=kb.workspace_id,
                kb_id=kb_id,
                title=source_uri,
                source_type=SourceType.UPLOAD,
                source_uri=source_uri,
                current_version=1,
                status=DocumentStatus.PENDING,
                metadata_=metadata_dict,
                created_by=ctx.user_id,
            )
            db.add(document)
            db.flush()
            version_no = 1

        # 先落对象存储，再创建文档版本记录，确保版本可追溯到真实文件对象。
        object_key = persist_upload(
            tenant_id=ctx.tenant_id,
            kb_id=kb_id,
            document_id=document.id,
            version=version_no,
            filename=source_uri,
            content=content,
        )

        doc_version = DocumentVersion(
            tenant_id=ctx.tenant_id,
            document_id=document.id,
            version=version_no,
            object_key=object_key,
            parser_type=infer_parser_type(source_uri),
            parse_status=ParseStatus.PENDING,
            checksum=checksum,
        )
        db.add(doc_version)
        db.flush()

        # 创建异步入库任务（带幂等键），避免重复请求产生重复任务。
        ingestion_job = enqueue_ingestion_job(
            db=db,
            tenant_id=ctx.tenant_id,
            workspace_id=kb.workspace_id,
            kb_id=kb_id,
            document_id=document.id,
            document_version_id=doc_version.id,
            action="upload",
            client_idempotency_key=idempotency_key,
        )

        audit_log(
            db=db,
            request=request,
            tenant_id=ctx.tenant_id,
            actor_user_id=ctx.user_id,
            action="document.upload",
            resource_type="document",
            resource_id=str(document.id),
            after_json={
                "workspace_id": str(kb.workspace_id),
                "kb_id": str(kb_id),
                "version": version_no,
                "object_key": object_key,
                "job_id": str(ingestion_job.id),
            },
        )

        db.commit()
    except Exception:
        db.rollback()
        raise

    return success(
        request,
        {
            "document_id": document.id,
            "workspace_id": document.workspace_id,
            "document_version_id": doc_version.id,
            "version": version_no,
            "status": document.status,
            "job_id": ingestion_job.id,
            "job_status": ingestion_job.status,
        },
    )


@router.get(
    "/knowledge-bases/{kb_id}/documents",
    summary="查询文档列表",
    description="返回指定知识库下当前用户可见的文档列表。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[DocumentData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_documents(
    request: Request,
    kb_id: UUID = Path(..., description="目标知识库 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """按知识库范围查询文档。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_READ,
    )
    # 先做知识库读权限校验，避免通过枚举 kb_id 越权读取文档清单。
    kb, _, _ = ensure_kb_read_access(
        db,
        tenant_id=ctx.tenant_id,
        kb_id=kb_id,
        user_id=ctx.user_id,
    )

    stmt = (
        select(Document)
        .where(Document.tenant_id == ctx.tenant_id)
        .where(Document.workspace_id == kb.workspace_id)
        .where(Document.kb_id == kb_id)
        .where(Document.status != DocumentStatus.DELETED)
    )
    documents = db.execute(stmt).scalars().all()
    data = [
        {
            "id": d.id,
            "workspace_id": d.workspace_id,
            "kb_id": d.kb_id,
            "title": d.title,
            "source_type": d.source_type,
            "source_uri": d.source_uri,
            "current_version": d.current_version,
            "status": d.status,
            "metadata": d.metadata_,
        }
        for d in documents
    ]
    return success(request, data)


@router.get(
    "/documents/{document_id}",
    summary="查询文档详情",
    description="按文档 ID 返回文档元信息与当前状态。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[DocumentData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_document(
    request: Request,
    document_id: UUID = Path(..., description="文档 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询单个文档详情。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_READ,
    )
    document, _ = ensure_document_read_access(
        db,
        tenant_id=ctx.tenant_id,
        document_id=document_id,
        user_id=ctx.user_id,
    )

    return success(
        request,
        {
            "id": document.id,
            "workspace_id": document.workspace_id,
            "kb_id": document.kb_id,
            "title": document.title,
            "source_type": document.source_type,
            "source_uri": document.source_uri,
            "current_version": document.current_version,
            "status": document.status,
            "metadata": document.metadata_,
        },
    )


@router.get(
    "/documents/{document_id}/ingestion-status",
    summary="查询文档入库状态",
    description="返回文档的入库任务状态、进度和错误信息。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_document_ingestion_status(
    request: Request,
    document_id: UUID = Path(..., description="文档 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询文档入库状态和进度。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_READ,
    )
    document, _ = ensure_document_read_access(
        db,
        tenant_id=ctx.tenant_id,
        document_id=document_id,
        user_id=ctx.user_id,
    )

    # 查询最新的入库任务
    latest_job = (
        db.execute(
            select(IngestionJob)
            .where(IngestionJob.tenant_id == ctx.tenant_id)
            .where(IngestionJob.document_id == document_id)
            .order_by(IngestionJob.created_at.desc())
            .limit(1)
        )
        .scalar_one_or_none()
    )

    if not latest_job:
        return success(
            request,
            {
                "document_id": str(document_id),
                "status": "no_job",
                "message": "暂无入库任务",
            },
        )

    # 任务模型已内置 stage/progress/error/finished_at 字段，直接对齐返回。
    progress = latest_job.progress
    if latest_job.status == IngestionJobStatus.COMPLETED:
        progress = 100
    progress = max(0, min(100, int(progress)))

    return success(
        request,
        {
            "document_id": str(document_id),
            "job_id": str(latest_job.id),
            "status": latest_job.status,
            "stage": latest_job.stage or "queued",
            "progress": progress,
            "error": latest_job.error,
            "created_at": latest_job.created_at.isoformat() if latest_job.created_at else None,
            "completed_at": latest_job.finished_at.isoformat() if latest_job.finished_at else None,
        },
    )


@router.get(
    "/documents/{document_id}/versions",
    summary="查询文档版本列表",
    description="按文档 ID 返回所有版本信息（按版本号倒序）。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[DocumentVersionData]],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_document_versions(
    request: Request,
    document_id: UUID = Path(..., description="文档 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询文档版本列表。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_READ,
    )
    ensure_document_read_access(
        db,
        tenant_id=ctx.tenant_id,
        document_id=document_id,
        user_id=ctx.user_id,
    )

    versions = (
        db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.tenant_id == ctx.tenant_id)
            .where(DocumentVersion.document_id == document_id)
            .order_by(DocumentVersion.version.desc())
        )
        .scalars()
        .all()
    )
    data = [
        {
            "id": version.id,
            "document_id": version.document_id,
            "version": version.version,
            "object_key": version.object_key,
            "parser_type": version.parser_type,
            "parse_status": version.parse_status,
            "checksum": version.checksum,
            "created_at": version.created_at,
        }
        for version in versions
    ]
    return success(request, data)


@router.get(
    "/documents/{document_id}/versions/{version}",
    summary="查询文档版本详情",
    description="按文档 ID + 版本号返回单个版本详情。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[DocumentVersionData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_document_version(
    request: Request,
    document_id: UUID = Path(..., description="文档 ID。"),
    version: int = Path(..., ge=1, description="文档版本号。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询文档版本详情。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_READ,
    )
    ensure_document_read_access(
        db,
        tenant_id=ctx.tenant_id,
        document_id=document_id,
        user_id=ctx.user_id,
    )

    doc_version = (
        db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.tenant_id == ctx.tenant_id)
            .where(DocumentVersion.document_id == document_id)
            .where(DocumentVersion.version == version)
        )
        .scalar_one_or_none()
    )
    if not doc_version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document version not found")

    return success(
        request,
        {
            "id": doc_version.id,
            "document_id": doc_version.document_id,
            "version": doc_version.version,
            "object_key": doc_version.object_key,
            "parser_type": doc_version.parser_type,
            "parse_status": doc_version.parse_status,
            "checksum": doc_version.checksum,
            "created_at": doc_version.created_at,
        },
    )


@router.get(
    "/documents/{document_id}/versions/{version}/chunks",
    summary="按版本查询文档切片分页",
    description="按文档 ID + 版本号分页查询切片内容。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[DocumentChunkPageData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_document_chunks_by_version(
    request: Request,
    document_id: UUID = Path(..., description="文档 ID。"),
    version: int = Path(..., ge=1, description="文档版本号。"),
    offset: int = Query(default=0, ge=0, description="分页偏移。"),
    limit: int = Query(default=50, ge=1, le=200, description="分页大小。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """按显式版本号分页查询文档切片。"""
    return list_document_chunks(
        request=request,
        document_id=document_id,
        version=version,
        offset=offset,
        limit=limit,
        ctx=ctx,
        db=db,
    )


@router.get(
    "/documents/{document_id}/chunks",
    summary="查询文档切片分页",
    description="按文档版本分页查询切片内容。未指定版本时默认使用文档当前版本。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[DocumentChunkPageData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_document_chunks(
    request: Request,
    document_id: UUID = Path(..., description="文档 ID。"),
    version: int | None = Query(default=None, ge=1, description="可选文档版本号，默认当前版本。"),
    offset: int = Query(default=0, ge=0, description="分页偏移。"),
    limit: int = Query(default=50, ge=1, le=200, description="分页大小。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """分页查询文档切片。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_READ,
    )
    document, _ = ensure_document_read_access(
        db,
        tenant_id=ctx.tenant_id,
        document_id=document_id,
        user_id=ctx.user_id,
    )

    target_version = version if version is not None else document.current_version
    doc_version = (
        db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.tenant_id == ctx.tenant_id)
            .where(DocumentVersion.document_id == document_id)
            .where(DocumentVersion.version == target_version)
        )
        .scalar_one_or_none()
    )
    if not doc_version:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="document version not found")

    total = (
        db.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.tenant_id == ctx.tenant_id)
            .where(DocumentChunk.document_id == document_id)
            .where(DocumentChunk.document_version_id == doc_version.id)
        )
        .scalar_one()
    )
    chunks = (
        db.execute(
            select(DocumentChunk)
            .where(DocumentChunk.tenant_id == ctx.tenant_id)
            .where(DocumentChunk.document_id == document_id)
            .where(DocumentChunk.document_version_id == doc_version.id)
            .order_by(DocumentChunk.chunk_no.asc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )

    return success(
        request,
        {
            "document_id": document_id,
            "version": target_version,
            "document_version_id": doc_version.id,
            "total": int(total),
            "offset": offset,
            "limit": limit,
            "items": [
                {
                    "id": chunk.id,
                    "document_id": chunk.document_id,
                    "document_version_id": chunk.document_version_id,
                    "chunk_no": chunk.chunk_no,
                    "title_path": chunk.title_path,
                    "content": chunk.content,
                    "token_count": chunk.token_count,
                    "metadata": chunk.metadata_,
                    "created_at": chunk.created_at,
                }
                for chunk in chunks
            ],
        },
    )


@router.patch(
    "/documents/{document_id}",
    summary="更新文档元信息",
    description="更新文档标题和元数据。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[DocumentData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def update_document(
    payload: DocumentUpdateRequest,
    request: Request,
    document_id: UUID = Path(..., description="文档 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """更新文档元信息。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_WRITE,
    )
    document, kb = ensure_document_read_access(
        db,
        tenant_id=ctx.tenant_id,
        document_id=document_id,
        user_id=ctx.user_id,
    )
    ensure_kb_write_access(
        db,
        tenant_id=ctx.tenant_id,
        kb_id=UUID(str(kb.id)),
        user_id=ctx.user_id,
    )

    before = {"title": document.title, "metadata": document.metadata_}
    if payload.title is not None:
        document.title = payload.title
    if payload.metadata is not None:
        document.metadata_ = payload.metadata

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="document.update",
        resource_type="document",
        resource_id=str(document.id),
        before_json=before,
        after_json={"title": document.title, "metadata": document.metadata_},
    )
    db.commit()

    return success(
        request,
        {
            "id": document.id,
            "workspace_id": document.workspace_id,
            "kb_id": document.kb_id,
            "title": document.title,
            "source_type": document.source_type,
            "source_uri": document.source_uri,
            "current_version": document.current_version,
            "status": document.status,
            "metadata": document.metadata_,
        },
    )


@router.post(
    "/documents/{document_id}/reindex",
    summary="重建文档索引",
    description="为文档当前版本重新创建入库任务。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[ReindexData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def reindex_document(
    request: Request,
    document_id: UUID = Path(..., description="文档 ID。"),
    idempotency_key: str | None = Header(
        default=None,
        alias="Idempotency-Key",
        description="可选幂等键，用于重复请求去重。",
    ),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """创建（或复用）重建索引任务。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_WRITE,
    )
    # 读权限用于确认文档可见性，写权限用于确认可发起重建任务。
    document, kb = ensure_document_read_access(
        db,
        tenant_id=ctx.tenant_id,
        document_id=document_id,
        user_id=ctx.user_id,
    )

    ensure_kb_write_access(
        db,
        tenant_id=ctx.tenant_id,
        kb_id=UUID(str(kb.id)),
        user_id=ctx.user_id,
    )

    # 仅对当前生效版本做重建，保持"查询到什么版本就重建什么版本"的一致性。
    doc_version = (
        db.execute(
            select(DocumentVersion)
            .where(DocumentVersion.document_id == document_id)
            .where(DocumentVersion.version == document.current_version)
        )
        .scalar_one_or_none()
    )
    if not doc_version:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="document version missing")

    job = enqueue_ingestion_job(
        db=db,
        tenant_id=ctx.tenant_id,
        workspace_id=kb.workspace_id,
        kb_id=document.kb_id,
        document_id=document_id,
        document_version_id=doc_version.id,
        action="reindex",
        client_idempotency_key=idempotency_key,
    )

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="document.reindex",
        resource_type="document",
        resource_id=str(document.id),
        after_json={"document_version_id": str(doc_version.id), "job_id": str(job.id)},
    )

    db.commit()

    return success(request, {"job_id": job.id, "status": job.status})


@router.delete(
    "/documents/{document_id}",
    summary="删除文档",
    description="逻辑删除文档，并清理关联版本、切片、向量与入库任务记录。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[DocumentData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def delete_document(
    request: Request,
    document_id: UUID = Path(..., description="文档 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """删除文档。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_DELETE,
    )
    document, kb = ensure_document_read_access(
        db,
        tenant_id=ctx.tenant_id,
        document_id=document_id,
        user_id=ctx.user_id,
    )
    ensure_kb_write_access(
        db,
        tenant_id=ctx.tenant_id,
        kb_id=UUID(str(kb.id)),
        user_id=ctx.user_id,
    )

    before_status = document.status
    document.status = DocumentStatus.DELETED

    version_ids = (
        db.execute(
            select(DocumentVersion.id).where(DocumentVersion.document_id == document_id)
        )
        .scalars()
        .all()
    )
    if version_ids:
        chunk_ids = (
            db.execute(
                select(DocumentChunk.id).where(DocumentChunk.document_version_id.in_(version_ids))
            )
            .scalars()
            .all()
        )
        if chunk_ids:
            db.execute(delete(ChunkEmbedding).where(ChunkEmbedding.chunk_id.in_(chunk_ids)))
            db.execute(delete(DocumentChunk).where(DocumentChunk.id.in_(chunk_ids)))

        db.execute(delete(DocumentVersion).where(DocumentVersion.id.in_(version_ids)))

    db.execute(delete(IngestionJob).where(IngestionJob.document_id == document_id))

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="document.delete",
        resource_type="document",
        resource_id=str(document.id),
        before_json={"status": before_status},
        after_json={"status": document.status},
    )
    db.commit()

    return success(
        request,
        {
            "id": document.id,
            "workspace_id": document.workspace_id,
            "kb_id": document.kb_id,
            "title": document.title,
            "source_type": document.source_type,
            "source_uri": document.source_uri,
            "current_version": document.current_version,
            "status": document.status,
            "metadata": document.metadata_,
        },
    )


def _build_job_diagnosis(job: IngestionJob, *, now_utc: datetime) -> dict[str, str]:
    """生成入库任务诊断信息，便于快速排障。"""
    if job.status == IngestionJobStatus.DEAD_LETTER:
        return {
            "category": "dead_letter",
            "summary": "任务已进入死信队列，需要人工介入。",
            "suggestion": "请先修复根因后调用重试接口重新入队。",
        }

    if job.status == IngestionJobStatus.RETRYING:
        return {
            "category": "retrying",
            "summary": "任务处于自动重试等待状态。",
            "suggestion": "可等待 next_run_at 自动重试，或手工触发重试加速恢复。",
        }

    if job.status == IngestionJobStatus.PROCESSING:
        heartbeat_at = job.heartbeat_at
        if heartbeat_at is not None and heartbeat_at.tzinfo is None:
            heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
        if heartbeat_at is not None and (now_utc - heartbeat_at).total_seconds() > 300:
            return {
                "category": "stale_processing",
                "summary": "任务长时间未刷新心跳，疑似卡住。",
                "suggestion": "检查 worker 进程与对象存储后，可将任务打入死信再重试。",
            }
        return {
            "category": "processing",
            "summary": "任务正在处理。",
            "suggestion": "持续轮询任务状态，关注 stage 与 progress 是否推进。",
        }

    if job.status == IngestionJobStatus.QUEUED:
        return {
            "category": "queued",
            "summary": "任务等待 worker 抢占执行。",
            "suggestion": "检查 worker 可用性与队列积压情况。",
        }

    if job.status == IngestionJobStatus.COMPLETED:
        return {
            "category": "completed",
            "summary": "任务已完成。",
            "suggestion": "无需额外处理，可继续检索验证入库效果。",
        }

    return {
        "category": "unknown",
        "summary": "任务状态未识别。",
        "suggestion": "请检查任务状态枚举与数据一致性。",
    }


def _serialize_ingestion_job(job: IngestionJob, *, now_utc: datetime | None = None) -> dict[str, object]:
    """统一序列化入库任务响应结构。"""
    current = now_utc or datetime.now(timezone.utc)
    retryable = job.status in {IngestionJobStatus.RETRYING, IngestionJobStatus.DEAD_LETTER}
    retry_in_seconds = 0
    if job.next_run_at is not None:
        next_run_at = job.next_run_at
        if next_run_at.tzinfo is None:
            next_run_at = next_run_at.replace(tzinfo=timezone.utc)
        retry_in_seconds = max(0, int((next_run_at - current).total_seconds()))
    can_retry_now = retryable and retry_in_seconds == 0

    return {
        "job_id": job.id,
        "workspace_id": job.workspace_id,
        "document_id": job.document_id,
        "document_version_id": job.document_version_id,
        "status": job.status,
        "stage": job.stage,
        "progress": job.progress,
        "attempt_count": job.attempt_count,
        "max_attempts": job.max_attempts,
        "next_run_at": job.next_run_at,
        "locked_at": job.locked_at,
        "locked_by": job.locked_by,
        "heartbeat_at": job.heartbeat_at,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "error": job.error,
        "terminal": job.status in {IngestionJobStatus.COMPLETED, IngestionJobStatus.DEAD_LETTER},
        "retryable": retryable,
        "can_retry_now": can_retry_now,
        "retry_in_seconds": retry_in_seconds,
        "diagnosis": _build_job_diagnosis(job, now_utc=current),
    }


@router.get(
    "/ingestion-jobs/{job_id}",
    summary="查询入库任务",
    description="用于轮询异步入库任务状态。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[IngestionJobData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_ingestion_job(
    request: Request,
    job_id: UUID = Path(..., description="入库任务 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """按任务 ID 返回任务运行状态。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_READ,
    )
    job = db.get(IngestionJob, job_id)
    if not job or job.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")

    # 入库任务归属于知识库，读取任务状态前仍需经过知识库可读校验。
    ensure_kb_read_access(
        db,
        tenant_id=ctx.tenant_id,
        kb_id=job.kb_id,
        user_id=ctx.user_id,
    )

    return success(request, _serialize_ingestion_job(job))


@router.post(
    "/ingestion-jobs/{job_id}/retry",
    summary="手工重试入库任务",
    description="将 retrying/dead_letter 任务重新入队（queued），用于故障恢复。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[IngestionJobData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def retry_ingestion_job(
    request: Request,
    job_id: UUID = Path(..., description="入库任务 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """手工重试入库任务。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_WRITE,
    )
    job = db.get(IngestionJob, job_id)
    if not job or job.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")

    ensure_kb_write_access(
        db,
        tenant_id=ctx.tenant_id,
        kb_id=job.kb_id,
        user_id=ctx.user_id,
    )

    if job.status == IngestionJobStatus.PROCESSING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="job is processing")
    if job.status == IngestionJobStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="job already completed")

    before = {
        "status": job.status,
        "stage": job.stage,
        "attempt_count": job.attempt_count,
        "error": job.error,
    }
    now_utc = datetime.now(timezone.utc)
    job.status = IngestionJobStatus.QUEUED
    job.stage = "queued"
    job.progress = 0
    job.next_run_at = now_utc
    job.locked_at = None
    job.locked_by = None
    job.heartbeat_at = None
    job.finished_at = None
    job.error = None

    doc = db.get(Document, job.document_id)
    if doc and doc.tenant_id == ctx.tenant_id and doc.status != DocumentStatus.DELETED:
        doc.status = DocumentStatus.PENDING

    version = db.get(DocumentVersion, job.document_version_id)
    if version and version.tenant_id == ctx.tenant_id:
        version.parse_status = ParseStatus.PENDING

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="ingestion.job.retry",
        resource_type="ingestion_job",
        resource_id=str(job.id),
        before_json=before,
        after_json={"status": job.status, "stage": job.stage},
    )
    db.commit()
    db.refresh(job)
    return success(request, _serialize_ingestion_job(job))


@router.post(
    "/ingestion-jobs/{job_id}/dead-letter",
    summary="手工打入死信",
    description="将任务标记为 dead_letter，便于人工排障后再重试。",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[IngestionJobData],
    responses={
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
def dead_letter_ingestion_job(
    payload: IngestionJobDeadLetterRequest,
    request: Request,
    job_id: UUID = Path(..., description="入库任务 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """手工将任务置为死信状态。"""
    require_tenant_action(
        db,
        tenant_id=ctx.tenant_id,
        tenant_role=ctx.tenant_role,
        action=PermissionAction.DOCUMENT_WRITE,
    )
    job = db.get(IngestionJob, job_id)
    if not job or job.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="job not found")

    ensure_kb_write_access(
        db,
        tenant_id=ctx.tenant_id,
        kb_id=job.kb_id,
        user_id=ctx.user_id,
    )

    if job.status == IngestionJobStatus.COMPLETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="completed job cannot be dead-lettered")

    reason = (payload.reason or "").strip() or "manual dead letter by operator"
    before = {
        "status": job.status,
        "stage": job.stage,
        "attempt_count": job.attempt_count,
        "error": job.error,
    }
    now_utc = datetime.now(timezone.utc)
    job.status = IngestionJobStatus.DEAD_LETTER
    job.stage = "failed"
    job.progress = 0
    job.error = reason
    job.finished_at = now_utc
    job.heartbeat_at = now_utc
    job.locked_at = None
    job.locked_by = None

    doc = db.get(Document, job.document_id)
    if doc and doc.tenant_id == ctx.tenant_id and doc.status != DocumentStatus.DELETED:
        doc.status = DocumentStatus.FAILED

    version = db.get(DocumentVersion, job.document_version_id)
    if version and version.tenant_id == ctx.tenant_id:
        version.parse_status = ParseStatus.FAILED

    audit_log(
        db=db,
        request=request,
        tenant_id=ctx.tenant_id,
        actor_user_id=ctx.user_id,
        action="ingestion.job.dead_letter",
        resource_type="ingestion_job",
        resource_id=str(job.id),
        before_json=before,
        after_json={"status": job.status, "stage": job.stage, "error": job.error},
    )
    db.commit()
    db.refresh(job)
    return success(request, _serialize_ingestion_job(job))
