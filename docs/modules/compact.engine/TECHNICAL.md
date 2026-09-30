# compact.engine technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0  
**Module:** `compact.engine`  
**Owner:** `cognitive-platform`  
**Deputy:** `durability-kernel`  
**Lane:** `LANE-C-MEMORY`  
**Lifecycle:** `target`  
**Source status:** `existing_bound`  
**Bootstrap work package:** `MEM-5-COMPACT`

This is the normative implementation and operating guide for the repository implementation of `compact.engine`. Source delivery, product composition, exact-source qualification, independent acceptance, activation and release are separate claims. A source path or a unit test never grants deployment, merge or release authority.

## 1. Mission and non-negotiable boundary

`compact.engine` constructs bounded, content-addressed cognitive checkpoints from an authoritative `CognitiveSnapshot`. It may select, summarize and qualify material, but it may not rewrite source facts, erase source lineage, resurrect a tombstoned record, self-enroll trust, or present generated summary bytes as source evidence.

The repository exposes one canonical construction and publication path:

1. obtain an authoritative `CognitiveSnapshotKeyV1` and exact `CognitiveSnapshot`;
2. require an exact input manifest—omission and injection are hard failures;
3. verify independent Ed25519 receipts for retention selection, semantic generation and token accounting;
4. construct a private `QualifiedCompactionCandidateV2` under record, byte and token ceilings;
5. verify an independently signed evaluator receipt and construct `CompactionProofV2` plus witness;
6. seal all source material, receipts and proof into `VerifiedCompactionPublicationV1` against a root-authenticated trust manifest;
7. publish only through the preflighted and continuously fenced `MemoryCheckpointCoordinatorV2`;
8. reserve replay/nonces under the durable lease, atomically persist artifacts/head/outbox, then recoverably finalize the admission;
9. reopen by rehashing durable material, reconstructing the verified publication, revalidating historical trust, and re-admitting current trust before returning payload bytes.

The legacy record-only `compact()` entrypoint is not exported. The raw SQLite bundle/store is not exported. `QualifiedCompactionCandidateV2` fields remain private, so a caller cannot manufacture a candidate by filling public fields.

## 2. Authoritative source inventory

Primary source root:

- `codex-rs/hepta-compact-engine`

Core implementation:

- `src/lib.rs` — closed public inventory and canonical V2 coordinator export.
- `src/qualified.rs` — deterministic bounded kernel, exact snapshot coverage, deletion non-resurrection, protected references, checked arithmetic, loss report and proof construction.
- `src/trust.rs` — role-scoped Ed25519 enrollments and selector/generator/tokenizer/evaluator receipt validation.
- `src/trust_registry.rs` — root-authenticated, append-only manifest chain, rotation, revocation and current/historical trust semantics.
- `src/publication.rs` — sealed publication request, fresh batch token-accounting receipt, canonical archive and cryptographic reopen.
- `src/coordinator.rs` — V2 publication/reopen protocol over the immutable durable owner.
- `src/fenced_coordinator.rs` — durable lease, nonce reservation, admission recovery, source-retention release and manifest persistence.
- `src/fenced_coordinator_guarded.rs` — the middle guard layer; it path-loads `fenced_coordinator.rs` and continuously compares the in-memory registry with the durable active manifest and root pin.
- `src/fenced_coordinator_final.rs` — the public outer layer selected by `src/lib.rs`; it path-loads `fenced_coordinator_guarded.rs`, verifies the complete signed chain and performs durable-manifest preflight before any lease mutation. These three files are one nested authoritative module chain, not parallel implementations.
- `src/durable.rs` — immutable artifact/head/outbox owner, publication transaction and same-transaction owner/root/lease/manifest verification. It also owns the `durable_tests.rs` and `durable_fence_tests.rs` test-module roots.
- `src/mutation_guard.rs` — permanent SQLite mutation-intent tables/triggers and exact owner/root/manifest/lease/operation checks at every protected write boundary.
- `src/recovery.rs` — bounded admission/outbox recovery, claim lifecycle and restart reconciliation.
- `src/compaction_schema.sql` — immutable artifact, active-pointer, trust, revocation and outbox schema.
- `src/compaction_schema_hardening.sql` — NULL-safe predecessor CAS hardening applied on every open.
- `src/archive_codec.rs` — bounded canonical archive codec; it is not an authority deserializer.

Product composition:

- `codex-rs/hepta-agentd/src/compaction_checkpoint_host.rs` — `AgentdCompactionCheckpointHostV1`, the named Agentd scheduler host that composes production-writer authority with `MemoryCheckpointCoordinatorV2`.

Verification and operations:

- `src/qualified_tests.rs`
- `src/trust_tests.rs`
- `src/durable_tests.rs`
- `src/durable_fence_tests.rs`
- `src/product_e2e_tests.rs`
- `tests/capacity_profile.rs`
- `docs/modules/compact.engine/RECOVERY_PROTOCOL_V2.md`
- `.github/workflows/compact-engine-qualification.yml`
- `.github/workflows/compact-engine-capacity.yml`
- `scripts/compact_engine_qualification.py`
- `scripts/test_compact_engine_qualification.py`

`durable_fence_tests.rs` is reached from the `durable.rs` test module; the qualification verifier rejects any mapped or crate-local `*_tests.rs` source that is not reachable from the Rust test graph. The presence of these sources proves only materialization. A candidate is merge-ready only when the focused workflow emits one fail-closed readiness manifest for one source SHA, workflow run and attempt, with exact-head, deterministic synthetic-merge and required capacity lanes all terminally successful.

## 3. Canonical kernel contract

### 3.1 Authoritative input and exact coverage

The builder receives:

- the exact `CognitiveSnapshotKeyV1` frontier;
- the authoritative `CognitiveSnapshot` containing current source records;
- `CompactionInputRecordV2[]` with stable ID, revision, predecessor, deletion state, content digest, retention evidence and token accounting;
- `CompactionPolicyV2` with bounded record, byte and token budgets;
- protected live references;
- signed selector, generator and tokenizer receipts.

The input IDs/revisions must exactly cover the authoritative snapshot. A caller-supplied internally consistent subset is insufficient. Any extra record, missing record, snapshot substitution, revision gap, predecessor mismatch, payload digest mismatch, or resurrection after tombstone is rejected before candidate construction.

### 3.2 Determinism and capacity

Selection is protocol-visible. Inputs are ordered by registered retention priority and deterministic stable tie-break keys. Protected references are admitted first. Every retained item must fit all active ceilings. Counts, encoded bytes, token totals and loss-report totals use checked arithmetic.

Current hard ceilings are:

- 65,536 input records;
- 64 MiB semantic payload bytes;
- 8,000,000 payload tokens;
- a bounded protected-reference set.

Changing sorting, tie-break, fit behavior, identity scope or budget semantics requires a new algorithm/schema revision. The source constants are authoritative; source/document divergence fails documentation qualification.

### 3.3 Candidate, payload and proof identity

Candidate, payload, checkpoint, qualification and proof identities bind:

- authoritative snapshot and source-memory snapshot;
- scope, purpose, generation and predecessor;
- policy and input manifest;
- retained/omitted IDs and loss report;
- actual semantic payload bytes;
- selector, generator and tokenizer receipt identities;
- evaluator receipt, implementation and attestation;
- model, tokenizer and relevant configuration digests.

Zero or unknown critical digests are rejected. The proof witness is verified again during reopen.

## 4. Closed-world trust model

Four roles are independent:

- `TrustedRetentionSelectorV1` authorizes the exact retention input/order.
- `TrustedSemanticGeneratorV1` attests the exact payload and generation context.
- `TrustedTokenizerV1` attests token accounting only.
- `TrustedCompactionEvaluatorV1` independently evaluates reconstruction, contradiction preservation, protected support and deletion non-resurrection.

Tokenizer trust cannot substitute for generator provenance or evaluator independence. The evaluator cannot share principal identity or signing key with the selector or generator.

Each `TrustEnrollmentV1` binds schema version, role, key ID, epoch, validity interval, predecessor key digest, implementation digest, attestation digest, Ed25519 verifying key and optional one-way revocation time. Every receipt binds role, key ID, epoch, issue/expiry interval, exact subject digests, a non-zero anti-replay nonce and a 64-byte Ed25519 signature.

`SignedCompactionTrustManifestV1` is signed by an out-of-band pinned root. Manifests form a strictly increasing predecessor-bound chain. Historical entries are immutable except for one-way revocation. A current operation requires a current manifest and current role enrollment; historical reopen verifies the acceptance-time manifest and then separately re-admits each principal against the current active manifest before payload return.

## 5. Durable state and ownership

The durable owner persists:

| Object | Durable ownership rule |
|---|---|
| `compaction_candidates` | immutable candidate and exact source/policy/generation tuple |
| `compaction_payloads` | content-addressed semantic bytes and bounded byte/token costs |
| `compaction_evaluations` | immutable evaluator artifact and epoch |
| `compaction_proofs` | immutable proof image and 96-byte verification witness |
| `compaction_checkpoints` | immutable lineage and publication identity |
| `active_compaction_checkpoint` | one CAS-controlled head per owner/scope/purpose |
| `compaction_outbox` | append-only event identity with fenced claim/delivery state |
| `compaction_trust_registry` | append-only trust history with one-way revocation |
| `compaction_checkpoint_revocations` | immutable revocation facts |
| V2 owner/manifest/admission tables | lease, signed manifest history, nonce reservation and recoverable operation status |

Payload, candidate, evaluation, proof, checkpoint and revocation rows are immutable. Outbox identity and payload are immutable. The active pointer may advance only by one local generation and must name the exact previous checkpoint digest.

A newly materialized local durable owner may begin at any positive generation already proven by the authoritative snapshot. It is a local lineage root and must not invent a predecessor. Every later generation must be `active_generation + 1` and must name the exact active digest. The hardening trigger uses SQLite `IS NOT`, not `!=`, so a NULL predecessor cannot bypass the CAS through three-valued logic.

## 6. Three-stage publication protocol

### Stage A — fenced admission reservation

`MemoryCheckpointCoordinatorV2` first verifies the complete root-signed manifest chain and compares its final digest/root with any durable active manifest **before acquiring or replacing a lease**. A stale or forked chain is rejected without durable fencing side effects.

Under the exact owner lease, it then reserves `(owner, idempotency_key)` and all four role-bound nonces. The reservation binds request digest, checkpoint identity, owner instance, lease token/epoch, root and active manifest. Equal retries reuse the reservation; semantic drift or nonce reuse with different semantics conflicts.

### Stage B — immutable artifact/head/outbox transaction

`DurableCompactionStoreV1::publish` executes under one `BEGIN IMMEDIATE` transaction. Before resolving idempotency or inserting any artifact, the facade parses owner/root/manifest from the sealed archive and rechecks, inside that same transaction:

- exact owner;
- root pin;
- lease token digest;
- lease epoch;
- non-regressing lease expiry;
- durable active manifest;
- active manifest root.

A lease replacement, manifest rotation or root substitution therefore aborts the artifact transaction.

The transaction then:

1. resolves equal idempotent replay or rejects drift;
2. validates/persists the four historical trust enrollments;
3. inserts or verifies the content-addressed payload;
4. inserts immutable candidate, evaluation, proof and checkpoint rows;
5. performs the predecessor/generation active-head CAS;
6. inserts the deterministic `checkpoint-published` outbox event;
7. commits.

Commit makes artifacts, head and outbox visible together. Failure before commit exposes none of the new generation.

### Stage C — recoverable admission finalization

After Stage B commits, the admission is finalized as `committed` with publication/checkpoint/outbox digests. This is intentionally a separate transaction. A crash after artifact commit but before finalization is reconciled from the immutable checkpoint; it is not a second execution opportunity. Equal retry returns the original receipt.

## 7. Open, recovery and manifest anti-rollback

Opening the product owner is closed-world:

1. verify every signed manifest against the pinned root;
2. verify owner, root sequence and predecessor chain;
3. require the final manifest to be current;
4. preflight durable active manifest/root before lease acquisition;
5. persist/verify the manifest chain and acquire the lease;
6. compare the in-memory active registry with durable active state again;
7. open the immutable store, apply schema hardening and capture the exact lease/root/manifest fence;
8. run integrity, foreign-key, immutable-digest and active-pointer verification;
9. reconcile interrupted admissions and outbox claims.

Every public operation rechecks durable active manifest equality. Recovery performs a pre/post manifest check around the read so a concurrent manifest transition cannot return payload under a stale trust view.

`recover_current_checkpoint` expands the compact archive, reconstructs the canonical publication from source material and receipts, verifies the proof witness, validates all durable cross-object identities, re-admits current trust and only then returns payload bytes. A revoked active head falls back to the newest prior unrevoked generation and marks the fallback explicitly.

## 8. Source retention, revocation and GC

Each candidate binds a source-retention fence digest and deadline. Source facts remain owned by the source store; checkpoint publication never authorizes source mutation or deletion. `release_source_retention` is lease/manifest fenced and records only the release of the compaction-side hold.

Checkpoint revocation is append-only and emits a durable event. It does not erase historical evidence.

Physical payload/checkpoint GC remains fail-closed until a separately reviewed transaction proves all of the following:

- the checkpoint is durably revoked;
- no active pointer can select it;
- source-retention deadline and release conditions are satisfied;
- all durable references are accounted for;
- the GC event is inserted atomically;
- the same owner/manifest/lease fence is still valid.

## 9. Named product callers

Canonical library caller identity:

```text
memory.checkpoint-coordinator.v2
```

Native type: `MemoryCheckpointCoordinatorV2`.

Repository product caller identity:

```text
agentd.runtime.compaction-scheduler.v1
```

Native host: `AgentdCompactionCheckpointHostV1` in `codex-rs/hepta-agentd/src/compaction_checkpoint_host.rs`.

The Agentd host composes the existing production writer owner with the V2 coordinator, verifies current production-writer authority before every operation, and exposes lease renewal, manifest rotation, publication, recovery, revocation, source-retention release and outbox claim/completion. It cannot mint trust, accept a raw candidate/proof/key, or mutate source records.

This is source-level product composition. It is not production activation or independent semantic acceptance.

## 10. Verification matrix

The repository test matrix covers or is required to cover:

- input-order invariance and identical-input determinism;
- exact-coverage omission/injection rejection;
- revision/predecessor and tombstone non-resurrection;
- protected-reference retention;
- record/byte/token `limit-1`, `limit`, `limit+1` boundaries;
- selector/generator/tokenizer/evaluator signature, purpose, subject, nonce and epoch tamper;
- key rotation, revocation and historical/current trust separation;
- stale/forked manifest and wrong root;
- stale manifest rejection before lease acquisition;
- lease replacement between reservation and artifact transaction;
- NULL predecessor CAS bypass;
- duplicate idempotency and semantic drift;
- concurrent first-local-root and successor CAS;
- crash before/after artifact commit and committed-response loss;
- outbox claim/restart reconciliation and completion fencing;
- revoked-head fallback;
- payload/artifact/active-pointer corruption on reopen;
- migration forward/rollback and predecessor recovery;
- property tests and bounded codec fuzzing;
- public build→proof→atomic publish→restart→reopen/reconstruct→successor publication E2E.

The focused read-only workflow executes exact-head, deterministic synthetic-merge and required full-capacity lanes from one frozen source identity. Both compile/test lanes run the repository entrypoint for `codex-hepta-compact-engine` and `codex-hepta-agentd`, strict Clippy, rustfmt, implementation-map reachability verification and qualification-tool regression tests.

```bash
python3 -m unittest -v scripts.test_compact_engine_qualification
python3 scripts/compact_engine_qualification.py verify-map
cd codex-rs
cargo check --locked -p codex-hepta-compact-engine -p codex-hepta-agentd --all-targets
just test --locked -p codex-hepta-compact-engine -p codex-hepta-agentd
cargo clippy --locked -p codex-hepta-compact-engine -p codex-hepta-agentd --all-targets -- -D warnings
cargo fmt --all -- --check
```

The terminal job downloads only artifacts named for the current source SHA and run attempt. It emits `hepta.compact-engine-readiness-manifest.v1`, binding `source_head_sha`, `frozen_source_sha`, `base_sha`, deterministic and GitHub merge SHAs, workflow/final merge SHAs, run/attempt, runner image, target triple, `Cargo.lock`, migration, test-set, qualification-profile, implementation-map, documentation and source-tree hashes, plus every required artifact hash. Missing, queued, skipped, cancelled, failed, stale or cross-attempt evidence forces `requiredLanesPassed=false`, `mergeReady=false` and `productionQualified=false`. A pull-request gate requires `mergeReady=true`; a branch-push gate requires `requiredLanesPassed=true`. `productionQualified` remains false until a final merge SHA and an explicit successful post-merge receipt are bound.

## 11. Capacity and performance evidence

The required capacity lane in the same focused workflow attempt exercises the pure kernel at:

- 65,536 records;
- 64 MiB semantic payload;
- 8,000,000 payload tokens.

It records wall time, process CPU, peak RSS, host/toolchain identity and exact source binding, then runs the representative signed publication plus cryptographic reopen profile. Its artifact is a required input to the same readiness manifest. The standalone capacity workflow remains a diagnostic/check-name compatibility lane and is never accepted as a substitute for the current focused-workflow attempt. Publication and reopen metrics additionally expose bounded payload/archive bytes, observed hash count, clone-byte estimate and latency.

The pure-kernel ceiling is distinct from a full durable publish/reopen claim. An exact 64 MiB payload cannot traverse a transient archive that also needs metadata unless an explicit metadata-overhead allowance is implemented and qualified. Numeric SLOs require terminal target-host receipts on the final SHA.

## 12. Observability and operations

Safe metrics include publication disposition, generation, bounded artifact sizes, transaction latency, CAS conflicts, lease/manifest conflicts, integrity failures, revocation/fallback count, outbox state/age/attempt count and reopen latency. Logs may contain bounded IDs and digests, never semantic payload bytes, signatures or keys.

Alerts are required for integrity/foreign-key failure, active-pointer corruption, repeated CAS loss, lease takeover, stale/forked manifest, trust expiry/revocation, outbox age/attempt threshold, revoked-head fallback and capacity pressure.

The stop procedure disables new publication, preserves immutable evidence, continues safe read/fallback only when integrity and current trust succeed, and never deletes source facts.

## 13. Current claim boundary

The convergence branch contains:

- the canonical bounded kernel;
- four-role signed trust and root-manifest chain;
- sealed publication/reopen archive;
- durable immutable artifact/head/outbox owner;
- V2 lease, admission and recovery protocol;
- same-transaction owner/root/lease/manifest fencing;
- pre-lease stale-manifest rejection;
- named Agentd product host;
- public V2 restart/reconstruction/successor E2E source;
- focused and capacity workflows;
- machine-checked implementation-map/test reachability;
- one-run fail-closed readiness-manifest generation.

The following remain gates before `productionImplementation` may become true:

1. terminal green exact-head and deterministic synthetic-merge focused qualification on the final SHA;
2. terminal target-host capacity evidence, including a representative full publish/reopen profile;
3. migration rollback and power-loss/fault-injection receipts on the final schema;
4. separately reviewed fenced physical GC;
5. independent semantic reconstruction acceptance and operator approval.

Activation, canary, promotion, merge and release remain externally governed. This document grants none of those authorities.
