# compact.engine technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `compact.engine`  
**Owner:** `cognitive-platform`  
**Deputy:** `durability-kernel`  
**Lane:** `LANE-C-MEMORY`  
**Lifecycle:** `target`  
**Source status:** `existing_bound`  
**Bootstrap work package:** `MEM-5-COMPACT`

This document is the normative implementation and operating guide for the repository implementation of `compact.engine`. It distinguishes source implementation, product composition, qualification, independent acceptance, activation and release. A source path or passing unit test never grants production, deployment, merge or release authority.

## 1. Mission and non-negotiable boundary

`compact.engine` constructs bounded, content-addressed cognitive checkpoints from an authoritative `CognitiveSnapshot`. It may select, summarize and qualify material, but it may not rewrite source facts, erase source lineage, resurrect a tombstoned record, self-enroll trust, or treat a generated summary as source evidence.

The module has one canonical construction route:

1. receive an authoritative `CognitiveSnapshot` and exact compaction input manifest;
2. verify exact input coverage and deletion/revision invariants;
3. verify signed retention-selection, semantic-generation and tokenization receipts;
4. build a private `QualifiedCompactionCandidateV2` under record, byte and token ceilings;
5. verify an independently signed evaluator receipt and construct `CompactionProofV2`;
6. publish immutable artifact images through `DurableCompactionStoreV1` using one SQLite transaction and a generation/predecessor CAS;
7. expose the active checkpoint through `MemoryCheckpointCoordinatorV1` only after reopen integrity and revocation checks.

The legacy record-only `compact()` entrypoint is not exported. Callers cannot construct `QualifiedCompactionCandidateV2` by filling public fields.

## 2. Source inventory

Authoritative source root:

- `codex-rs/hepta-compact-engine`

Primary components:

- `src/lib.rs` — closed public inventory; only canonical qualified/trusted/durable surfaces are exported.
- `src/qualified.rs` — deterministic bounded kernel, exact snapshot coverage, deletion non-resurrection, protected-reference retention, loss report and proof construction.
- `src/trust.rs` — Ed25519 enrollment and receipt validation for selector, generator, tokenizer and evaluator identities.
- `src/durable.rs` — durable owner, transaction, generation CAS, outbox, restart verification, revocation and fallback selection.
- `src/compaction_schema.sql` — exact SQLite schema, constraints, indexes and immutability guards.
- `src/qualified_tests.rs`, `src/trust_tests.rs`, `src/durable_tests.rs` — source tests.
- `.github/workflows/compact-engine-qualification.yml` — read-only exact-head and deterministic synthetic-merge qualification.

The source root is materialized. This fact does not by itself establish a green exact-head receipt, product execution, independent semantic acceptance, activation or release.

## 3. Canonical kernel contract

### 3.1 Authoritative input

The public builder receives:

- `CognitiveSnapshotKeyV1` identifying the exact source frontier;
- an authoritative `CognitiveSnapshot` containing the current source records;
- `CompactionInputRecordV2[]` whose stable IDs, revisions, predecessor links, deletion state and payload digests must exactly cover the authoritative snapshot;
- `CompactionPolicyV2` with bounded record, byte and token budgets;
- protected live references;
- signed selector, generator and tokenizer receipts.

Omission and injection are both hard failures. Internal consistency of a caller-supplied subset is not sufficient.

### 3.2 Determinism and selection

The selection algorithm is protocol-visible. Inputs are ordered by registered retention priority and stable deterministic tie-break keys. Every retained record must fit all active ceilings. Checked arithmetic is mandatory for counts, encoded bytes, token counts and report totals. Changing sort keys, tie-break semantics, fit behavior or digest scope requires a new schema/algorithm revision.

Current hard ceilings are:

- at most 65,536 input records;
- at most 64 MiB encoded semantic payload;
- at most 8,000,000 tokens;
- a bounded protected-reference set.

The exact constants in source prevail if this document and source diverge; such divergence fails documentation qualification.

### 3.3 Deletion and protected support

A tombstoned stable ID cannot reappear as live in a later revision. Required protected live references are retained before optional material. A candidate records retained and omitted IDs, counts, digests, capacity usage and explicit loss observations. Compaction never converts omitted material into a deletion decision.

### 3.4 Candidate and proof identity

Candidate, semantic payload, checkpoint, qualification and proof identities bind the exact source snapshot, source-memory snapshot, policy, input manifest, retained/omitted sets, payload bytes, tokenizer receipt, generator receipt, evaluator receipt and implementation/attestation identities. Unknown or zero critical digests are rejected.

## 4. Trust and receipt lifecycle

Four roles are independent:

- `TrustedRetentionSelectorV1` — authorizes the exact retention ordering/manifest.
- `TrustedSemanticGeneratorV1` — attests the exact semantic payload and generation configuration.
- `TrustedTokenizerV1` — attests token accounting only.
- `TrustedCompactionEvaluatorV1` — independently evaluates reconstruction/loss obligations and signs the qualification.

Tokenizer trust cannot substitute for generator provenance or evaluator independence.

Every `TrustEnrollmentV1` binds:

- schema version;
- role;
- key ID;
- trust epoch;
- validity interval;
- optional predecessor key digest;
- implementation digest;
- attestation digest;
- Ed25519 verifying key;
- optional one-way revocation time.

Every signed receipt binds its exact subject digests, key ID, trust epoch, issue/expiry interval, anti-replay nonce and 64-byte Ed25519 signature. Current verification rejects not-yet-valid, expired or revoked trust. Historical verification evaluates trust and receipt validity at the durable acceptance time, preserving verifiability after later rotation while rejecting a key already revoked at acceptance.

Rotation requires a strictly increasing epoch, a different key digest and an explicit predecessor-key digest. The durable trust registry is append-only except for a one-way transition from unrevoked to revoked.

## 5. Durable state model

`src/compaction_schema.sql` owns these tables:

| Table | Purpose |
|---|---|
| `compaction_candidates` | immutable candidate identity, exact snapshot/policy/generation tuple, source-retention fence and idempotency key |
| `compaction_payloads` | content-addressed semantic payload bytes and bounded byte/token costs |
| `compaction_evaluations` | immutable evaluator artifact and evaluator epoch |
| `compaction_proofs` | immutable proof image plus 96-byte verification witness |
| `compaction_checkpoints` | immutable checkpoint lineage and publication digest |
| `active_compaction_checkpoint` | one CAS-controlled active pointer per owner/scope/purpose |
| `compaction_outbox` | durable local events with claim/delivery fencing and bounded retries |
| `compaction_trust_registry` | role-scoped trust epochs, validity and revocation |
| `compaction_checkpoint_revocations` | append-only checkpoint revocation facts |

Payload, candidate, evaluation, proof, checkpoint and revocation records are immutable. Outbox identity and payload are immutable while delivery state advances. The active pointer may advance only by one generation and must name the previous checkpoint as predecessor.

## 6. Atomic publication protocol

`DurableCompactionStoreV1::publish` acquires `BEGIN IMMEDIATE` ownership and executes this sequence in one transaction:

1. resolve an existing idempotency key; identical semantics return `Unchanged`, drift conflicts;
2. validate and persist the four trust enrollments;
3. insert or verify the content-addressed payload;
4. insert immutable candidate, evaluation, proof and checkpoint rows;
5. compare the active generation/checkpoint and perform a predecessor-bound CAS;
6. insert the `checkpoint-published` outbox event;
7. commit.

Any failure rolls the transaction back. The first generation must be `1` with no predecessor. Later generations must be exactly previous generation plus one and name the exact active checkpoint digest. Duplicate requests are idempotent; reuse of an idempotency key with different semantics is terminal conflict.

The publication digest includes owner, idempotency key, scope, purpose, generation, predecessor, source snapshots, source-retention fence, policy, candidate, payload, evaluation, proof, checkpoint, selector/generator receipt digests, all four trust enrollment identities, all artifact-image digests and acceptance time.

## 7. Recovery, revocation and retention

Store open enables foreign keys, WAL and `synchronous=FULL`, applies the deterministic schema, runs `PRAGMA integrity_check` and `PRAGMA foreign_key_check`, verifies required schema objects, rehashes every payload and artifact image, and validates every active pointer against an exact immutable checkpoint row.

`MemoryCheckpointCoordinatorV1::recover_current_checkpoint` repeats integrity verification, requeues interrupted outbox claims, and then selects the active non-revoked checkpoint. If the active checkpoint is revoked, selection falls back to the highest earlier non-revoked generation and marks the returned selection as a fallback.

Every candidate carries a `source_retention_fence_digest` and `retain_source_until_unix_seconds`. Source facts remain owned by the source store; this module records the fence but may not delete source data. Physical payload GC is prohibited until a separately reviewed fenced-GC transaction proves all referencing checkpoints revoked, the source-retention deadline elapsed, no active pointer references the payload and the GC outbox event is durable. Until that transaction is implemented and qualified, payload deletion remains fail-closed.

Checkpoint revocation is append-only and emits a durable `checkpoint-revoked` event. Revocation does not erase historical evidence.

## 8. Outbox and response-loss semantics

Outbox events are inserted in the same transaction as publication/revocation. Event identity is deterministic from publication digest and event kind. A worker claims one pending event with a unique claim token and atomically increments the attempt count. Completion requires the exact claim token. Process restart calls `reconcile_claims`, returning interrupted claims to pending state. Delivered events remain immutable audit evidence.

Queue acceptance is not external success. Destination-specific delivery, deduplication, acknowledgement and terminal failure remain responsibilities of the named adapter. The local outbox supports at most 1,000 attempts per row and a payload ceiling of 1 MiB; the delivery policy must terminalize before violating that bound.

## 9. Named product caller

The repository-owned caller is:

```text
memory.checkpoint-coordinator.v1
```

represented by `MemoryCheckpointCoordinatorV1`. It accepts only a fully verified `DurableCompactionBundleV1`, publishes through the durable owner and recovers only after integrity/reconciliation checks. It does not mint trust, generate semantic payloads, approve its own evaluation or mutate cognitive source records.

Library composition is not activation. A product host must still construct this caller from the product-owned cognitive store/runtime bootstrap and provide externally enrolled selector/generator/tokenizer/evaluator identities. The implementation map records the exact composition state.

## 10. Failure and crash boundaries

Required crash-injection boundaries are:

- before and after payload insert;
- before and after candidate/evaluation/proof insert;
- before and after checkpoint insert;
- immediately before and after active-pointer CAS;
- immediately before and after outbox insert;
- after commit but before response delivery;
- after outbox claim and before destination acknowledgement.

Expected behavior is either the prior complete active generation or the new complete generation plus its outbox event—never a partial generation. Retrying after committed-response loss returns the existing publication. A CAS loser receives conflict and must rebuild from the new active head.

Migration failure must leave the predecessor database usable by the predecessor binary. Schema changes require a versioned migration rehearsal, checksum, forward test, rollback/restore test and corruption fixture.

## 11. Verification matrix

Source tests must cover at least:

- input order invariance and identical-input digest determinism;
- exact-coverage omission and injection rejection;
- tombstone non-resurrection;
- protected-reference retention;
- record/byte/token `limit-1`, `limit`, `limit+1` boundaries;
- selector/generator/tokenizer/evaluator signature, nonce, epoch and subject tamper;
- trust rotation, revocation and historical validation;
- duplicate idempotency, semantic drift and concurrent generation CAS;
- commit/response-loss replay;
- outbox claim/restart reconciliation and completion fencing;
- revoked-head fallback;
- payload/artifact corruption and active-pointer corruption on reopen;
- migration failure and predecessor recovery;
- property tests for ordering, capacity and digest stability;
- fuzzing of receipt decoding, manifest construction and durable-row corruption.

The focused workflow runs, from a clean read-only checkout:

```bash
cd codex-rs
cargo fmt --all -- --check
cargo check --locked -p codex-hepta-compact-engine --all-targets
cargo test --locked -p codex-hepta-compact-engine --all-targets
cargo clippy --locked -p codex-hepta-compact-engine --all-targets -- -D warnings
```

It executes both the exact source head and a deterministic synthetic merge with the current PR base. A queued, skipped, cancelled or failed job is not qualification evidence.

## 12. Capacity and performance qualification

Qualification fixtures cover 65,536 records, 64 MiB payload and 8,000,000 tokens. They record:

- wall and CPU time;
- peak RSS;
- allocation/clone count where instrumentation supports it;
- source and artifact hash count;
- publication latency;
- reopen/integrity-verification latency;
- SQLite database, WAL and outbox sizes.

Large capacity fixtures may be ignored in ordinary unit CI only when a named qualification lane runs them and publishes exact-source artifacts. Numeric SLOs cannot be claimed until target-host measurements are stored. The implementation remains fail-closed at hard source limits regardless of benchmark status.

## 13. Observability and operations

Safe metrics include publication disposition, generation, bounded artifact sizes, transaction latency, CAS conflicts, integrity failures, revocation/fallback count, pending/claimed/terminal outbox count and reopen latency. Logs use digests and bounded identifiers, never semantic payload bytes, signatures, keys or source record contents.

Alerts are required for:

- integrity or foreign-key failure;
- active pointer corruption;
- repeated CAS conflict;
- trust expiry/revocation affecting new publication;
- outbox age/attempt threshold;
- fallback from a revoked head;
- payload or checkpoint capacity pressure.

The stop procedure disables new publication, preserves immutable evidence, continues safe read/fallback where integrity allows, and does not delete source facts.

## 14. Claim boundary and completion

Repository source implementation is complete only after:

1. exact-head and synthetic-merge focused qualification pass on the final SHA;
2. durable and trust tests cover the required failure matrix;
3. the named caller is composed through a product-owned bootstrap;
4. implementation map, dossier, source map and registries match the final public inventory;
5. target-host capacity receipts and migration rehearsals are stored.

Independent semantic acceptance, production activation, canary, promotion and release remain external gates. This document grants no authority to merge, deploy, activate or release.
