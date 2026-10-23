## Why

Objective submission needs crash-durable ownership before transport I/O. UI-local state cannot safely deduplicate a retained request after restart, and separate snapshot/precheck/append calls permit conflicting observations. A locally committed observation also does not prove the independently durable current-cut ACK succeeded.

## Changes

- Add the typed Objective sender domain to the original CognitiveStore/ProductionDurableWriter, with exact raw request and full identity, original schema/state-digest validation, one-use owner-bound send permission, durable observation/local cancellation and bounded restart enumeration. No new database, writer, UI ledger or FinalUse lifecycle is introduced.
- Add `retain_observation_checked`: semantic check and append share the original SQLite write transaction; concurrent conflicting publications fail closed and exact retries remain idempotent.
- Add `snapshot_acknowledged`: hold the original write transaction through the independent current-cut ACK and live validation before returning the recovered projection. It grants no new send/cancel permission.
- Add the original Agentd trusted-host bridge and wire-digest tests, plus source-specific complete execution evidence.

## Validation

| Immutable source stage | Original `codex-hepta-memory --lib` result |
| --- | --- |
| `4869044893f114bcb1d7235830c7313638df8254` | 317 passed, 8 skipped |
| `7f86518d7f179c068d60c6cf26d41710d3540579` | 319 passed, 8 skipped |
| `db91f9ec316ba1472e7adf97f8415949de012469` | 322 passed, 8 skipped |

The original complete workspace and lock are retained: 9,111 original blobs plus 19 recorded candidate paths, 193 effective members, no unrecorded source difference before/after the gates. Tests use original `just test --locked --cargo-profile dev-small --build-jobs 1 --test-threads 1 -p codex-hepta-memory --lib`; this is not a claim that all workspace packages were tested. Counts belong to distinct source stages and are not interchangeable. Final executable Rust hashes match the final commit; the separately bound docs-only update was not part of the on-disk test overlay.

Original `just fmt --check` including the final post-Clippy check passes. Original `just fix -p codex-hepta-memory --locked --profile dev-small --lib` exits zero, with 28 lib-test warnings and 2 lib duplicate warnings (plus an upstream PTY warning), not warning-free qualification. Full stdout/stderr, JUnit, receipts, runners and exact source manifests are retained in `results/integration/2026-10-23-objective-sender-final/`; the frozen 317 evidence remains in its original prefix.

## Draft boundaries

The three original Agentd bridge tests remain unexecuted. A real independently authenticated/fenced/durable production checkpoint provider is still required and unimplemented here; no default is supplied. The change does not qualify the Desktop adapter, real model execution, native guest or hardware. Existing protected current-cut and schema recovery remain mandatory; legacy fresh test genesis is not a production upgrade path. Local cancellation is not original RunCancel, and DB current-cut is not the Objective publication anchor. Tokio deadlines are cooperative and require bounded nonblocking checkpoint/verifier/clock/check callbacks.
