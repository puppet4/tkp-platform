from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tkp_api.core.exceptions import PermissionDeniedException
from tkp_api.core.security import AuthenticatedPrincipal
from tkp_api.dependencies import ensure_user, get_request_context
from tkp_api.models.enums import MembershipStatus, TenantRole, WorkspaceRole
from tkp_api.models.tenant import TenantMembership, User
from tkp_api.services.membership_sync import normalize_email, workspace_role_from_tenant_role


def test_ensure_user_handles_oversized_subject_and_email():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    User.__table__.create(engine)
    local_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    db = local_session()
    try:
        huge_subject = "x" * 1200
        huge_email = f"{'y' * 300}@example.com"
        principal = AuthenticatedPrincipal(
            subject=huge_subject,
            provider="local",
            email=huge_email,
            display_name="z" * 260,
            claims={"sub": huge_subject},
        )

        user = ensure_user(db, principal)
        db.commit()

        assert len(user.external_subject) <= 256
        assert len(user.email) <= 256
        assert len(user.display_name) <= 128
    finally:
        db.close()


def test_normalize_email():
    assert normalize_email("  Alice@Example.COM ") == "alice@example.com"


def test_workspace_role_from_tenant_role():
    assert workspace_role_from_tenant_role(TenantRole.OWNER) == WorkspaceRole.OWNER
    assert workspace_role_from_tenant_role(TenantRole.ADMIN) == WorkspaceRole.EDITOR
    assert workspace_role_from_tenant_role(TenantRole.MEMBER) == WorkspaceRole.VIEWER
    assert workspace_role_from_tenant_role(TenantRole.VIEWER) == WorkspaceRole.VIEWER


@pytest.fixture
def db_session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    User.__table__.create(engine)
    TenantMembership.__table__.create(engine)
    local_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)
    db = local_session()
    try:
        yield db
    finally:
        db.close()


def _seed_user_and_membership(db: Session, *, tenant_id: UUID) -> User:
    user = User(
        id=uuid4(),
        email="ctx-user@example.com",
        display_name="Ctx User",
        status="active",
        auth_provider="local",
        external_subject="ctx-user-subject",
    )
    db.add(user)
    db.flush()
    db.add(
        TenantMembership(
            tenant_id=tenant_id,
            user_id=user.id,
            role=TenantRole.ADMIN,
            status=MembershipStatus.ACTIVE,
        )
    )
    db.commit()
    return user


def test_get_request_context_uses_token_tenant_id(db_session: Session):
    tenant_id = UUID("00000000-0000-0000-0000-00000000aa11")
    user = _seed_user_and_membership(db_session, tenant_id=tenant_id)
    principal = AuthenticatedPrincipal(
        subject="ctx-user-subject",
        provider="local",
        email=user.email,
        display_name=user.display_name,
        claims={"sub": "ctx-user-subject", "tenant_id": str(tenant_id)},
    )
    ctx = get_request_context(principal=principal, db=db_session)
    assert ctx.tenant_id == tenant_id
    assert ctx.user_id == user.id
    assert ctx.tenant_role == TenantRole.ADMIN


def test_get_request_context_requires_token_tenant_id(db_session: Session):
    tenant_id = UUID("00000000-0000-0000-0000-00000000aa12")
    _seed_user_and_membership(db_session, tenant_id=tenant_id)
    principal = AuthenticatedPrincipal(
        subject="ctx-user-subject",
        provider="local",
        email="ctx-user@example.com",
        display_name="Ctx User",
        claims={"sub": "ctx-user-subject"},
    )
    with pytest.raises(PermissionDeniedException) as exc:
        get_request_context(principal=principal, db=db_session)
    assert exc.value.status_code == 403
