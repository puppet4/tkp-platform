import pytest
from pydantic import ValidationError

from tkp_rag.core.config import Settings


def test_rag_settings_reject_blank_internal_token():
    with pytest.raises(ValidationError):
        Settings(internal_service_token="   ")


def test_rag_settings_accept_valid_internal_token():
    cfg = Settings(internal_service_token="internal-token-123")
    assert cfg.internal_service_token == "internal-token-123"
