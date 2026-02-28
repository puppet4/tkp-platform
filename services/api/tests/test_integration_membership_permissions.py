import jwt
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.requests import Request

from tkp_api.api import auth as auth_api
from tkp_api.api import permissions as permissions_api
from tkp_api.api import tenants as tenants_api
from tkp_api.api import users as users_api
from tkp_api.core.config import get_settings
from tkp_api.core.security import AuthenticatedPrincipal
from tkp_api.core.security import parse_authorization_header
from tkp_api.dependencies import RequestContext
from tkp_api.models.auth import UserCredential
from tkp_api.models.enums import MembershipStatus, TenantRole, WorkspaceRole
from tkp_api.models.knowledge import KBMembership
from tkp_api.models.permission import TenantRolePermission
from tkp_api.models.tenant import Tenant, TenantMembership, User
from tkp_api.models.workspace import Workspace, WorkspaceMembership
from tkp_api.schemas.auth import AuthLoginRequest, AuthRegisterRequest, AuthSwitchTenantRequest
from tkp_api.schemas.permission import PermissionTemplatePublishRequest, RolePermissionUpdateRequest
from tkp_api.schemas.tenant import TenantMemberInviteRequest
from tkp_api.services.tenant_bootstrap import create_tenant_with_owner


def _make_request(path: str = "/test") -> Request:
    request = Request({"type": "http", "method": "GET", "path": path, "headers": []})
    request.state.request_id = "test-request-id"
    return request


def _make_ctx(*, user: User, tenant_id, tenant_role: str) -> RequestContext:
    principal = AuthenticatedPrincipal(
        subject=str(user.id),
        provider="local",
        email=user.email,
        display_name=user.display_name,
        claims={"sub": str(user.id)},
    )
    return RequestContext(
        user_id=user.id,
        tenant_id=tenant_id,
        tenant_role=tenant_role,
        principal=principal,
    )


def _create_user(db: Session, *, email: str, display_name: str | None = None) -> User:
    user = User(
        id=uuid4(),
        email=email,
        display_name=display_name or email.split("@")[0],
        status="active",
        auth_provider="local",
        external_subject=email,
    )
    db.add(user)
    db.flush()
    return user


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    for table in (
        User.__table__,
        UserCredential.__table__,
        Tenant.__table__,
        TenantMembership.__table__,
        Workspace.__table__,
        WorkspaceMembership.__table__,
        KBMembership.__table__,
        TenantRolePermission.__table__,
    ):
        table.create(engine)
    local_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    db = local_session()
    try:
        yield db
    finally:
        db.close()


def test_register_creates_personal_tenant_and_default_workspace(db_session: Session):
    response = auth_api.register(
        payload=AuthRegisterRequest(
            email="alice@example.com",
            password="StrongPassw0rd!",
            display_name="Alice",
        ),
        request=_make_request("/auth/register"),
        db=db_session,
    )
    data = response["data"]

    user = db_session.execute(select(User).where(User.email == "alice@example.com")).scalar_one()
    tenant_membership = (
        db_session.execute(
            select(TenantMembership)
            .where(TenantMembership.user_id == user.id)
            .where(TenantMembership.tenant_id == data["personal_tenant_id"])
        )
        .scalar_one()
    )
    workspace = db_session.get(Workspace, data["default_workspace_id"])
    workspace_membership = (
        db_session.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.workspace_id == workspace.id)
            .where(WorkspaceMembership.user_id == user.id)
        )
        .scalar_one()
    )

    assert tenant_membership.role == TenantRole.OWNER
    assert tenant_membership.status == MembershipStatus.ACTIVE
    assert workspace.slug == "default"
    assert workspace_membership.role == WorkspaceRole.OWNER
    assert workspace_membership.status == MembershipStatus.ACTIVE


def test_register_existing_credential_returns_clear_error(db_session: Session):
    _create_user(db_session, email="dup@example.com", display_name="Dup")
    db_session.commit()
    auth_api.register(
        payload=AuthRegisterRequest(
            email="dup@example.com",
            password="StrongPassw0rd!",
            display_name="Dup",
        ),
        request=_make_request("/auth/register"),
        db=db_session,
    )

    with pytest.raises(HTTPException) as exc:
        auth_api.register(
            payload=AuthRegisterRequest(
                email="dup@example.com",
                password="StrongPassw0rd!",
                display_name="Dup",
            ),
            request=_make_request("/auth/register"),
            db=db_session,
        )

    assert exc.value.status_code == 409
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail["code"] == "REGISTER_CREDENTIAL_EXISTS"
    assert "请直接登录" in exc.value.detail["message"]


def test_register_blank_display_name_returns_clear_error(db_session: Session):
    with pytest.raises(HTTPException) as exc:
        auth_api.register(
            payload=AuthRegisterRequest(
                email="blank-display@example.com",
                password="StrongPassw0rd!",
                display_name="   ",
            ),
            request=_make_request("/auth/register"),
            db=db_session,
        )

    assert exc.value.status_code == 422
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail["code"] == "REGISTER_INVALID_DISPLAY_NAME"
    assert "展示名" in exc.value.detail["message"]


def test_login_wrong_password_returns_clear_error(db_session: Session):
    auth_api.register(
        payload=AuthRegisterRequest(
            email="login-wrong@example.com",
            password="StrongPassw0rd!",
            display_name="Login Wrong",
        ),
        request=_make_request("/auth/register"),
        db=db_session,
    )
    with pytest.raises(HTTPException) as exc:
        auth_api.login(
            payload=AuthLoginRequest(
                email="login-wrong@example.com",
                password="WrongPassw0rd!",
            ),
            request=_make_request("/auth/login"),
            db=db_session,
        )
    assert exc.value.status_code == 401
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail["code"] == "LOGIN_INVALID_CREDENTIALS"
    assert "账号或密码错误" in exc.value.detail["message"]


def test_login_disabled_user_returns_clear_error(db_session: Session):
    user = _create_user(db_session, email="disabled@example.com", display_name="Disabled")
    user.status = "disabled"
    db_session.commit()

    with pytest.raises(HTTPException) as exc:
        auth_api.login(
            payload=AuthLoginRequest(
                email="disabled@example.com",
                password="StrongPassw0rd!",
            ),
            request=_make_request("/auth/login"),
            db=db_session,
        )
    assert exc.value.status_code == 403
    assert isinstance(exc.value.detail, dict)
    assert exc.value.detail["code"] == "LOGIN_USER_DISABLED"
    assert "账号已被禁用" in exc.value.detail["message"]


def test_login_response_contains_tenant_id(db_session: Session, monkeypatch):
    monkeypatch.setenv("KD_AUTH_JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("KD_AUTH_JWT_ALGORITHMS", "HS256")

    auth_api.register(
        payload=AuthRegisterRequest(
            email="tenant-login@example.com",
            password="StrongPassw0rd!",
            display_name="Tenant Login",
        ),
        request=_make_request("/auth/register"),
        db=db_session,
    )

    login_response = auth_api.login(
        payload=AuthLoginRequest(
            email="tenant-login@example.com",
            password="StrongPassw0rd!",
        ),
        request=_make_request("/auth/login"),
        db=db_session,
    )
    tenant_id = login_response["data"]["tenant_id"]
    token = login_response["data"]["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})

    assert tenant_id is not None
    assert claims["tenant_id"] == str(tenant_id)


def test_login_single_session_keeps_latest_token(db_session: Session, monkeypatch):
    monkeypatch.setenv("KD_AUTH_JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("KD_AUTH_JWT_ALGORITHMS", "HS256")
    monkeypatch.delenv("KD_AUTH_JWT_ISSUER", raising=False)
    monkeypatch.delenv("KD_AUTH_JWT_AUDIENCE", raising=False)
    monkeypatch.delenv("KD_AUTH_JWKS_URL", raising=False)
    monkeypatch.delenv("KD_REDIS_URL", raising=False)
    get_settings.cache_clear()

    auth_api.register(
        payload=AuthRegisterRequest(
            email="sso-login@example.com",
            password="StrongPassw0rd!",
            display_name="SSO Login",
        ),
        request=_make_request("/auth/register"),
        db=db_session,
    )
    login1 = auth_api.login(
        payload=AuthLoginRequest(
            email="sso-login@example.com",
            password="StrongPassw0rd!",
        ),
        request=_make_request("/auth/login"),
        db=db_session,
    )
    login2 = auth_api.login(
        payload=AuthLoginRequest(
            email="sso-login@example.com",
            password="StrongPassw0rd!",
        ),
        request=_make_request("/auth/login"),
        db=db_session,
    )
    with pytest.raises(HTTPException) as exc:
        parse_authorization_header(f"Bearer {login1['data']['access_token']}")
    assert exc.value.status_code == 401
    principal = parse_authorization_header(f"Bearer {login2['data']['access_token']}")
    assert principal.claims.get("tkp_uid")
    get_settings.cache_clear()


def test_switch_tenant_issues_token_with_target_tenant(db_session: Session, monkeypatch):
    monkeypatch.setenv("KD_AUTH_JWT_SECRET", "unit-test-secret")
    monkeypatch.setenv("KD_AUTH_JWT_ALGORITHMS", "HS256")

    register_response = auth_api.register(
        payload=AuthRegisterRequest(
            email="switch-tenant@example.com",
            password="StrongPassw0rd!",
            display_name="Switch Tenant",
        ),
        request=_make_request("/auth/register"),
        db=db_session,
    )
    user = db_session.get(User, register_response["data"]["user_id"])
    _, target_workspace = create_tenant_with_owner(
        db_session,
        owner_user_id=user.id,
        tenant_name="Second Tenant",
        tenant_slug="second-tenant",
    )
    db_session.commit()

    switch_response = auth_api.switch_tenant(
        payload=AuthSwitchTenantRequest(tenant_id=target_workspace.tenant_id),
        request=_make_request("/auth/switch-tenant"),
        user=user,
        db=db_session,
    )
    token = switch_response["data"]["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})

    assert switch_response["data"]["tenant_id"] == target_workspace.tenant_id
    assert claims["tenant_id"] == str(target_workspace.tenant_id)


def test_invite_and_join_tenant_flow(db_session: Session, monkeypatch):
    monkeypatch.setattr(tenants_api, "audit_log", lambda **_: None)

    owner = _create_user(db_session, email="owner@example.com")
    tenant, _ = create_tenant_with_owner(
        db_session,
        owner_user_id=owner.id,
        tenant_name="Tenant A",
        tenant_slug="tenant-a",
    )
    db_session.commit()

    owner_ctx = _make_ctx(user=owner, tenant_id=tenant.id, tenant_role=TenantRole.OWNER)
    invite_response = tenants_api.invite_tenant_member(
        payload=TenantMemberInviteRequest(email="member@example.com", role=TenantRole.MEMBER),
        request=_make_request("/tenants/invite"),
        tenant_id=tenant.id,
        ctx=owner_ctx,
        db=db_session,
    )
    assert invite_response["data"]["status"] == MembershipStatus.INVITED

    invited_user = db_session.execute(select(User).where(User.email == "member@example.com")).scalar_one()
    join_response = tenants_api.join_tenant(
        request=_make_request("/tenants/join"),
        tenant_id=tenant.id,
        user=invited_user,
        db=db_session,
    )

    tenant_membership = (
        db_session.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == tenant.id)
            .where(TenantMembership.user_id == invited_user.id)
        )
        .scalar_one()
    )
    workspace_membership = (
        db_session.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.tenant_id == tenant.id)
            .where(WorkspaceMembership.user_id == invited_user.id)
        )
        .scalar_one()
    )

    assert join_response["data"]["status"] == MembershipStatus.ACTIVE
    assert tenant_membership.status == MembershipStatus.ACTIVE
    assert workspace_membership.status == MembershipStatus.ACTIVE
    assert workspace_membership.role == WorkspaceRole.VIEWER


def test_role_permission_update_and_template_publish_affect_snapshot(db_session: Session, monkeypatch):
    monkeypatch.setattr(permissions_api, "audit_log", lambda **_: None)

    owner = _create_user(db_session, email="owner2@example.com")
    member = _create_user(db_session, email="member2@example.com")
    tenant, _ = create_tenant_with_owner(
        db_session,
        owner_user_id=owner.id,
        tenant_name="Tenant B",
        tenant_slug="tenant-b",
    )
    db_session.add(
        TenantMembership(
            tenant_id=tenant.id,
            user_id=member.id,
            role=TenantRole.MEMBER,
            status=MembershipStatus.ACTIVE,
        )
    )
    db_session.commit()

    owner_ctx = _make_ctx(user=owner, tenant_id=tenant.id, tenant_role=TenantRole.OWNER)
    member_ctx = _make_ctx(user=member, tenant_id=tenant.id, tenant_role=TenantRole.MEMBER)

    permissions_api.update_role_permissions(
        payload=RolePermissionUpdateRequest(
            permission_codes=[
                "api.tenant.read",
                "menu.document",
            ]
        ),
        request=_make_request("/permissions/roles/member"),
        role=TenantRole.MEMBER,
        ctx=owner_ctx,
        db=db_session,
    )

    snapshot_after_override = permissions_api.my_permission_snapshot(
        request=_make_request("/permissions/me"),
        ctx=member_ctx,
        db=db_session,
    )
    assert snapshot_after_override["data"]["allowed_actions"] == ["api.tenant.read", "menu.document"]

    permissions_api.publish_default_template(
        payload=PermissionTemplatePublishRequest(overwrite_existing=True),
        request=_make_request("/permissions/templates/default/publish"),
        ctx=owner_ctx,
        db=db_session,
    )
    snapshot_after_publish = permissions_api.my_permission_snapshot(
        request=_make_request("/permissions/me"),
        ctx=member_ctx,
        db=db_session,
    )
    assert "api.chat.completion" in snapshot_after_publish["data"]["allowed_actions"]
    assert "menu.workspace" in snapshot_after_publish["data"]["allowed_actions"]

    with pytest.raises(HTTPException) as exc:
        permissions_api.update_role_permissions(
            payload=RolePermissionUpdateRequest(permission_codes=["api.tenant.read", "unknown.bad.code"]),
            request=_make_request("/permissions/roles/member"),
            role=TenantRole.MEMBER,
            ctx=owner_ctx,
            db=db_session,
        )
    assert exc.value.status_code == 422


def test_remove_user_disables_workspace_and_kb_memberships(db_session: Session, monkeypatch):
    monkeypatch.setattr(users_api, "audit_log", lambda **_: None)

    owner = _create_user(db_session, email="owner3@example.com")
    member = _create_user(db_session, email="member3@example.com")
    tenant, workspace = create_tenant_with_owner(
        db_session,
        owner_user_id=owner.id,
        tenant_name="Tenant C",
        tenant_slug="tenant-c",
    )
    db_session.add(
        TenantMembership(
            tenant_id=tenant.id,
            user_id=member.id,
            role=TenantRole.MEMBER,
            status=MembershipStatus.ACTIVE,
        )
    )
    db_session.add(
        WorkspaceMembership(
            tenant_id=tenant.id,
            workspace_id=workspace.id,
            user_id=member.id,
            role=WorkspaceRole.VIEWER,
            status=MembershipStatus.ACTIVE,
        )
    )
    db_session.add(
        KBMembership(
            tenant_id=tenant.id,
            kb_id=uuid4(),
            user_id=member.id,
            role="kb_viewer",
            status=MembershipStatus.ACTIVE,
        )
    )
    db_session.commit()

    owner_ctx = _make_ctx(user=owner, tenant_id=tenant.id, tenant_role=TenantRole.OWNER)
    response = users_api.remove_user(
        request=_make_request("/users/remove"),
        user_id=member.id,
        ctx=owner_ctx,
        db=db_session,
    )

    tenant_membership = (
        db_session.execute(
            select(TenantMembership)
            .where(TenantMembership.tenant_id == tenant.id)
            .where(TenantMembership.user_id == member.id)
        )
        .scalar_one()
    )
    workspace_membership = (
        db_session.execute(
            select(WorkspaceMembership)
            .where(WorkspaceMembership.tenant_id == tenant.id)
            .where(WorkspaceMembership.user_id == member.id)
        )
        .scalar_one()
    )
    kb_membership = (
        db_session.execute(
            select(KBMembership)
            .where(KBMembership.tenant_id == tenant.id)
            .where(KBMembership.user_id == member.id)
        )
        .scalar_one()
    )

    assert response["data"]["membership_status"] == MembershipStatus.DISABLED
    assert tenant_membership.status == MembershipStatus.DISABLED
    assert workspace_membership.status == MembershipStatus.DISABLED
    assert kb_membership.status == MembershipStatus.DISABLED
    assert db_session.get(User, member.id).status == "disabled"
