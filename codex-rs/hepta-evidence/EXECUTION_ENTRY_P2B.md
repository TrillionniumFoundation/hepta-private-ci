# P2b: deny-only final-use entry audit

**DENY_ALL.** This branch stacks on P2a #1967. It deliberately does not attempt a physical Codex Exec Server call, create a signed Final-use verifier/token, or turn SQLite preparation into tool permission.

Original HeptaEvidenceStore provides audit_execution_effect_entry_denied_v1, which validates original request bytes and reads the exact P2a persisted envelope. Every returned verdict is a denial: no original preparation, reconciliation needed after unknown state, or no independent Final-use/physical owner when preparation matches.

The audit returns no dispatch/retry/permit/complete method, does not write a new ledger, and can run on the original read-only Evidence connection after a cold restart. The same-operation cross-generation/payload mismatch rejects instead of returning an affirmative verdict. Existing model-only App Server turn/start remains unrelated to tool grants.

Five original SQLite integration unit tests cover missing/recorded/quarantined/stale/read-only states. Native Rustfmt, locked Cargo, strict Clippy, full owner tests, CI on exact source plus prospective merge, signed issuer, trustworthy revocation distribution, real Codex execution, crash/restart and target-host measurements are separate **unpassed** gates. No production caller is added.

Next safe integration: once P1 and P2a native CI are green, implement on the existing Agentd/Operations effect owner an exact physical-wire operation prepare; acquire independently signed Final-use for the physical tool operation and validate its live epoch/nonce/revocation immediately before effect entry; persist send and reconcile indeterminate responses through original provider status. Do not use a proposed FinalUseBinding, payload hash, boolean, or caller assertion as authorization. No Cell direct IPC bypass.
