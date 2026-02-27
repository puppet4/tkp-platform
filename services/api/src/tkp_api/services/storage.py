"""对象存储服务（当前为本地文件系统实现）。"""

from pathlib import Path
from uuid import UUID

from tkp_api.core.config import get_settings


def infer_parser_type(filename: str) -> str:
    """根据文件后缀推断解析器类型。"""
    ext = Path(filename).suffix.lower()
    if ext in {".md", ".markdown", ".txt"}:
        return "markdown"
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
        return "image"
    if ext in {".pdf"}:
        return "pdf"
    return "generic"


def persist_upload(
    tenant_id: UUID,
    kb_id: UUID,
    document_id: UUID,
    version: int,
    filename: str,
    content: bytes,
) -> str:
    """保存上传文件并返回对象键。"""
    settings = get_settings()
    # 仅保留文件名部分，避免目录穿越风险。
    safe_name = Path(filename).name or "document.bin"
    object_key = f"tenant/{tenant_id}/kb/{kb_id}/doc/{document_id}/v{version}/{safe_name}"

    target = Path(settings.storage_root).joinpath(object_key)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    return object_key
