# runtime.codex operations runbook

## Required metrics

Export at least:

- admission accepted/rejected/overloaded counts;
- active and oldest unresolved native dispatch;
- Agentd runs by phase, including pre-effect-permit and entered-effect states;
- final-use claim latency, denial reason, revocation epoch/revision, and stale-head rejection;
- durable prepare, owner dispatch, provider queue, first-token, terminal, interrupt, and reconciliation latency;
- physical provider request count per operation identity;
- event lag, disconnect, duplicate correlation, and history-unavailable counts;
- ephemeral threads opened, explicitly cleaned, transport-closed, and orphan-suspected;
- quarantine count, age, disposition, signer, and resolution sequence;
- process identity mismatch, trusted-clock drift, and anti-rollback rejection;
- peak RSS, CPU time, journal fsync latency, and capacity pressure.

Never log prompts, provider credentials, signed grants, private keys, unrestricted model output, or raw cognitive memory. Use operation IDs and digests.

## Alerts

Page immediately for any duplicate physical provider request, blind replay attempt, authority/revocation rollback, process-instance mismatch, journal integrity failure, invalid state transition, or success without terminal correlation and final owner readiness.

Warn on p95/p99 threshold breach, growing unresolved age, quarantine accumulation, cleanup failure, event lag, issuer latency, reconciliation failure, or admission saturation.

## Indeterminate operations

Apply `EPHEMERAL_HISTORY_QUARANTINE.md`. The only allowed dispositions are independently confirmed terminal, independently proven absent, or abandoned without replay. A release envelope must be signed outside runtime.codex/Agentd and advance the external resolution sequence. Human judgement alone cannot mint success or retry authority.

## Capacity response

Do not solve capacity pressure by evicting unresolved operations. First stop new admission, drain known-safe work, reconcile exact operations, and scale only after the owner/store limits and p95/p99 evidence are updated. Unknown effects retain their slots by design.

## Evidence retention

Retain exact candidate SHA/tree, target profile, host/process attestations, issuer/key-custody evidence, revocation head, fault observations, logs, thresholds, receipt, artifact digest, and GitHub provenance attestation for the deployment retention period. Repository receipts never substitute for independent acceptance records.
