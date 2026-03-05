# Release Checklist (Phase 4)

## Pre-Release
- Freeze change scope and confirm owner/oncall.
- Verify `test_http_api_full_workflow_with_permissions_and_coverage` passed.
- Verify SQL governance and migration replay passed.
- Confirm rollback target version is available.

## Canary Rollout
- Start with 10% traffic for 15 minutes.
- Observe ingestion failure rate, retrieval p95 latency, and zero-hit rate.
- Promote to 30%, then 100% only if all SLO checks pass.

## Rollback
- Trigger `/api/ops/release/rollouts/{rollout_id}/rollback`.
- Open/attach incident ticket and record rollback reason.
- Validate baseline metrics recover within 20 minutes.

## Post-Release
- Export audit logs and release records.
- Update runbook timeline and incident references.
