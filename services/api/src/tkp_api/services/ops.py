"""Ops alert service stubs."""

from sqlalchemy.orm import Session


def acknowledge_alert(db: Session, *, tenant_id, alert_id: str, user_id) -> None:
    pass


def resolve_alert(db: Session, *, tenant_id, alert_id: str, user_id) -> None:
    pass
