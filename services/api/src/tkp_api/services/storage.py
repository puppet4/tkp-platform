"""对象存储服务，支持 local / minio / oss。"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Protocol
from uuid import UUID

from tkp_api.core.config import Settings, get_settings


class StorageProvider(Protocol):
    """对象存储驱动协议。"""

    def put_bytes(self, object_key: str, content: bytes, content_type: str = "application/octet-stream") -> None:
        """写入对象字节。"""


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


def _sanitize_prefix(prefix: str | None) -> str:
    """规范化对象键前缀。"""
    if not prefix:
        return ""
    clean = prefix.strip().strip("/")
    return f"{clean}/" if clean else ""


def build_object_key(
    tenant_id: UUID,
    kb_id: UUID,
    document_id: UUID,
    version: int,
    filename: str,
    *,
    key_prefix: str | None = None,
) -> str:
    """构建稳定对象键。"""
    safe_name = Path(filename).name or "document.bin"
    base_key = f"tenant/{tenant_id}/kb/{kb_id}/doc/{document_id}/v{version}/{safe_name}"
    return f"{_sanitize_prefix(key_prefix)}{base_key}"


class LocalStorageProvider:
    """本地文件系统存储。"""

    def __init__(self, storage_root: str) -> None:
        self._root = Path(storage_root)

    def put_bytes(self, object_key: str, content: bytes, content_type: str = "application/octet-stream") -> None:
        target = self._root.joinpath(object_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def _build_minio_client(settings: Settings):
    """构建 MinIO 客户端（延迟导入，避免本地不依赖时启动失败）。"""
    try:
        from minio import Minio
    except ModuleNotFoundError as exc:
        raise RuntimeError("minio backend requires package 'minio'") from exc

    if not settings.storage_endpoint:
        raise RuntimeError("storage endpoint is required for minio backend")
    if not settings.storage_access_key or not settings.storage_secret_key:
        raise RuntimeError("storage access_key/secret_key is required for minio backend")

    return Minio(
        settings.storage_endpoint,
        access_key=settings.storage_access_key,
        secret_key=settings.storage_secret_key,
        secure=settings.storage_secure,
        region=settings.storage_region,
    )


class MinioStorageProvider:
    """MinIO 对象存储。"""

    def __init__(self, settings: Settings) -> None:
        self._bucket = settings.storage_bucket
        self._client = _build_minio_client(settings)
        if not self._client.bucket_exists(self._bucket):
            self._client.make_bucket(self._bucket)

    def put_bytes(self, object_key: str, content: bytes, content_type: str = "application/octet-stream") -> None:
        self._client.put_object(
            bucket_name=self._bucket,
            object_name=object_key,
            data=BytesIO(content),
            length=len(content),
            content_type=content_type,
        )


def _build_oss_bucket(settings: Settings):
    """构建阿里云 OSS Bucket 客户端（延迟导入）。"""
    try:
        import oss2
    except ModuleNotFoundError as exc:
        raise RuntimeError("oss backend requires package 'oss2'") from exc

    if not settings.storage_endpoint:
        raise RuntimeError("storage endpoint is required for oss backend")
    if not settings.storage_access_key or not settings.storage_secret_key:
        raise RuntimeError("storage access_key/secret_key is required for oss backend")

    endpoint = settings.storage_endpoint
    if not endpoint.startswith("http://") and not endpoint.startswith("https://"):
        endpoint = f"https://{endpoint}" if settings.storage_secure else f"http://{endpoint}"

    auth = oss2.Auth(settings.storage_access_key, settings.storage_secret_key)
    return oss2.Bucket(auth, endpoint, settings.storage_bucket)


class OssStorageProvider:
    """阿里云 OSS 存储。"""

    def __init__(self, settings: Settings) -> None:
        self._bucket = _build_oss_bucket(settings)

    def put_bytes(self, object_key: str, content: bytes, content_type: str = "application/octet-stream") -> None:
        self._bucket.put_object(
            object_key,
            content,
            headers={"Content-Type": content_type},
        )


def get_storage_provider(settings: Settings | None = None) -> StorageProvider:
    """根据配置创建对象存储驱动。"""
    cfg = settings or get_settings()
    if cfg.storage_backend == "local":
        return LocalStorageProvider(cfg.storage_root)
    if cfg.storage_backend == "minio":
        return MinioStorageProvider(cfg)
    if cfg.storage_backend == "oss":
        return OssStorageProvider(cfg)
    raise RuntimeError(f"unsupported storage backend: {cfg.storage_backend}")


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
    object_key = build_object_key(
        tenant_id=tenant_id,
        kb_id=kb_id,
        document_id=document_id,
        version=version,
        filename=filename,
        key_prefix=settings.storage_key_prefix,
    )
    provider = get_storage_provider(settings)
    provider.put_bytes(object_key, content)
    return object_key
