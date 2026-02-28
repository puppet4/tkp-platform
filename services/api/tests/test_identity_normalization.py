from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tkp_api.core.security import AuthenticatedPrincipal
from tkp_api.dependencies import ensure_user
from tkp_api.models.tenant import User


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
