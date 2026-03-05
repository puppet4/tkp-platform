from datetime import datetime, timezone
from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from tkp_api.models.agent import AgentRun
from tkp_api.models.conversation import Conversation, Message
from tkp_api.models.enums import IngestionJobStatus, MessageRole
from tkp_api.models.knowledge import Document, IngestionJob, RetrievalLog
from tkp_api.models.ops import OpsAlertWebhook, OpsDeletionProof, OpsIncidentTicket, OpsReleaseRollout
from tkp_api.models.tenant import User
from tkp_api.models.workspace import Workspace
from tkp_api.services.ops_center import (
    build_cost_leaderboard,
    build_incident_diagnosis,
    build_ops_overview,
    build_security_baseline,
    build_tenant_health,
    create_deletion_proof,
    create_incident_ticket,
    create_release_rollout,
    dispatch_alerts,
    get_public_sla_spec,
    get_runbook_summary,
    list_alert_webhooks,
    list_deletion_proofs,
    list_incident_tickets,
    list_release_rollouts,
    rollback_release_rollout,
    update_incident_ticket,
    upsert_alert_webhook,
)


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type_, _compiler, **_kwargs):
    return "JSON"


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(_type_, _compiler, **_kwargs):
    return "BLOB"


def _create_tables(engine):
    User.__table__.create(engine)
    Workspace.__table__.create(engine)
    Document.__table__.create(engine)
    IngestionJob.__table__.create(engine)
    RetrievalLog.__table__.create(engine)
    Conversation.__table__.create(engine)
    Message.__table__.create(engine)
    AgentRun.__table__.create(engine)
    OpsIncidentTicket.__table__.create(engine)
    OpsAlertWebhook.__table__.create(engine)
    OpsReleaseRollout.__table__.create(engine)
    OpsDeletionProof.__table__.create(engine)


def test_ops_phase3_diagnosis_ticket_and_webhook_flow():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    _create_tables(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)

    tenant_id = uuid4()
    user_id = uuid4()
    workspace_id = uuid4()
    document_id = uuid4()
    now = datetime.now(timezone.utc)

    with factory() as db:
        db.add(User(id=user_id, email="owner@example.com", display_name="Owner", external_subject="owner-sub"))
        db.add(
            Workspace(
                id=workspace_id,
                tenant_id=tenant_id,
                name="WS One",
                slug="ws-one",
                description="phase3",
            )
        )
        db.add(
            Document(
                id=document_id,
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                kb_id=uuid4(),
                title="doc",
                source_type="upload",
                status="ready",
            )
        )
        db.add(
            IngestionJob(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                kb_id=uuid4(),
                document_id=document_id,
                document_version_id=uuid4(),
                idempotency_key=f"dead-{uuid4()}",
                status=IngestionJobStatus.DEAD_LETTER,
                next_run_at=now,
                finished_at=now,
                error="parse failed",
            )
        )
        db.add(
            RetrievalLog(
                tenant_id=tenant_id,
                user_id=user_id,
                query_text="unknown",
                kb_ids=[],
                top_k=5,
                filter_json={},
                result_chunks=[],
                latency_ms=150,
            )
        )
        db.commit()

        diagnosis = build_incident_diagnosis(db, tenant_id=tenant_id, window_hours=24)
        assert isinstance(diagnosis, list) and len(diagnosis) >= 1
        assert any(item["source_code"] in {"INGESTION_DEAD_LETTER", "INGESTION_FAILURE_RATE"} for item in diagnosis)

        created = create_incident_ticket(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            source_code=diagnosis[0]["source_code"],
            severity=diagnosis[0]["severity"],
            title=diagnosis[0]["title"],
            summary=diagnosis[0]["summary"],
            diagnosis={"suggestion": diagnosis[0]["suggestion"]},
            context=diagnosis[0]["context"],
        )
        assert created["status"] == "open"

        listed = list_incident_tickets(db, tenant_id=tenant_id, limit=20, offset=0)
        assert len(listed) == 1
        assert listed[0]["ticket_id"] == created["ticket_id"]

        updated = update_incident_ticket(
            db,
            tenant_id=tenant_id,
            ticket_id=uuid4(),
            status="resolved",
            assignee_user_id=user_id,
            resolution_note="handled",
        )
        assert updated is None

        resolved = update_incident_ticket(
            db,
            tenant_id=tenant_id,
            ticket_id=UUID(created["ticket_id"]),
            status="resolved",
            assignee_user_id=user_id,
            resolution_note="handled",
        )
        assert resolved is not None
        assert resolved["status"] == "resolved"
        assert resolved["resolved_at"]

        webhook = upsert_alert_webhook(
            db,
            tenant_id=tenant_id,
            name="default",
            url="https://example.invalid/webhook",
            secret="sec",
            enabled=True,
            event_types=["ingestion.dead_letter"],
            timeout_seconds=3,
        )
        assert webhook["name"] == "default"

        webhook_list = list_alert_webhooks(db, tenant_id=tenant_id)
        assert len(webhook_list) == 1

        dispatch_result = dispatch_alerts(
            db,
            tenant_id=tenant_id,
            event_type="ingestion.dead_letter",
            severity="critical",
            title="dead letter",
            message="job failed",
            attributes={"count": 1},
            dry_run=True,
        )
        assert dispatch_result["dry_run"] is True
        assert dispatch_result["matched_webhook_total"] == 1

        overview = build_ops_overview(db, tenant_id=tenant_id, window_hours=24)
        assert overview["incident_open_total"] >= 0
        assert overview["webhook_enabled_total"] == 1

        health = build_tenant_health(db, tenant_id=tenant_id, window_hours=24)
        assert len(health) == 1
        assert health[0]["workspace_id"] == str(workspace_id)


def test_ops_phase3_cost_leaderboard_should_rank_by_estimated_cost():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    _create_tables(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)

    tenant_id = uuid4()
    user_a = uuid4()
    user_b = uuid4()
    conversation_id = uuid4()

    with factory() as db:
        db.add(User(id=user_a, email="a@example.com", display_name="User A", external_subject="user-a"))
        db.add(User(id=user_b, email="b@example.com", display_name="User B", external_subject="user-b"))
        db.add(Conversation(id=conversation_id, tenant_id=tenant_id, user_id=user_a, title="c1", kb_scope={}))
        db.add(
            Message(
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content="answer",
                citations=[],
                usage={"prompt_tokens": 1000, "completion_tokens": 500, "total_tokens": 1500},
            )
        )
        db.add(
            RetrievalLog(
                tenant_id=tenant_id,
                user_id=user_a,
                query_text="q1",
                kb_ids=[],
                top_k=5,
                filter_json={},
                result_chunks=[],
                latency_ms=120,
            )
        )
        db.add(
            AgentRun(
                tenant_id=tenant_id,
                user_id=user_b,
                conversation_id=None,
                plan_json={},
                tool_calls=[],
                status="completed",
                cost=0.5,
            )
        )
        db.commit()

        ranked = build_cost_leaderboard(db, tenant_id=tenant_id, window_hours=24, limit=10)

    assert len(ranked) == 2
    assert ranked[0]["estimated_total_cost"] >= ranked[1]["estimated_total_cost"]


def test_ops_phase4_release_and_compliance_flow():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    _create_tables(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)

    tenant_id = uuid4()
    user_id = uuid4()

    with factory() as db:
        release = create_release_rollout(
            db,
            tenant_id=tenant_id,
            approved_by=user_id,
            version="v1.2.3",
            strategy="canary",
            risk_level="medium",
            canary_percent=10,
            scope={"service": "api"},
            note="phase4 release",
        )
        assert release["status"] == "running"

        release_list = list_release_rollouts(db, tenant_id=tenant_id, limit=20, offset=0)
        assert len(release_list) == 1

        rollback_before, rollback = rollback_release_rollout(
            db,
            tenant_id=tenant_id,
            approved_by=user_id,
            rollout_id=UUID(release["rollout_id"]),
            reason="rollback test",
        )
        assert rollback_before is not None
        assert rollback is not None
        assert rollback["rollback_of"] == release["rollout_id"]

        proof = create_deletion_proof(
            db,
            tenant_id=tenant_id,
            deleted_by=user_id,
            resource_type="document",
            resource_id=str(uuid4()),
            ticket_id=None,
            payload={"reason": "gdpr"},
        )
        assert proof["resource_type"] == "document"
        assert proof["subject_hash"]
        assert proof["signature"]

        proofs = list_deletion_proofs(db, tenant_id=tenant_id, limit=20, offset=0)
        assert len(proofs) == 1

        baseline = build_security_baseline(db, tenant_id=tenant_id)
        assert baseline["overall_status"] in {"pass", "warn"}
        assert isinstance(baseline["checks"], list) and len(baseline["checks"]) >= 3

        sla = get_public_sla_spec()
        assert "availability_sla" in sla
        runbook = get_runbook_summary()
        assert isinstance(runbook.get("documents"), list) and len(runbook["documents"]) >= 1
