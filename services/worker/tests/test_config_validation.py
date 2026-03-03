import pytest
from pydantic import ValidationError

from tkp_worker.config import Settings


def test_worker_settings_reject_minio_without_required_fields():
    with pytest.raises(ValidationError):
        Settings(storage_backend="minio", storage_endpoint=None, storage_access_key=None, storage_secret_key=None)


def test_worker_settings_accept_valid_minio_config():
    cfg = Settings(
        storage_backend="minio",
        storage_endpoint="127.0.0.1:9000",
        storage_access_key="minioadmin",
        storage_secret_key="minioadmin",
    )
    assert cfg.storage_backend == "minio"
