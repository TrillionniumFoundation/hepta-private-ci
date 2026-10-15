# P2a: original Evidence-owner durable execution preparation

**Status: PREPARE_ONLY / DENY_ALL / Draft.** This is a source-level, opt-in SQLite preparation seam; no Agentd caller, Codex Exec Server, tool execution, final-use token, original external terminal effect, CNS route cutover, independent operator acceptance, or production activation is introduced.

## Exact dependency and ownership

This branch stacks on the exact unmerged P1 source at fe5ab64f6b609e7c2cbfcf12352ff637fb2dc20f from [PR #1957](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1957); the canonical main parent is 78fdb0cf8537e3a84fc6e0a849707559c80881e8. It changes only the existing codex-hepta-evidence crate plus an isolated source/merge CI workflow. P1 supplies the versioned ExecutionIntentV1 and unsigned FinalUseBinding proposal. B0 [PR #1947](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1947) is an independent synthetic Python IPC cost experiment, not an execution or quality acceptance gate.

**Do not create another SQLite database, runtime owner or permission issuer.** The original HeptaEvidenceStore already provides a BEGIN IMMEDIATE provider-effect-intent transaction, exact-key idempotent retry and conflict rejection, original row readback, durable reopen and quarantine.

## Implemented

- HeptaEvidenceStore::prepare_execution_intent_v1 takes one P1 intent and the exact original payload bytes. It validates the original bytes, constructs a stable logical occurrence key, and appends **one non-executing control-envelope intent** through the existing Evidence BEGIN IMMEDIATE transaction. It then reads back that original row. It has no physical effect boundary.
- Occurrence key is domain-separated under hepta.execution.prepare-only.v1 and binds subject, scope, logical operation ID. Target, generation, fence, authority epoch, actual payload digest/length, deadline and resource budget belong to the *same immutable occurrence envelope*. Changing any of them reuses the same key with different content and fails as an idempotency conflict. Separate subjects/scopes remain separate identities.
- Original provider-effect payload_sha256 in this reserved namespace hashes the *serialized control envelope*, **not** the raw tool payload. The raw tool payload is independently checked through P1. No future executor may treat this reserved provider-effect payload digest as a physical tool call identity. A real Exec Server integration needs its own exact actual wire payload and separately verified final-use binding before effect entry.
- ExecutionPreparationReadbackStatusV1::RecordedOnly means only SQLite persisted the envelope. It is not a grant, send permit, provider response, or tool success. Absent and OriginalOwnerReconciliationRequired are explicit non-success outcomes. Any stored ACK/uncertainty for this namespace forces read-only original-owner reconciliation rather than retrying.
- No new schema migration, signing key, cache, WAL, dispatcher, background worker, implicit adapter capability, unbounded queue, or SDK route was added. The new API shares the original Evidence store writer and transaction policy.
- The failure between commit and acknowledgement is safe to *re-present for readback*: an unchanged request becomes AlreadyPresent. No callback here crosses an external tool boundary, so this is not a physical effect retry guarantee. A process crash after a genuine physical effect is separately unknown and may only be reconciled against the original provider/owner facts.

## Local and hosted qualification

Run at the exact P2a source commit, *and* at the prospective merge with the stacked P1 branch:

```sh
python3 scripts/verify_cargo_lock.py
cd codex-rs
cargo fmt -p codex-hepta-evidence -- --check
cargo check --locked -p codex-hepta-contracts -p codex-hepta-evidence --all-targets
cargo test --locked -p codex-hepta-contracts --lib execution_contract_v1
cargo test --locked -p codex-hepta-evidence --lib execution_preparation_v1
cargo clippy --locked -p codex-hepta-evidence -p codex-hepta-contracts --all-targets -- -D warnings
```

Native tests use the original SqliteConfig and real HeptaEvidenceStore to cover transaction durability, cold reopen, exact idempotency, parallel identical prepares, same-operation stale generation/fence/target conflicts, raw-byte tampering, cross-Scope isolation, indeterminate quarantine, and the categorical absence of effect authority. Unit tests and same-process SQLite receipts do not establish power-loss guarantees on a target filesystem; collect target fsync/restart evidence before promotion.

No local Rust toolchain is available in the authoring container. Until exact-HEAD and merge tests complete on GitHub, this remains an **uncompiled, unqualified Draft**. Do not mark green from source review, data digests, Python results, or queued workflows. Follow real CI failures rather than suppressing lint/dependency advisories.

## Strict next dependency: P2b physical owner, still blocked

Original Agentd/Operations caller must authenticate request and selected owner, check quota and permitted effect class, use an independently issued signed Final-use grant, persist the full **physical** wire payload and durable operation identity before the precise effect boundary, and attach the original Codex Exec Server transport. Every update of authority epoch, generation, deadline, nonce/revocation and route must be rechecked at final entry. Lost ACK, crash, timeout, process/transport loss and cancellation after send are reconcile-only, never automatic retry. The original provider status or signed original outcome must be observed before marking a task complete. Keep the App Server model-only turn path separate from the tool-process authorization path.

Before real production deployment: enforce per-Scope rate/size quotas, verify target-host WAL/fsync/recovery on identical hardware, compare actual local/remote Codex execution at equal sandbox/authority ceilings, and finish Cell Split Control/CNS generation-fence/independent NDU gates. This P2a source provides **none** of those proofs.

No changes to mandatory CI policy, authority keys, existing Tool Router or runtime deployment flags.
