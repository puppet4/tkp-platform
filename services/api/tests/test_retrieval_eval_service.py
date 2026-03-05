from uuid import UUID, uuid4

from pgvector.sqlalchemy import Vector
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from tkp_api.models.knowledge import RetrievalEvalItem, RetrievalEvalRun
from tkp_api.services import retrieval_eval as retrieval_eval_service


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type_, _compiler, **_kwargs):
    return "JSON"


@compiles(Vector, "sqlite")
def _compile_vector_sqlite(_type_, _compiler, **_kwargs):
    return "BLOB"


def test_retrieval_eval_run_persistence_and_compare(monkeypatch):
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    RetrievalEvalRun.__table__.create(engine)
    RetrievalEvalItem.__table__.create(engine)
    db_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, class_=Session)

    tenant_id = uuid4()
    user_id = uuid4()
    kb_id = uuid4()
    step = {"value": 0}

    def fake_summary(*_args, **_kwargs):
        step["value"] += 1
        if step["value"] == 1:
            return {
                "tenant_id": str(tenant_id),
                "sample_total": 1,
                "matched_total": 1,
                "hit_at_k": 1.0,
                "citation_coverage_rate": 1.0,
                "avg_latency_ms": 90,
                "results": [
                    {
                        "query": "退款流程是什么",
                        "expected_terms": ["退款"],
                        "matched": True,
                        "hit_count": 2,
                        "citation_covered": True,
                        "top_hit_score": 950,
                        "latency_ms": 90,
                    }
                ],
            }
        return {
            "tenant_id": str(tenant_id),
            "sample_total": 1,
            "matched_total": 0,
            "hit_at_k": 0.0,
            "citation_coverage_rate": 0.0,
            "avg_latency_ms": 180,
            "results": [
                {
                    "query": "工单怎么提交",
                    "expected_terms": ["工单"],
                    "matched": False,
                    "hit_count": 0,
                    "citation_covered": False,
                    "top_hit_score": None,
                    "latency_ms": 180,
                }
            ],
        }

    monkeypatch.setattr(retrieval_eval_service, "build_retrieval_eval_summary", fake_summary)

    with db_factory() as db:
        baseline = retrieval_eval_service.create_retrieval_eval_run(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="baseline",
            kb_ids=[kb_id],
            top_k=5,
            samples=[{"query": "退款流程是什么", "expected_terms": ["退款"]}],
        )
        current = retrieval_eval_service.create_retrieval_eval_run(
            db,
            tenant_id=tenant_id,
            user_id=user_id,
            name="current",
            kb_ids=[kb_id],
            top_k=5,
            samples=[{"query": "工单怎么提交", "expected_terms": ["工单"]}],
        )
        baseline_run_id = UUID(baseline["run_id"])
        current_run_id = UUID(current["run_id"])

        run_list = retrieval_eval_service.list_retrieval_eval_runs(db, tenant_id=tenant_id, limit=10, offset=0)
        assert len(run_list) == 2

        baseline_detail = retrieval_eval_service.get_retrieval_eval_run_detail(
            db,
            tenant_id=tenant_id,
            run_id=baseline_run_id,
        )
        assert baseline_detail["name"] == "baseline"
        assert baseline_detail["sample_total"] == 1
        assert isinstance(baseline_detail["results"], list) and len(baseline_detail["results"]) == 1

        diff = retrieval_eval_service.compare_retrieval_eval_runs(
            db,
            tenant_id=tenant_id,
            baseline_run_id=baseline_run_id,
            current_run_id=current_run_id,
        )
        assert diff["baseline_run_id"] == str(baseline_run_id)
        assert diff["current_run_id"] == str(current_run_id)
        assert diff["delta_hit_at_k"] == -1.0
        assert diff["delta_citation_coverage_rate"] == -1.0
        assert diff["improved"] is False
