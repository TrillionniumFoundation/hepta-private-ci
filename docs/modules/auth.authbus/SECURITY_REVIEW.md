# auth.authbus independent security review

Review date: 2026-09-27

Reviewer role: independent repository security referee.

## Scope

Opaque issuer registrations, durable issuer lookup, authority writer visibility, owner fencing, checkpoint publication, restart/expiration reconciliation, qualification coverage, product callers and operational documentation.

## Findings disposition

- Caller-constructible issuer key material: addressed in source by sealed handles and persisted registry loaders; exact-head compile/API inventory remains the acceptance proof.
- Settlement stale/revoked handle: addressed by same-transaction durable issuer reload.
- Public raw authority writer: addressed by crate-private exposure; closed-world inventory required.
- Multi-owner checkpoint race: addressed by process-lifetime independent SQLite owner fence; dual-process and kill tests required.
- Leaked expired reservations: addressed by bounded sweep and authority-worker contract; product scheduling/telemetry required.
- Replay-only qualification: replaced by an authority-boundary case inventory; all cases and product execution must run on the unchanged candidate.
- Documentation and operations gap: addressed by the module threat, operations, SLO, recovery, rotation, schema and deployment contracts in this directory.

## Decision

Source remediation is **conditionally acceptable for continued qualification**. Production activation remains blocked until the exact candidate has terminal-success focused tests, all-target build, strict lint, closed-world API inventory, source-head and synthetic-merge execution receipts, plus target-host ENOSPC/power-loss and KMS/operator acceptance evidence. Cancellation, skipped jobs, static-only checks or evidence from another SHA do not satisfy this decision.
