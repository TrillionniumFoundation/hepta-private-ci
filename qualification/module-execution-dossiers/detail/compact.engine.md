# compact.engine: implementation and execution dossier

Parent: `docs/modules/compact.engine/TECHNICAL.md`. Lane: `LANE-C-MEMORY`. Package: `MEM-5-COMPACT`.

Status: the convergence branch contains the canonical qualified kernel, root-authenticated four-role trust chain, sealed publication/reopen archive, V2 durable lease/admission protocol, atomic artifact/head/outbox owner, named Agentd product host and public restart/reconstruction/successor E2E source. Final exact-head/synthetic-merge receipts, target-host full-path capacity evidence, migration/power-loss qualification, fenced physical GC and independent acceptance remain gates.

## 1. Source and ownership

Authoritative roots:

- `codex-rs/hepta-compact-engine`
- `codex-rs/hepta-agentd/src/compaction_checkpoint_host.rs` for the named product composition.

No workflow generates production source or pushes implementation commits. The focused and capacity workflows use read-only checkouts. The earlier write-enabled materializer is deleted and is not evidence.

The module owns candidate, payload, evaluation, proof, checkpoint, active-pointer, trust-history, admission, nonce, revocation and local outbox state. It does not own cognitive source facts, external delivery success, deployment or release authority.

## 2. Canonical public path

```text
CognitiveSnapshotKeyV1 + authoritative CognitiveSnapshot + exact input manifest
  -> root-authenticated selector/generator/tokenizer/evaluator registrations
  -> signed selection/generation/token-accounting receipts
  -> private QualifiedCompactionCandidateV2
  -> independently signed CompactionProofV2 + witness
  -> VerifiedCompactionPublicationV1
  -> MemoryCheckpointCoordinatorV2
  -> AgentdCompactionCheckpointHostV1
```

The record-only `compact()` API, raw durable bundle and raw SQLite store are not exported. Candidate fields remain private. Omission, injection, revision/predecessor drift, deletion resurrection, capacity overflow and receipt substitution fail closed.

## 3. Trust boundary

Independent roles are:

- `TrustedRetentionSelectorV1`
- `TrustedSemanticGeneratorV1`
- `TrustedTokenizerV1`
- `TrustedCompactionEvaluatorV1`

Each enrollment binds role, key ID, Ed25519 key, trust epoch, validity, implementation/attestation identity, predecessor key and one-way revocation. Receipts bind exact subjects, validity and a non-zero anti-replay nonce. Root-signed manifests are predecessor-bound and append-only. Historical reopen verifies the acceptance-time manifest, then current read admission separately rejects revoked or substituted principals. Tokenizer authority is limited to accounting.

## 4. V2 durable protocol

The product owner uses three stages:

1. **Admission reservation:** under the exact lease, reserve operation ID and four nonces with request, root and manifest identity.
2. **Artifact transaction:** in one `BEGIN IMMEDIATE`, verify owner/root/lease token/epoch/expiry/active manifest, resolve idempotency, persist trust and immutable artifacts, advance the predecessor/generation CAS, and insert the outbox event.
3. **Admission finalization:** bind committed publication/checkpoint/outbox digests. A crash between stages two and three is reconciled from immutable state rather than re-executed.

A newly materialized local owner may start at any positive generation proven by the source snapshot and must not invent a predecessor. Successors must be exactly `active + 1` and name the exact active digest. `compaction_schema_hardening.sql` uses NULL-safe `IS NOT` predecessor comparison.

## 5. Lease and manifest fencing

`fenced_coordinator_final.rs` verifies the complete signed manifest chain and compares its final root/digest with durable active state before any lease mutation. A stale/forked chain therefore cannot seize or replace a lease as a side effect of rejected open.

`fenced_coordinator_guarded.rs` continuously compares in-memory and durable active manifests. `durable_facade.rs` repeats owner, root, exact lease token/epoch, non-regressing expiry and active-manifest checks inside the same transaction that writes artifacts, head and outbox. Lease replacement or manifest rotation between reservation and artifact commit aborts publication.

## 6. Recovery and rollback

Open enables foreign keys, WAL and `synchronous=FULL`, applies the exact schema plus hardening, runs integrity and foreign-key checks, validates schema objects and immutable hashes, verifies active pointers, reconciles reserved admissions and returns interrupted outbox claims to pending.

Reopen expands the compact archive, reconstructs the publication from source material and receipts, verifies proof witness and cross-object identities, and re-admits current trust before returning payload. Recovery performs durable-manifest checks before and after the read. A revoked head falls back to the newest prior unrevoked generation and reports the fallback.

Source retention remains separately fenced. Physical deletion remains fail-closed pending a reviewed GC transaction.

## 7. Named product composition

Library caller:

```text
memory.checkpoint-coordinator.v2
```

Native type: `MemoryCheckpointCoordinatorV2`.

Agentd caller:

```text
agentd.runtime.compaction-scheduler.v1
```

Native host: `AgentdCompactionCheckpointHostV1`.

The Agentd host composes the current production writer and checks its authority before lease, manifest, publication, recovery, revocation, retention and outbox operations. Product source composition is present; activation and target-host acceptance are not claimed.

## 8. Current test identities

- `src/qualified_tests.rs` — determinism, exact coverage, deletion/protected support and capacity boundaries.
- `src/trust_tests.rs` — signatures, subjects, nonces, epochs, rotation, revocation and historical validation.
- `src/durable_tests.rs` — schema/reopen, outbox recovery, immutability and artifact limits.
- `src/durable_fence_tests.rs` — lease replacement, stale manifest and NULL predecessor CAS regressions.
- `src/product_e2e_tests.rs` — public build→proof→atomic publish→restart→reconstruct→incremental successor path.
- `tests/capacity_profile.rs` — 65,536-record / 64-MiB / 8,000,000-token pure-kernel profile.

These paths are test identities, not pass receipts.

## 9. Qualification

The focused workflow runs from a clean read-only checkout in exact-head and deterministic synthetic-merge modes:

```bash
cd codex-rs
cargo fmt --all -- --check
cargo check --locked -p codex-hepta-compact-engine --all-targets
cargo test --locked -p codex-hepta-compact-engine --all-targets
cargo clippy --locked -p codex-hepta-compact-engine --all-targets -- -D warnings
```

Queued, pending, skipped, cancelled or failed work is not evidence. Capacity evidence must be bound to the same final source identity.

## 10. Remaining repository-controlled work

Before raising `productionImplementation`:

1. close every exact-head and synthetic-merge finding on the final SHA;
2. obtain terminal capacity receipts and a representative full publish/reopen target-host profile;
3. complete explicit crash/power-loss and migration rollback rehearsal on the final schema;
4. complete concurrent-writer, corruption, property and fuzz qualification not already covered by the focused suite;
5. implement and qualify separately reviewed fenced physical payload GC;
6. update exact-source evidence entries after the final immutable candidate is known.

## 11. External gates

Independent semantic reconstruction acceptance, production trust enrollment, operator acceptance, activation, canary, promotion, merge and release remain externally governed. A green repository run proves only the exact candidate tested by that run.
