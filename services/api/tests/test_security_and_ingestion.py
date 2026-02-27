import jwt
import pytest
from fastapi import HTTPException

from tkp_api.core.config import get_settings
from tkp_api.core.security import parse_authorization_header, revoke_token_jti
from tkp_api.services.ingestion import build_job_idempotency_key
from tkp_api.services.local_auth import hash_password, verify_password


def test_parse_authorization_header_jwt(monkeypatch):
    monkeypatch.setenv("KD_AUTH_MODE", "jwt")
    monkeypatch.setenv("KD_AUTH_JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("KD_AUTH_JWT_ALGORITHMS", "HS256")
    monkeypatch.delenv("KD_AUTH_JWT_ISSUER", raising=False)
    monkeypatch.delenv("KD_AUTH_JWT_AUDIENCE", raising=False)
    monkeypatch.delenv("KD_AUTH_JWKS_URL", raising=False)

    get_settings.cache_clear()

    token = jwt.encode({"sub": "user-1", "email": "u1@example.com"}, "unit-test-secret", algorithm="HS256")
    principal = parse_authorization_header(f"Bearer {token}")

    assert principal.subject == "user-1"
    assert principal.email == "u1@example.com"


def test_build_job_idempotency_key_is_deterministic():
    key1 = build_job_idempotency_key(
        tenant_id="00000000-0000-0000-0000-000000000001",
        workspace_id="00000000-0000-0000-0000-000000000010",
        kb_id="00000000-0000-0000-0000-000000000002",
        document_id="00000000-0000-0000-0000-000000000003",
        document_version_id="00000000-0000-0000-0000-000000000004",
        action="upload",
        client_key="abc",
    )
    key2 = build_job_idempotency_key(
        tenant_id="00000000-0000-0000-0000-000000000001",
        workspace_id="00000000-0000-0000-0000-000000000010",
        kb_id="00000000-0000-0000-0000-000000000002",
        document_id="00000000-0000-0000-0000-000000000003",
        document_version_id="00000000-0000-0000-0000-000000000004",
        action="upload",
        client_key="abc",
    )

    assert key1 == key2
    assert len(key1) == 64


def test_password_hash_and_verify():
    password_hash = hash_password("StrongPassw0rd!")
    assert verify_password("StrongPassw0rd!", password_hash)
    assert not verify_password("wrong-password", password_hash)


def test_parse_authorization_header_revoked_token(monkeypatch):
    monkeypatch.setenv("KD_AUTH_MODE", "jwt")
    monkeypatch.setenv("KD_AUTH_JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("KD_AUTH_JWT_ALGORITHMS", "HS256")
    monkeypatch.delenv("KD_AUTH_JWT_ISSUER", raising=False)
    monkeypatch.delenv("KD_AUTH_JWT_AUDIENCE", raising=False)
    monkeypatch.delenv("KD_AUTH_JWKS_URL", raising=False)

    get_settings.cache_clear()

    exp_ts = 32503680000
    jti = "revoked-test-jti"
    token = jwt.encode(
        {"sub": "user-1", "email": "u1@example.com", "jti": jti, "exp": exp_ts},
        "unit-test-secret",
        algorithm="HS256",
    )
    revoke_token_jti(jti, exp_ts)

    with pytest.raises(HTTPException) as exc:
        parse_authorization_header(f"Bearer {token}")
    assert exc.value.status_code == 401
