"""导入批次接口：支持多文件批量上传。"""

import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Request, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tkp_api.db.session import get_db
from tkp_api.dependencies import get_request_context
from tkp_api.models.enums import DocumentStatus, ImportBatchStatus, IngestionJobStatus, ParseStatus, SourceType
from tkp_api.models.knowledge import Document, DocumentVersion, ImportBatch, IngestionJob
from tkp_api.schemas.common import ErrorResponse, SuccessResponse
from tkp_api.schemas.responses import ImportBatchData, ImportBatchDetailData, ImportBatchFileData
from tkp_api.services import (
    PermissionAction,
    audit_log,
    enqueue_ingestion_job,
    ensure_kb_write_access,
    infer_parser_type,
    persist_upload,
    require_tenant_action,
)
from tkp_api.services.quota import QuotaMetric, enforce_quota
from tkp_api.utils.response import success

router = APIRouter(tags=["import-batches"])

_MAX_UPLOAD_BYTES = 50 * 1024 * 1024


@router.post(
    "/knowledge-bases/{kb_id}/import-batches",
    summary="创建导入批次",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[ImportBatchData],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def create_import_batch(
    request: Request,
    kb_id: UUID = Path(..., description="目标知识库 ID。"),
    body: dict = None,
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """创建导入批次。"""
    body = body or {}
    total_files = body.get("total_files", 0)
    label = body.get("label")

    if not isinstance(total_files, int) or total_files < 1 or total_files > 100:
        raise HTTPException(status_code=422, detail="total_files must be between 1 and 100")

    require_tenant_action(
        db, tenant_id=ctx.tenant_id, tenant_role=ctx.tenant_role, action=PermissionAction.DOCUMENT_WRITE,
    )
    kb, _, _ = ensure_kb_write_access(db, tenant_id=ctx.tenant_id, kb_id=kb_id, user_id=ctx.user_id)
    enforce_quota(
        db, tenant_id=ctx.tenant_id, metric_code=QuotaMetric.DOCUMENT_UPLOADS.value,
        projected_increment=total_files, workspace_id=kb.workspace_id, actor_user_id=ctx.user_id,
    )

    batch = ImportBatch(
        tenant_id=ctx.tenant_id,
        workspace_id=kb.workspace_id,
        kb_id=kb_id,
        created_by=ctx.user_id,
        label=label,
        total_files=total_files,
        status=ImportBatchStatus.UPLOADING,
    )
    db.add(batch)
    db.flush()

    audit_log(
        db=db, request=request, tenant_id=ctx.tenant_id, actor_user_id=ctx.user_id,
        action="import_batch.create", resource_type="import_batch", resource_id=str(batch.id),
        after_json={"kb_id": str(kb_id), "total_files": total_files},
    )
    db.commit()

    return success(request, _serialize_batch(batch))


@router.post(
    "/import-batches/{batch_id}/files",
    summary="上传文件到批次",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[dict],
    responses={401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
async def upload_file_to_batch(
    request: Request,
    batch_id: UUID = Path(..., description="批次 ID。"),
    file: UploadFile = File(..., description="待上传文件。"),
    relative_path: str | None = Form(default=None, description="文件相对路径（文件夹上传时使用）。"),
    metadata: str | None = Form(default=None, description="可选 JSON 元数据。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """上传单个文件到导入批次。"""
    batch = db.get(ImportBatch, batch_id)
    if not batch or batch.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="batch not found")
    if batch.status != ImportBatchStatus.UPLOADING:
        raise HTTPException(status_code=409, detail="batch is not in uploading state")

    require_tenant_action(
        db, tenant_id=ctx.tenant_id, tenant_role=ctx.tenant_role, action=PermissionAction.DOCUMENT_WRITE,
    )
    kb, _, _ = ensure_kb_write_access(db, tenant_id=ctx.tenant_id, kb_id=batch.kb_id, user_id=ctx.user_id)

    metadata_dict = {}
    if metadata:
        try:
            metadata_dict = json.loads(metadata)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="invalid metadata") from exc

    content = await file.read()
    filename = (file.filename or "").strip()
    if not filename:
        batch.failed_uploads += 1
        db.commit()
        raise HTTPException(status_code=422, detail="filename is empty")
    if not content:
        batch.failed_uploads += 1
        db.commit()
        raise HTTPException(status_code=422, detail="file content is empty")
    if len(content) > _MAX_UPLOAD_BYTES:
        batch.failed_uploads += 1
        db.commit()
        raise HTTPException(status_code=422, detail=f"file exceeds {_MAX_UPLOAD_BYTES // 1024 // 1024} MB limit")

    source_uri = relative_path or filename
    checksum = hashlib.sha256(content).hexdigest()

    # SHA-256 dedup: check if same checksum exists in this KB
    existing_version = db.execute(
        select(DocumentVersion)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(Document.tenant_id == ctx.tenant_id)
        .where(Document.kb_id == batch.kb_id)
        .where(Document.status != DocumentStatus.DELETED)
        .where(DocumentVersion.checksum == checksum)
    ).scalar_one_or_none()

    if existing_version:
        batch.uploaded_files += 1
        db.commit()
        return success(request, {
            "document_id": existing_version.document_id,
            "duplicate": True,
            "title": filename,
        })

    try:
        # Find or create document
        document = db.execute(
            select(Document)
            .where(Document.tenant_id == ctx.tenant_id)
            .where(Document.workspace_id == kb.workspace_id)
            .where(Document.kb_id == batch.kb_id)
            .where(Document.source_type == SourceType.UPLOAD)
            .where(Document.source_uri == source_uri)
            .where(Document.status != DocumentStatus.DELETED)
        ).scalar_one_or_none()

        if document:
            document.current_version += 1
            document.title = filename
            document.status = DocumentStatus.PENDING
            document.metadata_ = metadata_dict
            document.batch_id = batch_id
            version_no = document.current_version
        else:
            document = Document(
                tenant_id=ctx.tenant_id,
                workspace_id=kb.workspace_id,
                kb_id=batch.kb_id,
                title=filename,
                source_type=SourceType.UPLOAD,
                source_uri=source_uri,
                current_version=1,
                status=DocumentStatus.PENDING,
                metadata_=metadata_dict,
                created_by=ctx.user_id,
                batch_id=batch_id,
            )
            db.add(document)
            db.flush()
            version_no = 1

        object_key = persist_upload(
            tenant_id=ctx.tenant_id, kb_id=batch.kb_id,
            document_id=document.id, version=version_no,
            filename=source_uri, content=content,
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

        job = enqueue_ingestion_job(
            db=db, tenant_id=ctx.tenant_id, workspace_id=kb.workspace_id,
            kb_id=batch.kb_id, document_id=document.id,
            document_version_id=doc_version.id, action="upload",
            client_idempotency_key=None, batch_id=batch_id,
        )

        batch.uploaded_files += 1
        db.commit()

        return success(request, {
            "document_id": document.id,
            "document_version_id": doc_version.id,
            "version": version_no,
            "job_id": job.id,
            "duplicate": False,
            "title": filename,
        })
    except Exception:
        db.rollback()
        # Re-fetch batch since rollback cleared it
        batch = db.get(ImportBatch, batch_id)
        if batch:
            batch.failed_uploads += 1
            db.commit()
        raise


@router.post(
    "/import-batches/{batch_id}/finalize",
    summary="完成批次上传",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[ImportBatchData],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def finalize_import_batch(
    request: Request,
    batch_id: UUID = Path(..., description="批次 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """标记批次上传完成，推进状态至 ingesting。"""
    batch = db.get(ImportBatch, batch_id)
    if not batch or batch.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="batch not found")
    if batch.status != ImportBatchStatus.UPLOADING:
        raise HTTPException(status_code=409, detail="batch is not in uploading state")

    if batch.uploaded_files == 0 and batch.failed_uploads == 0:
        batch.status = ImportBatchStatus.CANCELLED
    elif batch.uploaded_files == 0:
        batch.status = ImportBatchStatus.PARTIAL_FAILURE
    else:
        batch.status = ImportBatchStatus.INGESTING

    db.commit()
    return success(request, _serialize_batch(batch))


@router.get(
    "/import-batches/{batch_id}",
    summary="批次详情",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[ImportBatchDetailData],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def get_import_batch(
    request: Request,
    batch_id: UUID = Path(..., description="批次 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询批次详情（含文件状态）。"""
    batch = db.get(ImportBatch, batch_id)
    if not batch or batch.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="batch not found")

    # Query documents in this batch
    docs = db.execute(
        select(Document).where(Document.batch_id == batch_id).where(Document.tenant_id == ctx.tenant_id)
    ).scalars().all()

    doc_ids = [d.id for d in docs]
    jobs_by_doc: dict[UUID, IngestionJob] = {}
    if doc_ids:
        # Get latest job per document
        jobs = db.execute(
            select(IngestionJob)
            .where(IngestionJob.batch_id == batch_id)
            .where(IngestionJob.tenant_id == ctx.tenant_id)
        ).scalars().all()
        for j in jobs:
            existing = jobs_by_doc.get(j.document_id)
            if not existing or (j.created_at and existing.created_at and j.created_at > existing.created_at):
                jobs_by_doc[j.document_id] = j

    files = []
    for doc in docs:
        job = jobs_by_doc.get(doc.id)
        files.append({
            "document_id": doc.id,
            "title": doc.title,
            "status": doc.status,
            "job_id": job.id if job else None,
            "job_status": job.status if job else None,
            "job_stage": job.stage if job else None,
            "job_progress": job.progress if job else None,
            "error": job.error if job else None,
        })

    # Auto-advance batch status based on job states
    if batch.status == ImportBatchStatus.INGESTING and jobs_by_doc:
        all_terminal = all(
            j.status in {IngestionJobStatus.COMPLETED, IngestionJobStatus.DEAD_LETTER}
            for j in jobs_by_doc.values()
        )
        if all_terminal:
            has_failed = any(j.status == IngestionJobStatus.DEAD_LETTER for j in jobs_by_doc.values())
            all_completed = all(j.status == IngestionJobStatus.COMPLETED for j in jobs_by_doc.values())
            if all_completed and batch.failed_uploads == 0:
                batch.status = ImportBatchStatus.COMPLETED
            elif has_failed or batch.failed_uploads > 0:
                batch.status = ImportBatchStatus.PARTIAL_FAILURE
            else:
                batch.status = ImportBatchStatus.COMPLETED
            db.commit()

    data = _serialize_batch(batch)
    data["files"] = files
    return success(request, data)


@router.get(
    "/knowledge-bases/{kb_id}/import-batches",
    summary="批次列表",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[list[ImportBatchData]],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def list_import_batches(
    request: Request,
    kb_id: UUID = Path(..., description="知识库 ID。"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """查询知识库下的导入批次列表。"""
    batches = db.execute(
        select(ImportBatch)
        .where(ImportBatch.tenant_id == ctx.tenant_id)
        .where(ImportBatch.kb_id == kb_id)
        .order_by(ImportBatch.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).scalars().all()

    total = db.execute(
        select(func.count())
        .select_from(ImportBatch)
        .where(ImportBatch.tenant_id == ctx.tenant_id)
        .where(ImportBatch.kb_id == kb_id)
    ).scalar_one()

    data = [_serialize_batch(b) for b in batches]
    return success(request, data, meta={"total": int(total), "offset": offset, "limit": limit})


@router.post(
    "/import-batches/{batch_id}/cancel",
    summary="取消批次",
    status_code=status.HTTP_200_OK,
    response_model=SuccessResponse[ImportBatchData],
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
def cancel_import_batch(
    request: Request,
    batch_id: UUID = Path(..., description="批次 ID。"),
    ctx=Depends(get_request_context),
    db: Session = Depends(get_db),
):
    """取消导入批次。"""
    batch = db.get(ImportBatch, batch_id)
    if not batch or batch.tenant_id != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="batch not found")
    if batch.status in {ImportBatchStatus.COMPLETED, ImportBatchStatus.CANCELLED}:
        raise HTTPException(status_code=409, detail="batch cannot be cancelled")

    batch.status = ImportBatchStatus.CANCELLED
    db.commit()
    return success(request, _serialize_batch(batch))


def _serialize_batch(batch: ImportBatch) -> dict:
    return {
        "id": batch.id,
        "kb_id": batch.kb_id,
        "label": batch.label,
        "total_files": batch.total_files,
        "uploaded_files": batch.uploaded_files,
        "failed_uploads": batch.failed_uploads,
        "status": batch.status,
        "created_at": batch.created_at,
        "updated_at": batch.updated_at,
    }
