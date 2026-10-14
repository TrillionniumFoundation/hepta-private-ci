# P2b — Complete, atomic, source-free execution-intent recovery

**State: DRAFT / PREPARE-ONLY / DENY_ALL.** This change repairs a gap in the
stacked P2a source. It does not connect to a live Codex Exec Server, sign grants,
invoke a tool, observe physical effects, bypass Agentd, or turn a recovered
request into a one-shot send permit.

## Frozen ancestry

- Canonical development base: main at
  `78fdb0cf8537e3a84fc6e0a849707559c80881e8`.
- P1: [#1957](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1957),
  exact `fe5ab64f6b609e7c2cbfcf12352ff637fb2dc20f`.
- P2a: [#1967](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1967),
  exact `f91219b88831808b37b1fbd154a82008e597506d`, **this PR's base**.
- B0 transport-cost shadow remains
  [#1947](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/1947).
  Its Python IPC results do not qualify native Codex/Hepta latency.

## Observed audit gap

P2a inserted a `ProviderEffectIntent` whose `payload_sha256` represented
serialized `ExecutionIntentV1`, but the original Evidence table stored only
that hashed ProviderEffectIntent. After crash/restart, the complete execution
control envelope could not be reconstructed using a durable key alone. A
caller-supplied candidate could be checked for equality, but that is **not** a
source-free durable recovery protocol.

## This increment

1. Migration `0013_execution_prepared_envelopes.sql` extends **the same**
   original Evidence SQLite database and writer with immutable typed-envelope
   JSON, digest, exact request SHA256, and an FK to the original provider-effect
   intent. No second DB, no new writer, no separate lifecycle/ledger service.
2. The existing `HeptaEvidenceStore::prepare_execution_intent_v1` now commits
   **both** records under one `BEGIN IMMEDIATE` transaction, or neither.
   Unchanged original occurrences are idempotent; changing target, generation,
   fence, scope, epoch, payload or deadline collides rather than creating a new
   effect. Digest-only orphans are NOT backfilled and are rejected for
   preparation/recovery, even after restart.
3. `recover_execution_preparation_by_key_v1(key)` reconstructs the complete
   validated `ExecutionIntentV1` **without caller-provided intent text**, while
   still returning only a non-authorizing `RecordedOnly` or
   `OriginalOwnerReconciliationRequired` disposition. It cannot restore
   external tool payload bytes; their digest is recorded and actual bytes must
   later be independently supplied and verified by the real effect owner.
4. Cold/reopen verification checks immutable schema/triggers and every complete
   envelope against its original provider-effect intent and canonical digest.
   Missing originals, altered bytes and corrupted request binding fail closed.
   This local hash check is not an external anti-rollback oracle or signer.
5. Seven additional actual-SQLite adversarial tests cover source-free read-only
   reopen, partial-transaction fault injection and rollback, digest-only orphan
   rejection, immutable update/delete triggers, forged content with restored
   schema, quarantine survival and default denial. P2a's ten earlier tests must
   still pass unchanged.

## Exact tests required

```sh
python3 scripts/verify_cargo_lock.py
cd codex-rs
cargo fmt -p codex-hepta-contracts -p codex-hepta-evidence -- --check
cargo check --locked -p codex-hepta-contracts -p codex-hepta-evidence --all-targets
cargo test --locked -p codex-hepta-contracts --lib execution_contract_v1
cargo test --locked -p codex-hepta-evidence --lib execution_preparation_v1
cargo test --locked -p codex-hepta-evidence --lib execution_complete_v1
cargo test --locked -p codex-hepta-evidence --lib provider_effect
cargo clippy --locked -p codex-hepta-contracts -p codex-hepta-evidence --all-targets -- -D warnings
```

The authoring environment currently has no Rust toolchain. Native checks are
not claimed until exact source-HEAD and prospective-merge CI actually run.
A passing SQLite unit test is not a target-host power-failure/fsync result.

## Next **blocking** owner boundary

Only after native qualification, an original Agentd/Operations owner may
bind the same durable key to a **separate physical provider/tool payload**,
independent Final-use signature/revocation, original Supervisor generation
fences and a durable *pre-effect* send claim. An unsigned P1 binding, raw
Evidence digest, recovered envelope or model-only Codex `turn/start` grant
must never be converted to an Exec Server tool grant. Any lost transport ACK
or crash after effect entry remains reconcile-only with the **original**
provider status, never automatic retry. Real Codex Exec Server integration
requires equal-policy native sandbox tests and target-host evidence.

**No production route, tool permission, required-check bypass, NDU promotion,
CellSplit CNS cutover, or operator acceptance is introduced by this PR.**
