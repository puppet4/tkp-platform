"""检索评测服务。"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from tkp_api.models.knowledge import RetrievalEvalItem, RetrievalEvalRun
from tkp_api.services.ops_metrics import build_retrieval_eval_summary


def create_retrieval_eval_run(
    db: Session,
    *,
    tenant_id: UUID,
    user_id: UUID,
    name: str,
    kb_ids: list[UUID],
    top_k: int,
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    """执行评测并持久化 run/item。"""
    summary = build_retrieval_eval_summary(
        db,
        tenant_id=tenant_id,
        kb_ids=kb_ids,
        samples=samples,
        top_k=top_k,
    )
    run = RetrievalEvalRun(
        tenant_id=tenant_id,
        created_by=user_id,
        name=name.strip() or "adhoc",
        kb_ids=[str(item) for item in kb_ids],
        top_k=top_k,
        sample_total=summary["sample_total"],
        matched_total=summary["matched_total"],
        hit_at_k=summary["hit_at_k"],
        citation_coverage_rate=summary["citation_coverage_rate"],
        avg_latency_ms=summary["avg_latency_ms"],
        status="completed",
        summary_json={
            "hit_at_k": summary["hit_at_k"],
            "citation_coverage_rate": summary["citation_coverage_rate"],
        },
    )
    db.add(run)
    db.flush()

    for index, item in enumerate(summary["results"]):
        db.add(
            RetrievalEvalItem(
                run_id=run.id,
                tenant_id=tenant_id,
                sample_no=index + 1,
                query_text=item["query"],
                expected_terms=item["expected_terms"],
                matched=item["matched"],
                hit_count=item["hit_count"],
                citation_covered=item["citation_covered"],
                top_hit_score=item["top_hit_score"],
                latency_ms=item["latency_ms"],
                result_json=item,
            )
        )
    db.commit()

    return {
        "run_id": str(run.id),
        "name": run.name,
        "created_at": run.created_at,
        "sample_total": run.sample_total,
        "matched_total": run.matched_total,
        "hit_at_k": float(run.hit_at_k),
        "citation_coverage_rate": float(run.citation_coverage_rate),
        "avg_latency_ms": run.avg_latency_ms,
        "results": summary["results"],
    }


def list_retrieval_eval_runs(
    db: Session,
    *,
    tenant_id: UUID,
    limit: int = 20,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """分页查询评测运行记录。"""
    rows = db.execute(
        select(RetrievalEvalRun)
        .where(RetrievalEvalRun.tenant_id == tenant_id)
        .order_by(RetrievalEvalRun.created_at.desc())
        .offset(offset)
        .limit(limit)
    ).scalars()

    result: list[dict[str, Any]] = []
    for row in rows:
        result.append(
            {
                "run_id": str(row.id),
                "name": row.name,
                "status": row.status,
                "sample_total": int(row.sample_total),
                "matched_total": int(row.matched_total),
                "hit_at_k": float(row.hit_at_k),
                "citation_coverage_rate": float(row.citation_coverage_rate),
                "avg_latency_ms": row.avg_latency_ms,
                "created_at": row.created_at,
            }
        )
    return result


def get_retrieval_eval_run_detail(
    db: Session,
    *,
    tenant_id: UUID,
    run_id: UUID,
) -> dict[str, Any]:
    """查询单个评测运行详情。"""
    run = db.get(RetrievalEvalRun, run_id)
    if not run or run.tenant_id != tenant_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="eval run not found")

    items = db.execute(
        select(RetrievalEvalItem)
        .where(RetrievalEvalItem.tenant_id == tenant_id, RetrievalEvalItem.run_id == run_id)
        .order_by(RetrievalEvalItem.sample_no.asc())
    ).scalars()
    results = [dict(item.result_json) for item in items]
    return {
        "run_id": str(run.id),
        "name": run.name,
        "status": run.status,
        "sample_total": int(run.sample_total),
        "matched_total": int(run.matched_total),
        "hit_at_k": float(run.hit_at_k),
        "citation_coverage_rate": float(run.citation_coverage_rate),
        "avg_latency_ms": run.avg_latency_ms,
        "created_at": run.created_at,
        "results": results,
    }


def compare_retrieval_eval_runs(
    db: Session,
    *,
    tenant_id: UUID,
    baseline_run_id: UUID,
    current_run_id: UUID,
) -> dict[str, Any]:
    """对比两次评测结果。"""
    baseline = get_retrieval_eval_run_detail(db, tenant_id=tenant_id, run_id=baseline_run_id)
    current = get_retrieval_eval_run_detail(db, tenant_id=tenant_id, run_id=current_run_id)

    def _delta(current_value: float | int | None, baseline_value: float | int | None) -> float | None:
        if current_value is None or baseline_value is None:
            return None
        return round(float(current_value) - float(baseline_value), 6)

    return {
        "tenant_id": str(tenant_id),
        "baseline_run_id": str(baseline_run_id),
        "current_run_id": str(current_run_id),
        "delta_hit_at_k": _delta(current["hit_at_k"], baseline["hit_at_k"]),
        "delta_citation_coverage_rate": _delta(current["citation_coverage_rate"], baseline["citation_coverage_rate"]),
        "delta_avg_latency_ms": _delta(current["avg_latency_ms"], baseline["avg_latency_ms"]),
        "baseline": baseline,
        "current": current,
        "improved": (
            (current["hit_at_k"] >= baseline["hit_at_k"])
            and (current["citation_coverage_rate"] >= baseline["citation_coverage_rate"])
        ),
    }
