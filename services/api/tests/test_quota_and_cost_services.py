from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from tkp_api.models.agent import AgentRun
from tkp_api.models.audit import AuditLog
from tkp_api.models.conversation import Message
from tkp_api.models.enums import MessageRole
from tkp_api.models.knowledge import RetrievalLog
from tkp_api.models.quota import QuotaPolicy
from tkp_api.services.cost import build_tenant_cost_summary
from tkp_api.services.quota import QuotaMetric, enforce_quota, upsert_quota_policy


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type_, _compiler, **_kwargs):
    return "JSON"


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(_type_, _compiler, **_kwargs):
    return "BLOB"


@compiles(INET, "sqlite")
def _compile_inet_sqlite(_type_, _compiler, **_kwargs):
    return "TEXT"


def test_quota_policy_upsert_and_enforce_records_alert():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    QuotaPolicy.__table__.create(engine)
    RetrievalLog.__table__.create(engine)
    AuditLog.__table__.create(engine)
    db_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)

    tenant_id = uuid4()
    user_id = uuid4()

    with db_factory() as db:
        created = upsert_quota_policy(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            metric_code=QuotaMetric.RETRIEVAL_REQUESTS.value,
            scope_type="tenant",
            scope_id=None,
            limit_value=0,
            window_minutes=60,
            enabled=True,
        )
        assert created["metric_code"] == QuotaMetric.RETRIEVAL_REQUESTS.value

        with pytest.raises(HTTPException) as exc_info:
            enforce_quota(
                db,
                tenant_id=tenant_id,
                metric_code=QuotaMetric.RETRIEVAL_REQUESTS.value,
                projected_increment=1,
                actor_user_id=user_id,
            )

        assert exc_info.value.status_code == 429
        assert isinstance(exc_info.value.detail, dict)
        assert exc_info.value.detail.get("code") == "QUOTA_EXCEEDED"

        events = db.execute(select(AuditLog).where(AuditLog.action == "quota.exceeded")).scalars().all()
        assert len(events) == 1
        payload = events[0].after_json or {}
        assert payload.get("metric_code") == QuotaMetric.RETRIEVAL_REQUESTS.value


def test_build_tenant_cost_summary_aggregates_metrics():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    RetrievalLog.__table__.create(engine)
    Message.__table__.create(engine)
    AgentRun.__table__.create(engine)
    db_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)

    tenant_id = uuid4()

    with db_factory() as db:
        db.add(
            RetrievalLog(
                tenant_id=tenant_id,
                user_id=uuid4(),
                query_text="退款流程",
                kb_ids=[],
                top_k=5,
                filter_json={},
                result_chunks=[],
                latency_ms=120,
            )
        )
        db.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=uuid4(),
                role=MessageRole.ASSISTANT,
                content="answer",
                citations=[],
                usage={"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
            )
        )
        db.add(
            AgentRun(
                tenant_id=tenant_id,
                user_id=uuid4(),
                conversation_id=None,
                plan_json={},
                tool_calls=[],
                status="completed",
                cost=0.125,
                started_at=datetime.now(timezone.utc),
                finished_at=datetime.now(timezone.utc),
            )
        )
        db.commit()

        summary = build_tenant_cost_summary(db, tenant_id=tenant_id, window_hours=24)

    assert summary["retrieval_request_total"] == 1
    assert summary["chat_completion_total"] == 1
    assert summary["prompt_tokens_total"] == 120
    assert summary["completion_tokens_total"] == 80
    assert summary["total_tokens"] == 200
    assert summary["agent_run_total"] == 1
    assert summary["agent_cost_total"] == 0.125
    assert summary["estimated_total_cost"] >= 0.125
