# Operations Runbook (Phase 4)

## Oncall Model
- 24x7 weekly rotation.
- Mandatory handoff notes each shift.
- Critical alerts fan out via webhook + phone bridge.

## Playbooks
- INGESTION_DEAD_LETTER: retry/dead-letter triage, target 10 minutes.
- RETRIEVAL_ZERO_HIT: KB readiness + query strategy check, target 15 minutes.
- RELEASE_ROLLBACK: rollback execution + verification, target 20 minutes.

## Escalation
- T+10 min unresolved: escalate to platform owner.
- T+30 min unresolved critical: initiate incident command.
- T+60 min unresolved: customer communication update required.
