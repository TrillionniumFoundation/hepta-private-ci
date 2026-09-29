# Recovery and qualification implementation status — 2026-09-28

This change continues PR #998 on `codex/secrets-heptabao-convergence`. It is not
a declaration that all four remediation phases are complete. The predecessor
contains the V4 consumption saga and manifest generator; those are retained, not
claimed as newly implemented by this change.

## Source changes in this increment

The registered consumer and reconciler share an operation-level execution guard.
A durable AuthBus non-admission fence serializes with reserve under the same
SQLite write transaction, includes archived identities, binds the effect digest
and participates in checkpoint publication. Missing reservation SELECT results
are no longer sufficient to close an operation. See `ADMISSION_FENCE_V1.md`.

Native receipt verification rejects empty or duplicate gates, failed or missing
exit statuses, mismatched candidate identities and unsupported authority claims.
It recomputes retained log digests and requires a positive executed-test count
for the Rust test and AuthBus-schema gates. This is evidence-format validation,
not an independently signed execution attestation. The provider digest remains
explicitly historical fixed-provider probe evidence, not current dynamic E2E.

The recovery bootstrap is removed after normal Rust/SQL source files are committed.
The verification workflow is read-only: it does not apply opaque payloads, push
source changes or bypass failure statuses. A queued predecessor job cannot
fast-forward over these source changes.

## Executed checks

Twelve Python receipt/attestation tests passed. Eight tests executed the actual
AuthBus SQL migrations in WAL/FULL SQLite, including a separate process exiting
before and after COMMIT, hot/archive reservation conflicts, write-lock exclusion,
rollback, immutable seals and checkpoint dirtiness. Module-manifest projection
verification passed. These are not Rust, HTTPS, product-process or power-loss
qualification results.

Six additional Rust regression tests are present (four AuthBus admission tests
and two operation-guard tests), but were not executed in the editing environment:
Rust/cargo/rustfmt were unavailable and toolchain network resolution failed.
GitHub native verification had no completed result when this status was written.
Native formatting, strict Clippy, exact-head and synthetic-merge qualification
therefore remain open. Source presence is not a passing gate.

## Remaining work

Phase 1 source now contains a 26-cut Unix SIGKILL/reopen matrix spanning claim,
AuthBus publication, provider response, consumer and settlement boundaries.
Pre-reserve invalid admission is rejected before a durable claim, and the
provider-error branch no longer attempts an invalid terminal transition from
`Claimed`. This source still requires exact-head and synthetic-merge native
execution before the matrix can be reported as passed.

Post-dispatch records without a response receipt still need a real provider-side
observer or another qualified original-operation terminal-evidence path. They
remain explicit pending states, retain quota and are never redispatched or
silently refunded.

Phase 2 still needs exact-candidate native logs, per-execution toolchain binding
and independently trusted attestation. Documentation projections and test-count
validation do not establish those facts.

Phase 3 remains incomplete: the actual Bao owner is the bounded schema-4 JSON
owner. It now exposes complete-operation and commit cost metrics, actionable
recovery/capacity diagnostics and proof-preserving schema-3 migration. The
unapplied/truncated phase-3 staging payload is not a SQLite production writer.
Separate operation/lease/consumption tables, event history, CAS, a fair recovery
queue, archive, anti-rollback service, retention and nonblocking host integration
still need complete implementation and native qualification.

Phase 4 remains incomplete: the supported fixed-provider slice is exact KV-v2
read-only. Generic dynamic issue/lookup/renew/revoke/expiry E2E is not established.
No normal Agentd/App Server caller, protected production trust-service bootstrap,
key-rotation deployment or deployed metrics export is established by this increment.
Provider mutation, activation, acceptance and release flags remain false.
