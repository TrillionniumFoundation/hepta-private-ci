# P1: Backend-neutral Execution Envelope (no effect authority)

**Status: CONTRACT_ONLY / DENY_ALL.** There is no new executable, listener, Executor, writer, approval issuer, tool grant, production calling path, runnable sandbox, or selected topology in this change. The existing Hepta owners remain authoritative.

## Exact baseline and related source

- Developed from [Hepta main at 78fdb0cf8537e3a84fc6e0a849707559c80881e8](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/78fdb0cf8537e3a84fc6e0a849707559c80881e8), without cherry-picking unqualified Cell Split or shared-Encoder draft branches.
- B0 independent synthetic-transport probe: [PR #1947](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1947). Its Python numbers are **not** Codex/Hepta native execution results.
- Actual Codex reference: the [0.162.1 release](https://github.com/openai/codex/releases/tag/rust-v0.162.1), which already separates App Server client semantics from the lower-level Exec Server. These two protocols are **not** interchangeable.
- Existing owners to reuse: `codex-hepta-contracts::FinalUseBinding` and the original kernel signer/verifier; `ProviderEffectIntent` and original provider-effect owner journal; `codex-hepta-infer-worker-host` model-only App Server path; Agentd/Supervisor/Evidence/CNS original durable owners.
- Cell/organ learning, NDU and topology mutation cannot generate final-use authority.

## Implemented additive contract

`src/execution_contract_v1.rs` exports:

- `ExecutionIntentV1`: strict schema (version 1); bounded ASCII identity; target kind explicitly distinguishes `codex_app_server_model_only` from `codex_exec_server_process`; exact subject/scope/destination; nonzero generation, fence and authority epoch; payload digest/length; deadline and maximum wall budget.
- `ExecutionIntentV1::verify_payload`: verifies the exact provided bytes against length/digest before a future owner proposes external execution.
- `ExecutionIntentV1::binding_proposal`: canonical SHA-256, domain-separated and length-delimited binding over **all** mutable request fields, plus separate subject/scope/destination/generation/fence/epoch binding. Returns a standard **unsigned** `FinalUseBinding` value, not a `VerifiedUseToken`.
- `ExecutionObservationV1`: strict typed, caller-supplied claims with exact operation/request/generation/fence/epoch match. It cannot be used to approve a retry or declare a tool effect terminal.
- `plan_execution_reconciliation_v1`: returns only `LookupOriginalOperation` or `VerifyOriginalReceipt`. There is **no** API returning Permit/Retry/Completed. Even `NotSentClaimed` must be corroborated by original process-held pre-effect abort proof or actual owner status. Terminal digest is not signature/authenticated receipt.

Public structs and JSON are intentionally not capabilities. An untrusted sender can forge them, so independently verify selected owner provenance, original signed grant, trusted time, revocation frontier, durable intent, external effect entry, and the provider's **original** receipt before performing or closing any effect. Hashes prove equality only, not authenticity.

This contract **does not** replace the existing `ProviderEffectCoordinator`, its journal, or the existing `FinalUseAuthority`. No second ledger/state store is created.

## Tests and exact commands

From repository root:

```sh
python3 scripts/verify_cargo_lock.py
cd codex-rs
cargo fmt --all -- --check
cargo test --locked -p codex-hepta-contracts --lib execution_contract_v1 -- --nocapture
cargo clippy --locked -p codex-hepta-contracts --all-targets -- -D warnings
```

Unit tests cover strict deserialization, no-authority target separation, deterministic payload/binding identity, every changed sensitive field affecting the digest, cross-scope/stale generation/epoch rejection, zero/over-budget guards, receipt spoofing, and forced reconciliation after uncertain or claimed terminal outcomes.

**Note:** A passing unit test is never proof of a live final-use signer, real Codex Exec Server, external sandbox, independent owner E2E, or target host deployment. Rust toolchain and hosted CI must run on this exact SHA; local source inspection cannot substitute for those receipts.

## Strict follow-up before any real execution

1. Select the **existing Agentd/Operations owner** and bind its original durable request/outbox/nonce/final-use *and* actual original provider status to these types. Do not create a second writer, attach an unverified `FinalUseBinding` as a bearer token or let a Cell issue Exec Server RPC directly.
2. Implement separate adapters for model-only App Server `turn/start` (preserving original thread/turn identity and no replay) and explicit sandboxed tool/process Exec Server (separate effect final-use). A model-only grant can never be upgraded into tool execution authority.
3. Compare real pinned, compiled Codex on target host using identical effect ceilings: in-process where appropriate, persistent local Exec Server, remote Exec Server and full cold-start control. Measure CPU/RSS/queueing/p95/p99/WAL/recovery and count installed Cell IDs separately from physically active calls.
4. Close outstanding Cell Split CNS/Control signed cutover, per-owner generation fencing and independent NDU future-window/negative-transfer gates **before** promotion of a self-mutating topology.

No new production route, release authority, CI skip or model capability claim is introduced.
