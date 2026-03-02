from pathlib import Path

from tkp_worker.main import _read_object_bytes


class _FakeObject:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def close(self) -> None:
        return None

    def release_conn(self) -> None:
        return None


class _FakeMinio:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def get_object(self, bucket: str, object_name: str):
        assert bucket == "tkp-unit"
        assert object_name == "tenant/a/doc.md"
        return _FakeObject(self._payload)


def test_read_object_bytes_local(tmp_path):
    p = Path(tmp_path) / "tenant/a/doc.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"local-bytes")

    data = _read_object_bytes(
        backend="local",
        storage_root=str(tmp_path),
        object_key="tenant/a/doc.md",
        bucket_name="ignored",
    )
    assert data == b"local-bytes"


def test_read_object_bytes_minio(monkeypatch):
    from tkp_worker import main as worker_main

    fake = _FakeMinio(b"minio-bytes")
    monkeypatch.setattr(worker_main, "_build_minio_client", lambda *_args, **_kwargs: fake)

    data = _read_object_bytes(
        backend="minio",
        storage_root="./unused",
        object_key="tenant/a/doc.md",
        bucket_name="tkp-unit",
        endpoint="127.0.0.1:9000",
        access_key="ak",
        secret_key="sk",
        secure=False,
    )
    assert data == b"minio-bytes"
