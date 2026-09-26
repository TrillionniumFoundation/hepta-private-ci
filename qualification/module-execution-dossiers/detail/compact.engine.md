# compact.engine: implementation and execution dossier

Parent: `docs/modules/compact.engine/TECHNICAL.md`. Lane: `LANE-C-MEMORY`. Package: `MEM-5-COMPACT`.

Status: canonical qualified kernel, four-role signed trust boundary and durable checkpoint owner are present on the convergence branch. Exact-head and deterministic synthetic-merge qualification, product bootstrap composition, fenced physical GC, capacity measurements and independent acceptance remain explicit gates.

## 1. Source and ownership

Authoritative root:

- `codex-rs/hepta-compact-engine`

No workflow may generate production source or push implementation commits. `.github/workflows/compact-engine-qualification.yml` is read-only and verifies the checked-out source. The deleted write-enabled materializer is not part of the implementation or evidence chain.

The module owns compaction candidate/payload/evaluation/proof/checkpoint publication records, its active-pointer CAS, local outbox, trust-enrollment history and checkpoint revocations. It does not own cognitive source facts or product deployment authority.

## 2. Public construction and proof path

The exported construction path is:

```text
CognitiveSnapshot + exact input manifest
  -> signed selector/generator/tokenizer admission
  -> build_qualified_candidate
  -> signed independent evaluator admission
  -> prove_compaction
  -> DurableCompactionBundleV1::from_verified
  -> MemoryCheckpointCoordinatorV1::publish_verified_checkpoint
```

The record-only `compact()` API is not exported. `QualifiedCompactionCandidateV2` fields are private. The builder enforces authoritative snapshot completeness, exact input coverage, revision/predecessor consistency, deletion non-resurrection, protected support and record/byte/token ceilings.

## 3. Durable records and transaction

`src/compaction_schema.sql` defines:

- `compaction_candidates`
- `compaction_payloads`
- `compaction_evaluations`
- `compaction_proofs`
- `compaction_checkpoints`
- `active_compaction_checkpoint`
- `compaction_outbox`
- `compaction_trust_registry`
- `compaction_checkpoint_revocations`

Candidate, payload, evaluation, proof, checkpoint and revocation identities are immutable. Publication executes under `BEGIN IMMEDIATE` and atomically persists trust, artifacts, checkpoint, generation/predecessor CAS and outbox. The idempotency key returns the prior publication only for identical semantics and conflicts on drift.

## 4. Trust boundary

Independent enrolled roles are:

- `TrustedRetentionSelectorV1`
- `TrustedSemanticGeneratorV1`
- `TrustedTokenizerV1`
- `TrustedCompactionEvaluatorV1`

Enrollments and receipts bind schema version, role, Ed25519 key, key ID, trust epoch, validity interval, implementation/attestation digests and anti-replay nonce. Rotation requires an increasing epoch and predecessor key digest. Revocation is one-way. Historical verification uses the durable acceptance time; tokenizer authority is limited to token accounting.

## 5. Recovery and rollback

Store open applies the exact schema, enables foreign keys, WAL and full synchronous durability, runs SQLite integrity/foreign-key checks, verifies required schema objects, rehashes persisted payload/artifact bytes and checks every active pointer.

Recovery requeues interrupted outbox claims and selects the active non-revoked checkpoint. A revoked active head falls back to the highest prior non-revoked generation. A transaction failure leaves the previous active generation. Retrying after committed-response loss resolves through the idempotency key.

Source retention remains fenced by a candidate-bound digest and deadline. Source deletion belongs to the source owner. Physical payload deletion remains fail-closed until a reviewed GC transaction proves revocation, inactivity, elapsed retention and durable GC notification.

## 6. Named caller and composition boundary

Repository caller identity:

```text
memory.checkpoint-coordinator.v1
```

Native type: `MemoryCheckpointCoordinatorV1` in `src/durable.rs`.

It publishes only a fully verified durable bundle and recovers only after integrity and outbox reconciliation. This is a named source caller. Product execution is not claimed until the cognitive-store/runtime product bootstrap constructs it with the product database and externally enrolled trust identities.

## 7. Current source tests

- `src/qualified_tests.rs` — deterministic selection, exact snapshot binding, protected references, deletion and capacity behavior.
- `src/trust_tests.rs` — role, signature, epoch, nonce, validity, tamper, rotation and historical verification.
- `src/durable_tests.rs` — schema open/reopen, outbox response-loss recovery, one-way revocation, immutable rows and artifact-size ceiling.

These paths are test identities, not pass receipts. Final evidence must bind the final commit SHA and include complete step results.

## 8. Qualification commands

From `codex-rs`:

```bash
cargo fmt --all -- --check
cargo check --locked -p codex-hepta-compact-engine --all-targets
cargo test --locked -p codex-hepta-compact-engine --all-targets
cargo clippy --locked -p codex-hepta-compact-engine --all-targets -- -D warnings
```

`.github/workflows/compact-engine-qualification.yml` runs those commands on the exact source head and a deterministic synthetic merge. Queued, skipped, cancelled and failed jobs are not evidence.

## 9. Required remaining repository work

Before raising the production implementation/composition claim:

1. obtain green exact-head and synthetic-merge focused receipts on the final SHA;
2. add full build→proof→publish→restart→reload→reconstruct→incremental-event E2E coverage;
3. add concurrent writer CAS, duplicate/semantic-drift, revoked-head fallback and row-corruption fixtures;
4. add explicit pre/post transaction crash injection and migration rollback rehearsal;
5. add property tests and fuzz targets for ordering, receipt decoding and durable corruption;
6. compose the named coordinator through the product-owned cognitive-store/runtime bootstrap;
7. implement separately reviewed fenced physical payload GC;
8. store 65K-record, 64-MiB and 8M-token target-host measurements.

## 10. External gates and claim boundary

The branch does not claim independent semantic acceptance, production trust enrollment, activation, canary, promotion, merge authority or release. Those remain externally governed. A green source qualification proves only the exact repository candidate tested by that run.
