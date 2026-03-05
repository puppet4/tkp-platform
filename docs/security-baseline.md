# Security Baseline (Phase 4)

## Scope
- Tenant isolation enforced in application layer.
- PII exposure minimized in operational outputs.
- Deletion actions require proof records.

## Minimum Controls
- Tenant-scoped authorization is mandatory for all ops endpoints.
- Sensitive fields are excluded from public runbook outputs.
- Deletion proof records include hash + signature + operator context.

## Readiness
- RLS: planned for production rollout checklist.
- Masking: active by default for ops/public views.
- Deletion proof: active via compliance APIs.
