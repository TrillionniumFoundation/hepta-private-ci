# cognitive.store production convergence

Status: source implementation and qualification contract. This document records the current product boundary; it is not activation, operator acceptance, promotion, or release evidence.

## 1. Canonical ownership and compiled module tree

`codex-hepta-cognitive-store` owns the module-facing semantic contract. Its compiled source tree is `src/lib.rs`, `src/durable.rs`, and `src/v2.rs` plus their directly included tests. `durable.rs` re-exports the one physical SQLite owner instead of creating a second database or writer.

`codex-hepta-memory::CognitiveStore` owns the physical schema, migrations, WAL/FULL durability, transactions, recovery implementation, Memory revisions, and the Memory-revision-bound knowledge-fact subledger. `AgentdProductionWriterHost` is the named product composition seam. Files or tests not reachable from this module tree are not implementation or qualification evidence.

The selected product chain is:

```text
trusted host bootstrap
  |  independently authenticated exact-current-cut witness
  |  externally verified authority lease + live verifier
  v
AgentdProductionWriterHost::open_with_recovery
  v
hepta-memory::CognitiveStore::open_with_recovery
  v
ProductionDurableWriter
  v
sealed ProductionCognitiveMutationCapability
  v
remember_with_kg / correct_with_kg / forget_with_kg
  v
cognitive_1.sqlite3
```

No second cognitive database, dual-write path, raw product writer fallback, or self-minted current-cut witness is permitted.

## 2. Memory and knowledge-fact authority

The authoritative Memory ledger is the immutable `memory_revisions` family, its citations, and its current-head projection.

The authoritative knowledge-fact state is the Memory-revision-bound subledger:

- `kg_revision_fact_sets`;
- `kg_revision_entities`;
- `kg_revision_relations`;
- their immutable source/citation and count invariants.

A correction creates a successor Memory revision and complete successor fact set. A forget creates a tombstoned Memory revision and an empty fact set. Knowledge facts have no independently writable head, CAS domain, or second writer. Knowledge-graph generations are derived projections and never become the fact source of truth.

The in-memory V2 store is a semantic and image-integrity oracle. It is not the production durability backend.

## 3. Production mutation boundary

A production semantic mutation is admitted only through a live-verified `ProductionDurableWriter` and its sealed `ProductionCognitiveMutationCapability`. The normal product build does not expose the qualification-only already-open-store seam.

For `remember`, `correct`, and `forget`, operation admission, authoritative source/Memory/fact/projection mutation, and terminal provenance are committed in the same `BEGIN IMMEDIATE` SQLite transaction. The production receipt binds at least:

- operation and semantic-input digests;
- expected predecessor revision where applicable;
- authoritative source identity, revision, digest, and observation time;
- grant digest, authority epoch, owner epoch, lease ID, and writer generation;
- committed write digest and provenance event identities.

A semantic-validation failure rolls the local admission and domain mutation back together. Queue admission or handler return is not an external-effect success.

Live authority must be revalidated at the actual owner-use boundary. A check performed only before waiting for the SQLite writer lock is not sufficient proof that a later commit was authorized. Exact transaction-entry and pre-commit revocation regressions remain required qualification evidence until the implementation and tests establish that ordering.

## 4. Ordinary open, recovery, and publication

Ordinary `CognitiveStore::open` verifies the registered schema and logical integrity and reconstructs the durable state. It does not independently prove that the opened database is the latest acknowledged cut and therefore is not a rollback-sensitive production-writer recovery path.

`CognitiveStore::open_with_recovery` is the writable recovery path. It:

1. requires an independently authenticated exact-current-cut anchor and an externally verified production authority;
2. takes the exclusive cognitive-store fence;
3. binds retained source database/WAL/journal descriptors;
4. materializes a bounded private generation without reopening the suspect source path through SQLite;
5. verifies registered schema, logical cut equality, SQLite integrity, and the authority/fence;
6. checkpoints and reopens the private generation;
7. atomically publishes the active-generation pointer only after the final checks;
8. retains the exclusive fence for the returned recovered generation.

Recovery failure never falls back to ordinary open. If pointer publication durability is ambiguous, the result remains `Indeterminate`; the possibly active generation is not deleted or treated as safely unpublished.

The external verifier must also be current immediately before active-generation publication. Tests must cover revocation while copying, before checkpoint, after checkpoint, and immediately before publication. Source implementation does not manufacture the independent latest-witness fact.

## 5. Trusted witness and normal daemon bootstrap

The host, not `cognitive.store`, owns authentication and independent retention of the latest current-cut witness. The witness is an exact equality fence; by itself it is not a signature, monotonic counter, grant, or proof that the latest witness was retained.

Normal daemon write startup is complete only when a trusted bootstrap supplies:

- the current authenticated witness or an explicit revoked/pending disposition;
- the matching authority lease and retained live verifier;
- the writer lease identity and strictly governed generation;
- restart reconciliation for a database commit whose successor witness was not acknowledged.

A pending witness update must fail closed on restart. The daemon must query the durable operation result and reconcile the external witness; it must not repeat the semantic mutation or accept the database itself as proof that its own state is current.

Until this normal bootstrap and restart protocol has exact executable evidence, `productCallerState` remains externally bootstrapped/pending and `productionImplementation` remains false.

## 6. Duplicate request and response-loss contract

The durable operation identity is semantic. Reusing it with changed content conflicts. Repeating an already committed semantic request must never append a second source, Memory revision, fact set, graph generation, or provenance occurrence.

A caller that lost the original response must be able to query a durable, typed terminal result for the exact operation identity. A generic `IllegalTransition("committed")` may prevent duplicate execution, but it is not the final product result contract. The query result must distinguish at least not found, queued, committed, rejected, indeterminate, and rolled back, and a committed result must bind the original operation and durable write identities.

Result lookup grants no authority to repeat a mutation and does not convert an old grant into current authority.

## 7. Shared experience and capacity

Shared-experience grants use the same SQLite owner and exact Memory revision. Recall and Replay are distinct purposes; Replay additionally binds parameter scope and artifact consumer. Current source eligibility and permission are checked again at consumer use.

Capacity is defined over active, unexpired policy heads, not every policy identity ever present in immutable history. Revoked and expired history remains auditable while releasing its live-capacity slot. The current-head projection must be verified against immutable history on open/recovery, and renewal/revocation must remain possible at the declared boundary.

Per-policy revision limits, owner event/outbox limits, Lane-C page ancestry limits, and retained immutable history remain explicit capacity boundaries. Paging limits response materialization; it is not evidence that each page avoids all scope-wide work. Long-term archive/pruning may be added only with predecessor, tombstone, revocation, source-lineage, current-cut, and recovery proofs intact.

## 8. Cutover and rollback

This convergence is an authority/route cutover over the same compatible SQLite owner; it is not a data-copy or dual-write migration.

Cutover requires draining known local outcomes, closing the predecessor writer, authenticating the exact current cut, acquiring a current authority under the intended generation, opening only through the recovery-gated host, and proving that the pre-cutover logical cut is unchanged before the first new mutation.

Rollback uses the same compatible database under a fresh generation and current authority. Reusing an earlier fence or restoring an old backup without an independently current witness is forbidden because it can resurrect corrected or forgotten content.

## 9. Required qualification

The following commands or their workflow-equivalent exact commands must complete on the exact candidate and every applicable deterministic merge candidate:

```text
python3 scripts/hepta-docs.py verify
python3 scripts/hepta-implementation-maps.py verify
cargo test --locked -p codex-hepta-cognitive-store
cargo test --locked -p codex-hepta-memory
cargo test --locked -p codex-hepta-agentd --test cognitive_store_product_writer
cargo clippy --locked -p codex-hepta-cognitive-store --all-targets -- -D warnings
cargo clippy --locked -p codex-hepta-memory --all-targets -- -D warnings
cargo clippy --locked -p codex-hepta-agentd --all-targets -- -D warnings
```

Qualification also requires executed evidence for:

- revocation while waiting for the write lock and immediately before commit;
- recovery revocation at copy/checkpoint/publication cuts;
- child-process crash/reopen and ambiguous active-pointer publication;
- response loss followed by typed result query without re-execution;
- current, stale, revoked, and pending external witness startup;
- writer handoff and old-backup rejection;
- shared-experience active-capacity migration, expiry, withdrawal, reactivation, and reopen;
- the 256-record and 16,384-record durable profiles;
- selected target-host latency, storage, memory, and recovery acceptance.

A canceled, skipped, stale-head, or unrelated workflow is not success evidence for these items.

## 10. Claim vocabulary

- **semantic oracle implemented**: V2 invariants and tests exist;
- **durable owner source-implemented**: the SQLite owner and recovery/mutation code exist;
- **product composition source-bound**: the named Agentd host and sealed capability are wired in source;
- **production implementation proved**: exact-candidate executable qualification has passed;
- **product execution proved**: the normal daemon used authenticated external inputs through the selected path;
- **accepted / activated / promoted / released**: separate independently governed lifecycle states.

Keep `productionImplementation=false`, `productExecutionProved=false`, and acceptance/activation/promotion/release false until their own current evidence exists.