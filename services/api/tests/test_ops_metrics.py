from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from tkp_api.models.knowledge import IngestionJob
from tkp_api.services.ops_metrics import build_ingestion_metrics


def test_build_ingestion_metrics_aggregates_backlog_failure_and_latency():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    IngestionJob.__table__.create(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)

    tenant_id = uuid4()
    now = datetime.now(timezone.utc)

    with factory() as db:
        db.add_all(
            [
                IngestionJob(
                    tenant_id=tenant_id,
                    workspace_id=uuid4(),
                    kb_id=uuid4(),
                    document_id=uuid4(),
                    document_version_id=uuid4(),
                    idempotency_key=f"queued-{uuid4()}",
                    status="queued",
                    next_run_at=now,
                ),
                IngestionJob(
                    tenant_id=tenant_id,
                    workspace_id=uuid4(),
                    kb_id=uuid4(),
                    document_id=uuid4(),
                    document_version_id=uuid4(),
                    idempotency_key=f"retrying-{uuid4()}",
                    status="retrying",
                    next_run_at=now,
                ),
                IngestionJob(
                    tenant_id=tenant_id,
                    workspace_id=uuid4(),
                    kb_id=uuid4(),
                    document_id=uuid4(),
                    document_version_id=uuid4(),
                    idempotency_key=f"completed-{uuid4()}",
                    status="completed",
                    started_at=now - timedelta(seconds=10),
                    finished_at=now - timedelta(seconds=5),
                    next_run_at=now,
                ),
                IngestionJob(
                    tenant_id=tenant_id,
                    workspace_id=uuid4(),
                    kb_id=uuid4(),
                    document_id=uuid4(),
                    document_version_id=uuid4(),
                    idempotency_key=f"dead-{uuid4()}",
                    status="dead_letter",
                    started_at=now - timedelta(seconds=20),
                    finished_at=now - timedelta(seconds=10),
                    next_run_at=now,
                ),
                IngestionJob(
                    tenant_id=tenant_id,
                    workspace_id=uuid4(),
                    kb_id=uuid4(),
                    document_id=uuid4(),
                    document_version_id=uuid4(),
                    idempotency_key=f"processing-stale-{uuid4()}",
                    status="processing",
                    heartbeat_at=now - timedelta(minutes=10),
                    next_run_at=now,
                ),
                IngestionJob(
                    tenant_id=tenant_id,
                    workspace_id=uuid4(),
                    kb_id=uuid4(),
                    document_id=uuid4(),
                    document_version_id=uuid4(),
                    idempotency_key=f"processing-fresh-{uuid4()}",
                    status="processing",
                    heartbeat_at=now - timedelta(seconds=20),
                    next_run_at=now,
                ),
            ]
        )
        db.commit()

        metrics = build_ingestion_metrics(db, tenant_id=tenant_id, window_hours=24, stale_seconds=120)

    assert metrics["queued"] == 1
    assert metrics["retrying"] == 1
    assert metrics["processing"] == 2
    assert metrics["completed"] == 1
    assert metrics["dead_letter"] == 1
    assert metrics["backlog_total"] == 2
    assert metrics["completed_last_window"] == 1
    assert metrics["dead_letter_last_window"] == 1
    assert metrics["failure_rate_last_window"] == 0.5
    assert isinstance(metrics["avg_latency_ms_last_window"], int) and metrics["avg_latency_ms_last_window"] >= 5000
    assert isinstance(metrics["p95_latency_ms_last_window"], int) and metrics["p95_latency_ms_last_window"] >= 5000
    assert metrics["stale_processing_jobs"] == 1
