# compact.engine: implementation design

Parent: `docs/modules/compact.engine/TECHNICAL.md`. Lane: `LANE-C-MEMORY`.

Status: one canonical checkpoint-subsystem convergence path is source-composed on PR #943: host-configured authoritative snapshot provider acquisition -> host-trusted tokenizer receipts -> deterministic candidate -> host-trusted Ed25519 evaluator proof -> externally authorized durable writer -> immutable CognitiveStore checkpoint metadata plus content-addressed payload. Exact-head/synthetic-merge execution, target-host qualification, independent acceptance, activation and release remain separate gates. Replay scheduling and skill induction remain later target capabilities.

## 1. Source and cross-owner envelope

Owner-native root: `codex-rs/hepta-compact-engine`.
Canonical work package: `MEM-5-COMPACT`.
Durable owner: existing Agent-local CognitiveStore.
Named product façade: `AgentdProductionWriterHost`. Runtime composition seam: `AgentdProductionWriterBootstrap`, injected explicitly into `AgentdConfig`; default startup has no bootstrap and mints no authority/trust.

The bounded co-owner integration paths are recorded in `docs/delivery/WORK_PACKAGES.json`; they include `cognitive.types`, `cognitive.store`, `runtime.agentd`, `runtime.codex` and `context.compiler`. The compact engine owns compaction semantics, not a second database, execution spine or production authority.

#959's parallel production-event-journal / publish-only Agentd host is retired. The canonical physical topology is the qualified checkpoint/payload tables in the existing CognitiveStore.

## 2. Canonical public operations

Owner-native operations:

- `build_qualified_candidate(snapshot, memory_snapshot, generation, predecessor, policy, semantic_payload, trusted_tokenizer, inputs) -> QualifiedCompactionCandidateV2`;
- `prove_compaction(candidate, trusted_evaluator, signed_qualification) -> CompactionProofV2`.

Host/product operations:

- `AgentdProductionWriterHost::publish_compaction_checkpoint(request)` where the request contains only `SnapshotAcquisitionRequestV1`, never a snapshot envelope;
- `AgentdProductionWriterHost::select_current_compaction_checkpoint(request, compatibility)`;
- `AgentdProductionWriterHost::rollback_compaction_payload_candidate(generation, request, compatibility)`;
- `AgentdProductionWriterHost::revoke_compaction_payload(...)`;
- `AgentdProductionWriterHost::gc_revoked_compaction_payload(...)`.

The only checkpoint contract is `CompactCheckpointV1`. The legacy crate-local `CompactCheckpoint` / `compact()` surface is removed so deletion, lineage, resource and qualification invariants have no record-only bypass.

## 3. Source, deletion and deterministic selection

`AgentdProductionWriterHost` acquires one `AuthoritativeSnapshotV1` from its host-configured `AuthoritativeCognitiveSnapshotProvider` at final use; a request cannot provide its own envelope. The engine independently requires a complete `CognitiveSnapshot` head set for that source cut. Input identities must exactly cover current snapshot heads. Revision chains start at revision 1, are contiguous, and bind predecessor digests. Once a tombstone is observed, a later live revision is rejected. Tombstoned heads never enter retained context.

Protected IDs must exist. Protected live heads are ordered first; optional live heads are deterministic by retention priority and stable identity. Every retained/omitted source head contributes its signed resource-accounting identity to the support manifest.

Canonical hard ceilings are 65,536 input revisions, 4,096 protected references, 64 MiB of bounded encoded input/output and 8,000,000 tokenizer-counted tokens. Policy record/byte/token/payload limits may be stricter but cannot raise those ceilings.

## 4. Authenticated tokenizer and semantic payload

`CompactionPolicyV2` binds tokenizer semantic identity and tokenizer implementation digest. `TrustedTokenizerV1` is deployment/host configuration and must match the policy and source snapshot tokenizer exactly.

Each `CompactionInputRecordV2` carries a `TokenizationReceiptV1` signed with the host-enrolled tokenizer key over exact record digest, tokenizer identity/implementation, encoded bytes and token count. Changing the subject, tokenizer, implementation or accounting invalidates the signature.

`CompactionSemanticPayloadV2` carries the actual compacted bytes, their digest, generator implementation/receipt, source snapshot, source-memory snapshot, tokenizer and signed tokenization receipt. The engine checks `hash(payload_bytes) == payload_digest`, exact byte count, signed token count and active policy bounds. A digest without recoverable matching bytes is not a publishable canonical payload.

## 5. Independent Ed25519 qualification

`TrustedCompactionEvaluatorV1` is host-enrolled and contains evaluator identity, implementation digest, attestation digest and Ed25519 verification key. It is not a request field.

`CompactionQualificationV2` signs the exact candidate digest together with evaluator implementation, evaluation artifact, attestation, retained-query suite, reconstruction obligation, contradiction holdout and every pass/fail outcome. `prove_compaction` verifies that signature directly using the host trust root.

`CompactionProofV2` then binds checkpoint/candidate identity, evaluator identity/implementation, evaluation artifact, attestation, signature digest, engine-derived signature-verification receipt, retained-query/reconstruction/contradiction evidence, deletion cutoff and source/retained counts. Non-zero digests or caller-supplied booleans cannot substitute for signature verification.

The durable owner does not enlarge `CompactionProofV2` with storage-specific fields. Instead its internal proof image retains the enrolled evaluator public key and raw qualification signature as authority-free witness material. Every decode/reopen reconstructs `CompactionProofWitnessV1` and re-runs the exact engine Ed25519/signature-receipt verifier before returning the proof. Host enrollment remains the trust decision; persisted public verification material cannot grant authority.

## 6. Durable payload owner and publication transaction

Migration `0011_qualified_compact_checkpoints.sql` contains three physical surfaces in the existing `cognitive_1.sqlite3` owner:

- immutable `cognitive_qualified_compact_checkpoints` checkpoint/proof metadata;
- content-addressed `cognitive_qualified_compact_payloads` actual payload bytes;
- immutable `cognitive_qualified_compact_payload_revocations` tombstones.

`AgentdProductionWriterBootstrap` first composes the externally verified writer/trust/provider dependencies against Agentd's already-open CognitiveStore; `ProductionDurableWriter::publish_qualified_compact_checkpoint` then revalidates external production authority, derives the exact compact fence, and enters the CognitiveStore publisher. `AgentdState` exposes the composed host only while the daemon is Running, App Server ready and unfenced. Inside one `BEGIN IMMEDIATE` transaction the store revalidates the live lease/fence, rejects already-revoked payloads, verifies exact payload bytes/digest/provenance, inserts or validates the content-addressed payload, performs generation/predecessor CAS, writes the immutable checkpoint/proof row and commits.

Identical retries are idempotent. Reusing a generation/content address with changed semantics conflicts. Concurrent same-generation successors have one winner. Crash before commit leaves the predecessor current and does not expose a new payload.

Checkpoint metadata is intentionally bounded to 16,384 immutable rows per owner. The count is checked inside the same `BEGIN IMMEDIATE` transaction after idempotent-replay detection: an identical replay remains valid at the bound, while a new successor returns explicit `CapacityExceeded`. A healthy store at its designed capacity is therefore not mislabeled as corruption, and the owner never silently truncates immutable audit lineage.

## 7. Revocation, current selection and rollback

Revocation is logical before physical. `revoke_qualified_compact_payload` appends one immutable tombstone under the production writer lease/fence. From that commit onward, payload resolution returns unavailable. A SQLite `BEFORE DELETE` invariant rejects payload deletion without a matching revocation tombstone; `gc_revoked_qualified_compact_payload` may physically delete bytes only after that tombstone exists. Historical checkpoint/proof metadata remains immutable for audit lineage.

`select_current_qualified_compact_checkpoint` does not accept the latest row merely because it is durable. It re-admits the head against the current scope/purpose, memory/fact/tombstone/source-ledger frontiers, KG generation, prompt registry revision, retrieval/encoder profile, authority epoch, model/tokenizer/template/tool schema, source-memory snapshot digest, compatibility digest and current compact generation. It also requires the exact payload bytes to resolve and match their digest.

Rollback never reselects a historical checkpoint. `rollback_qualified_compact_payload_candidate` may return historical payload bytes only after current-cut re-admission and only if they remain non-revoked/resolvable. The caller must then build, independently qualify and publish a new successor generation through the canonical path.

## 8. Verification and claim boundary

- **Canonical engine entrypoints:** `build_qualified_candidate` and `prove_compaction` in [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs).

Named product-test designs:

- `COMPACT-01`: a `Live -> Tombstone -> Live` lineage is rejected on the only canonical builder path.
- `COMPACT-02`: protected live references survive deterministic record/byte/token selection, while missing or over-budget protected support fails closed.
- `COMPACT-03`: policy tokenizer, trusted tokenizer and source-snapshot tokenizer must match; forged or substituted tokenization receipts fail signature verification.
- `COMPACT-04`: semantic payload bytes, digest, tokenizer receipt, source snapshot and source-memory snapshot are all identical to the candidate-bound artifact.
- `COMPACT-05`: unsigned, wrong-key, tampered or wrong-attestation evaluator qualification cannot produce `CompactionProofV2`.
- `COMPACT-06`: authorized publish atomically persists payload/checkpoint/proof, survives reopen and resolves the exact content-addressed payload.
- `COMPACT-07`: concurrent same-generation successors have one CAS winner and crash before commit leaves the predecessor current.
- `COMPACT-08`: current selection and rollback-candidate resolution reject source/deletion/authority/model/tokenizer/compatibility drift and revoked or missing payloads.
- `COMPACT-09`: payload bytes cannot be physically deleted before an immutable revocation tombstone; after revocation the resolver fails closed and GC may remove bytes without rewriting historical metadata.
- `COMPACT-10`: schema/data corruption, unknown persisted fields, raw evaluator-signature witness tampering and immutable-trigger tampering fail store reopen; the bounded large-input fixture remains deterministic.
- `COMPACT-11`: the 16,384-row immutable checkpoint bound is an explicit `CapacityExceeded` stop for new successors, not a corruption diagnosis; identical replay remains admissible at the bound.

Current source tests cover:

- engine deletion/non-resurrection, complete-head coverage, protected references, deterministic selection, hard resource bounds, forged tokenizer receipt rejection, tokenizer substitution, semantic payload byte drift, evaluator signature tampering and a 4,096-record deterministic fixture;
- CognitiveStore idempotent publish/reopen, content-addressed payload resolution, predecessor CAS, concurrent writer race, current-cut drift rejection, revoke-before-GC, rollback candidate re-admission, crash-before-commit, raw proof-signature replay/tamper rejection, bounded-capacity stop and schema/data corruption;
- Agentd provider-acquired authoritative-snapshot -> trusted tokenizer -> engine -> trusted evaluator -> authorized writer -> current re-admission -> restart payload-resolution path, missing-trust/missing-provider fail-closed behavior, and runtime-bootstrap readiness gating.

Tracked `IMPLEMENTATION_MAP.sourceBase` is a relevant-source baseline: it must be an ancestor with zero drift in the mapped module roots/guide/dossier/common mapping inputs. It is not called exact-head evidence. Exact-head and deterministic synthetic-merge identities are emitted by CI from the actual tested commit/tree.

Remaining repository/evidence work before changing product-execution claims:

- source-head compile/test/strict-lint/format terminal success;
- deterministic synthetic-merge terminal success;
- crash/fault-injection coverage for payload insert -> checkpoint CAS/commit, revoke -> resolver, and reopen;
- deployed bootstrap enrollment plus target-host latency/RSS/SQLite/revalidation measurement;
- independent semantic review and deployment enrollment of concrete tokenizer/evaluator identities.

Checkpoint-subsystem closure does not require `plan_replay` or skill induction. Those remain later capabilities. Acceptance, activation, canary, promotion and release remain external and false.
