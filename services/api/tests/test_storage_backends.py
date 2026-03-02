from uuid import uuid4

from tkp_api.core.config import get_settings
from tkp_api.services import storage as storage_service


class _FakeMinio:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def bucket_exists(self, bucket: str) -> bool:
        return True

    def put_object(self, bucket_name: str, object_name: str, data, length: int, content_type: str):
        self.objects[(bucket_name, object_name)] = data.read(length)


def test_persist_upload_local_backend(tmp_path, monkeypatch):
    monkeypatch.setenv("KD_STORAGE_BACKEND", "local")
    monkeypatch.setenv("KD_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("KD_STORAGE_KEY_PREFIX", "unit-test")
    get_settings.cache_clear()

    key = storage_service.persist_upload(
        tenant_id=uuid4(),
        kb_id=uuid4(),
        document_id=uuid4(),
        version=1,
        filename="../../hello.txt",
        content=b"hello-local",
    )

    assert key.startswith("unit-test/")
    assert (tmp_path / key).read_bytes() == b"hello-local"
    get_settings.cache_clear()


def test_persist_upload_minio_backend(tmp_path, monkeypatch):
    fake_client = _FakeMinio()

    monkeypatch.setenv("KD_STORAGE_BACKEND", "minio")
    monkeypatch.setenv("KD_STORAGE_ROOT", str(tmp_path))
    monkeypatch.setenv("KD_STORAGE_BUCKET", "tkp-unit")
    monkeypatch.setenv("KD_STORAGE_KEY_PREFIX", "ingestion")
    get_settings.cache_clear()

    monkeypatch.setattr(storage_service, "_build_minio_client", lambda _settings: fake_client)

    key = storage_service.persist_upload(
        tenant_id=uuid4(),
        kb_id=uuid4(),
        document_id=uuid4(),
        version=2,
        filename="doc.md",
        content=b"hello-minio",
    )

    assert key.startswith("ingestion/")
    assert fake_client.objects[("tkp-unit", key)] == b"hello-minio"
    get_settings.cache_clear()
