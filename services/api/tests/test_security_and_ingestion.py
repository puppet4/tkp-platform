import jwt
import pytest
from fastapi import HTTPException
from uuid import UUID

from tkp_api.core.config import get_settings
from tkp_api.core.security import activate_user_session, parse_authorization_header, revoke_token_jti
from tkp_api.services.ingestion import build_job_idempotency_key
from tkp_api.services.local_auth import hash_password, issue_access_token, verify_password
from tkp_api.models.tenant import User


def test_parse_authorization_header_jwt(monkeypatch):
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


def test_parse_authorization_header_accepts_jwt(monkeypatch):
    monkeypatch.setenv("KD_AUTH_JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("KD_AUTH_JWT_ALGORITHMS", "HS256")
    monkeypatch.delenv("KD_AUTH_JWT_ISSUER", raising=False)
    monkeypatch.delenv("KD_AUTH_JWT_AUDIENCE", raising=False)
    monkeypatch.delenv("KD_AUTH_JWKS_URL", raising=False)

    get_settings.cache_clear()

    token = jwt.encode(
        {"sub": "jwt-user", "email": "jwt@example.com", "name": "JWT User"},
        "unit-test-secret",
        algorithm="HS256",
    )
    principal = parse_authorization_header(f"Bearer {token}")

    assert principal.subject == "jwt-user"
    assert principal.email == "jwt@example.com"


def test_parse_authorization_header_prefers_real_token_when_placeholder_exists(monkeypatch):
    monkeypatch.setenv("KD_AUTH_JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("KD_AUTH_JWT_ALGORITHMS", "HS256")
    monkeypatch.delenv("KD_AUTH_JWT_ISSUER", raising=False)
    monkeypatch.delenv("KD_AUTH_JWT_AUDIENCE", raising=False)
    monkeypatch.delenv("KD_AUTH_JWKS_URL", raising=False)
    get_settings.cache_clear()

    token = jwt.encode(
        {"sub": "jwt-user-2", "email": "jwt2@example.com"},
        "unit-test-secret",
        algorithm="HS256",
    )
    principal = parse_authorization_header(f"Bearer {{bearerToken}}, Bearer {token}")
    assert principal.subject == "jwt-user-2"
    assert principal.email == "jwt2@example.com"


def test_parse_authorization_header_rejects_placeholder_token(monkeypatch):
    monkeypatch.setenv("KD_AUTH_JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("KD_AUTH_JWT_ALGORITHMS", "HS256")
    monkeypatch.delenv("KD_AUTH_JWT_ISSUER", raising=False)
    monkeypatch.delenv("KD_AUTH_JWT_AUDIENCE", raising=False)
    monkeypatch.delenv("KD_AUTH_JWKS_URL", raising=False)
    get_settings.cache_clear()

    with pytest.raises(HTTPException) as exc:
        parse_authorization_header("Bearer {{bearerToken}}")
    assert exc.value.status_code == 401
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail["code"] == "AUTH_TOKEN_PLACEHOLDER_NOT_RESOLVED"


def test_issue_access_token_contains_tenant_claim(monkeypatch):
    monkeypatch.setenv("KD_AUTH_JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("KD_AUTH_JWT_ALGORITHMS", "HS256")
    monkeypatch.delenv("KD_AUTH_JWT_ISSUER", raising=False)
    monkeypatch.delenv("KD_AUTH_JWT_AUDIENCE", raising=False)
    get_settings.cache_clear()

    user = User(
        id=UUID("00000000-0000-0000-0000-000000000111"),
        email="token@example.com",
        display_name="Token User",
        auth_provider="local",
        external_subject="token@example.com",
    )
    tenant_id = UUID("00000000-0000-0000-0000-000000000222")
    token, _, _, _ = issue_access_token(user, tenant_id=tenant_id)
    claims = jwt.decode(token, options={"verify_signature": False})

    assert claims["tenant_id"] == str(tenant_id)
    assert claims["tkp_uid"] == str(user.id)


def test_single_session_new_login_invalidates_old_token(monkeypatch):
    monkeypatch.setenv("KD_AUTH_JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("KD_AUTH_JWT_ALGORITHMS", "HS256")
    monkeypatch.delenv("KD_AUTH_JWT_ISSUER", raising=False)
    monkeypatch.delenv("KD_AUTH_JWT_AUDIENCE", raising=False)
    monkeypatch.delenv("KD_AUTH_JWKS_URL", raising=False)
    monkeypatch.delenv("KD_REDIS_URL", raising=False)
    get_settings.cache_clear()

    user = User(
        id=UUID("00000000-0000-0000-0000-000000000333"),
        email="sso@example.com",
        display_name="SSO User",
        auth_provider="local",
        external_subject="sso@example.com",
    )
    token1, exp1, _, jti1 = issue_access_token(user)
    activate_user_session(user_session_id=str(user.id), jti=jti1, exp_ts=exp1)
    parse_authorization_header(f"Bearer {token1}")

    token2, exp2, _, jti2 = issue_access_token(user)
    activate_user_session(user_session_id=str(user.id), jti=jti2, exp_ts=exp2)
    with pytest.raises(HTTPException) as exc:
        parse_authorization_header(f"Bearer {token1}")
    assert exc.value.status_code == 401
    parse_authorization_header(f"Bearer {token2}")
    get_settings.cache_clear()
