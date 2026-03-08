from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from tkp_api.api import auth as auth_api
from tkp_api.models.auth import UserCredential, UserMfaTotp
from tkp_api.models.enums import MembershipStatus, TenantRole, WorkspaceRole
from tkp_api.models.tenant import Tenant, TenantMembership, User
from tkp_api.models.workspace import Workspace, WorkspaceMembership
from tkp_api.schemas.auth import (
    AuthLoginRequest,
    AuthMFALoginRequest,
    AuthMFATotpDisableRequest,
    AuthMFATotpEnableRequest,
    AuthMFATotpSetupRequest,
    AuthRegisterRequest,
)
from tkp_api.services.local_auth import generate_totp_code


def _make_request(path: str = "/test") -> Request:
    request = Request({"type": "http", "method": "GET", "path": path, "headers": []})
    request.state.request_id = "test-request-id"
    return request


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    for table in (
        User.__table__,
        UserCredential.__table__,
        UserMfaTotp.__table__,
        Tenant.__table__,
        TenantMembership.__table__,
        Workspace.__table__,
        WorkspaceMembership.__table__,
    ):
        table.create(engine)
    local_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    db = local_session()
    try:
        yield db
    finally:
        db.close()


def _register_user(db: Session, email: str, password: str) -> User:
    res = auth_api.register(
        payload=AuthRegisterRequest(email=email, password=password, display_name="MFA User"),
        request=_make_request("/auth/register"),
        db=db,
    )
    return db.get(User, res["data"]["user_id"])


def test_totp_login_requires_otp_after_enabled(db_session: Session):
    password = "StrongPassw0rd!"
    user = _register_user(db_session, f"mfa-{uuid4().hex[:8]}@example.com", password)
    assert user is not None

    setup = auth_api.setup_totp_mfa(
        payload=AuthMFATotpSetupRequest(password=password),
        request=_make_request("/auth/mfa/totp/setup"),
        user=user,
        db=db_session,
    )
    secret = setup["data"]["secret"]
    code = generate_totp_code(secret)

    enabled = auth_api.enable_totp_mfa(
        payload=AuthMFATotpEnableRequest(code=code),
        request=_make_request("/auth/mfa/totp/enable"),
        user=user,
        db=db_session,
    )
    assert enabled["data"]["enabled"] is True
    assert len(enabled["data"]["backup_codes"]) == 8

    with pytest.raises(HTTPException) as exc:
        auth_api.login(
            payload=AuthLoginRequest(email=user.email, password=password),
            request=_make_request("/auth/login"),
            db=db_session,
        )
    assert exc.value.status_code == 401
    assert exc.value.detail["code"] == "LOGIN_MFA_REQUIRED"
    challenge_token = exc.value.detail["details"]["challenge_token"]

    login = auth_api.login_mfa_totp(
        payload=AuthMFALoginRequest(challenge_token=challenge_token, otp_code=generate_totp_code(secret)),
        request=_make_request("/auth/login/mfa"),
        db=db_session,
    )
    assert isinstance(login["data"]["access_token"], str)
    assert login["data"]["tenant_id"] is not None


def test_totp_disable_with_backup_code_restores_password_login(db_session: Session):
    password = "StrongPassw0rd!"
    user = _register_user(db_session, f"mfa-disable-{uuid4().hex[:8]}@example.com", password)
    setup = auth_api.setup_totp_mfa(
        payload=AuthMFATotpSetupRequest(password=password),
        request=_make_request("/auth/mfa/totp/setup"),
        user=user,
        db=db_session,
    )
    secret = setup["data"]["secret"]
    enabled = auth_api.enable_totp_mfa(
        payload=AuthMFATotpEnableRequest(code=generate_totp_code(secret)),
        request=_make_request("/auth/mfa/totp/enable"),
        user=user,
        db=db_session,
    )
    backup_code = enabled["data"]["backup_codes"][0]

    disabled = auth_api.disable_totp_mfa(
        payload=AuthMFATotpDisableRequest(password=password, backup_code=backup_code),
        request=_make_request("/auth/mfa/totp/disable"),
        user=user,
        db=db_session,
    )
    assert disabled["data"]["enabled"] is False

    login = auth_api.login(
        payload=AuthLoginRequest(email=user.email, password=password),
        request=_make_request("/auth/login"),
        db=db_session,
    )
    assert isinstance(login["data"]["access_token"], str)
