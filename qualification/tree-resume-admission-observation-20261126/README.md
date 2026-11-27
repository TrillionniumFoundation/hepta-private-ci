# Tree-resume fixture admission observation

## Original failure and limits

The retained macOS Intel Core unit-test shard at source
`be271ddfa2a2d519a44112e4f176d2d8c3499c25` ran 309 cases: 308 passed and
`agent::control::tests::resume_agent_from_rollout_does_not_reopen_v2_descendants`
failed at the existing five-second admission wait. Its original log is 30,001
bytes, SHA-256
`44e669156d761e9aa44cd2be625c42f9a0152be7d81cb5b768dc528cbd0d6168`.
This is one retained failed shard, not the entire Core target outcome.

The helper is called for several independently created tree nodes. Its original
failure did not identify which node or turn was being aborted, or whether a
start, abort, or finish owner retained the admission fence. The normal abort API
can return while an existing owner continues cleanup. An owner that fails its
watchdog deliberately leaves admission closed. These source facts do not prove
which path caused the recorded failure.

## Diagnostic-only change

Before the original abort, the test makes one `try_lock` attempt and copies only
the observed turn ID. It retains no task, authority, execution guard, or lock
across the abort or wait. The original abort call, five-second timeout, yield
loop, history injection, persistence, and all tree/resume assertions remain.

Only after the original wait fails does the helper create the existing
`RecoveryDiagnostics` observer and take one snapshot. The failure includes the
fixture marker, pre-abort capture status, optional observed turn ID, and the
existing bounded pending-owner observations. The observer is registered after
failure: its rejection list cannot describe earlier events, and its authority
capture is also a post-failure observation. Busy locks, missing turn IDs, absent
registry slots, and unmatched turns remain inconclusive. The snapshot is not
atomic or complete and does not confer recovery authority.

No production code, watchdog, timeout, retry, thread count, permission, or
dependency changes. Formatting and source invariants are checked; no new Rust
build or native test has run for this candidate. It provides a more useful
failure report and does not close the original admission failure.
