# P2 native execution proposal boundary (source-only)

This candidate is a strict descendant of native ModelPort Final-use draft #3513
(which descends from #3510 -> #3505 -> #3500 -> #3492). It carries only a
non-authorizing Agentd proposal seam and is **not** a production cutover.

## Code ownership

- `src/native_shadow_execution.rs` accepts only `codex_execution_core::ExecutionIntent`,
  and creates a canonical, digest-bound in-memory proposal. It imports no
  Codex-specific protocol, client, thread, session, model or tool types.
- `src/shadow_execution.rs` remains the Codex compatibility bridge. It translates
  `CodexOperationIntent` exactly once, then calls the same native validation.
- The original `propose_shadow_execution_v1` signature is preserved.
- Both routes deny prior chain records, stale identities and serialized
  Final-use authority. Neither can spawn a process, write a ledger or commit
  an effect.

## Acceptance / nonclaims

These unit tests check only source-level intent and canonical digest parity.
The wider `codex-hepta-agentd` crate still embeds Codex App Server, and the
live production execution path is unchanged. The native seam does not grant a
model invocation, create Final-use, authenticate a receipt, persist a WAL, or
implement cancellation/recovery. The Rust test source was committed without
local Cargo or rustfmt execution in the available environment.

The complete P2 gate **remains open** until identical bounded task fixtures
demonstrate request, cancel, timeout, recovery, permission and failure parity
against the existing Codex App Server product host using independently
observed terminal outcomes, with no direct Codex internal types in the
selected Hepta core interfaces.

Run on the exact candidate SHA with Rust installed:

```sh
cd codex-rs
cargo fmt --all --check
cargo test -p codex-hepta-agentd native_shadow_execution
cargo test -p codex-hepta-agentd shadow_execution
cargo test -p codex-execution-core
cargo clippy -p codex-hepta-agentd -p codex-execution-core --all-targets -- -D warnings
```

Do not promote or merge based on this README or unit-test fixtures. Keep
DRAFT / HOLD_NO_GO until exact-source CI, independent observation and product
operator acceptance.
