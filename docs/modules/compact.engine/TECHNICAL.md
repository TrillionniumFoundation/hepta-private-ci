# compact.engine technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `compact.engine`

**Owner:** `cognitive-platform`

**Deputy:** `durability-kernel`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `MEM-5-COMPACT`

This stable document is the implementation guide for `compact.engine`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Create bounded compaction checkpoints without rewriting source facts.

The primary owner `cognitive-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `durability-kernel` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `engine`, state model `stateful` and architecture role `execution_plant` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-compact-engine`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-compact-engine`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The registered primary source remains [codex-rs/hepta-compact-engine/src/lib.rs](../../../codex-rs/hepta-compact-engine/src/lib.rs). The current crate exports the canonical `CompactCheckpointV1` / `CompactionProofV2` contracts plus `build_qualified_candidate` and `prove_compaction`; the historical `NATIVE_BINDINGS.json` observation that named the removed `CompactCheckpoint` / `compact` surface is not an exact-head API claim. Exact-head source and test identity comes from the CI-generated implementation evidence described in section 12. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/compact.engine.md#8-verification-and-claim-boundary) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/compact.engine.md) for the implemented subset and remaining product work.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `cognitive.read`
- `kernel.operations`

Authoritative write domains:

- `compact_checkpoint`

Explicitly denied capabilities:

- `source_fact_mutation`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The canonical checkpoint subsystem has one product chain:

`host-configured AuthoritativeCognitiveSnapshotProvider::acquire -> validated AuthoritativeSnapshotV1 -> host-trusted tokenizer evidence -> build_qualified_candidate -> host-trusted evaluator signature -> prove_compaction -> ProductionDurableWriter -> CognitiveStore immutable checkpoint + content-addressed payload`.

The bounded components are:

- the host-configured `AuthoritativeCognitiveSnapshotProvider`, which acquires the exact Lane C source cut at final use; requests carry only `SnapshotAcquisitionRequestV1` and cannot inject a pre-built envelope;
- the deterministic deletion/lineage core, which rejects broken revision chains and `Live -> Tombstone -> Live` resurrection;
- record, encoded-byte and token-budget selection with hard repository ceilings;
- `TrustedTokenizerV1` plus signed `TokenizationReceiptV1` for every selected input and semantic payload;
- `TrustedCompactionEvaluatorV1` plus an Ed25519-signed `CompactionQualificationV2` over the exact candidate and holdout outcomes;
- the immutable `CompactCheckpointV1` / `CompactionProofV2` metadata publisher;
- the content-addressed compact-payload owner and its separate immutable revocation/GC lifecycle;
- current-selection and rollback-candidate re-admission against a fresh authoritative cut.

Snapshot-provider, tokenizer and evaluator trust belong to Agentd host configuration. They are not request fields. A request may supply signed evidence, but it cannot choose the public key that authenticates its own evidence. The engine remains authority-free and does not call a model, mint production authority or mutate source facts.

The semantic payload contains its exact bytes as well as its digest, generator provenance, tokenizer identity and signed tokenization accounting. Publication binds those exact bytes to the checkpoint digest and persists them in the same CognitiveStore transaction. Digest-only output is not considered recoverable context.

Configuration affecting authority, tokenizer/evaluator identity, schema, compatibility, model identity or resource policy is immutable for one admitted operation/generation. Unknown critical fields, unbounded queues and implicit fallback stores are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::compact_checkpointV1`
- native `CompactionProofV2` qualification evidence binding

Consumed contracts:

- `DomainRead::cross_owner_outboxV1`
- `DomainRead::operation_ledgerV1`
- `ModulePort::cognitive.read::compact.engine`
- `ModulePort::kernel.operations::compact.engine`

Critical protocol schemas:

None.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domain:

- `compact_checkpoint`.

The physical owner remains the existing Agent-local CognitiveStore; compact.engine does not introduce a second database. Migration `0011_qualified_compact_checkpoints.sql` contains three related physical surfaces inside that one domain:

- `cognitive_qualified_compact_checkpoints`: immutable checkpoint/proof metadata, keyed by owner/scope/purpose/generation with generation/predecessor CAS;
- `cognitive_qualified_compact_payloads`: content-addressed payload bytes keyed by exact `payload_digest`, source snapshot and tokenizer identity; rows cannot be updated;
- `cognitive_qualified_compact_payload_revocations`: append-only revocation tombstones binding payload digest, tombstone frontier, authority epoch and revocation digest.

Publication holds the externally authorized writer lease, enters `BEGIN IMMEDIATE`, revalidates that lease/fence inside the transaction, verifies exact payload bytes against `checkpoint.payload_digest`, inserts or verifies the content-addressed payload, performs checkpoint generation/predecessor CAS, and commits checkpoint/proof metadata atomically. A conflict or crash before commit leaves the prior durable head selected and does not leak a newly usable payload.

Payload deletion semantics deliberately differ from checkpoint metadata. Revocation first appends an immutable tombstone; resolution then immediately returns no payload. Physical payload bytes may be garbage-collected only after that tombstone exists. Historical checkpoint/proof rows are retained so deletion does not destroy audit lineage, but historical metadata never makes a revoked/deleted payload usable again.

Store open verifies migration checksums, exact required table/trigger/index definitions, checkpoint/proof digests and predecessor continuity, owner identity, and content-addressed payload bytes. Corruption or schema tampering fails closed. Rollback never restores deleted payload bytes or expired authority.

## 7. Runtime, concurrency and transaction model

The named product façade is `AgentdProductionWriterHost`. `AgentdProductionWriterBootstrap` is the only runtime composition seam: it requires an externally verified production lease/verifier, deployment-enrolled tokenizer/evaluator trust, and a host-selected authoritative snapshot provider. `runtime.rs` composes that bootstrap against the already-open Agentd CognitiveStore and retains the host in `AgentdState`; without an explicit bootstrap the default runtime remains read-only. State exposes the host only while Agentd is Running, App Server ready and unfenced.

The publication call performs, in order:

1. final-use `AuthoritativeCognitiveSnapshotProvider::acquire` followed by `AuthoritativeSnapshotV1::validate_for_request`; caller-supplied snapshot envelopes are not accepted;
2. policy tokenizer == source snapshot tokenizer == host-trusted tokenizer;
3. Ed25519 verification of every input/payload tokenization receipt and exact byte/token accounting;
4. deterministic candidate construction over the complete authoritative memory head set;
5. Ed25519 verification of independent evaluator qualification over the exact candidate digest;
6. durable writer authority refresh and a second lease/fence validation inside SQLite `BEGIN IMMEDIATE`;
7. content-addressed payload publication plus immutable checkpoint/proof generation CAS.

Concurrent candidates may be computed, but SQLite serialization plus predecessor/generation CAS permits only one successor. Stable identical replay is idempotent; semantic drift under the same durable identity conflicts.

Read use is also a product boundary. `select_current_compaction_checkpoint` reacquires a fresh authoritative snapshot from the attached provider and and then requires the durable checkpoint to match the current memory, fact, tombstone, source-ledger, KG, prompt-registry, retrieval, encoder, authority, model, tokenizer, template, tool-schema, memory-snapshot and compatibility cut. It must also resolve the exact non-revoked payload bytes. There is no legacy read path that treats durable existence alone as currentness.

## 8. Failure semantics, recovery and rollback

Crash-before-commit leaves both the prior checkpoint and prior payload selection unchanged. Reopen reconstructs every persisted checkpoint/proof contract and verifies the durable predecessor chain before returning a head. Content-addressed payload corruption is detected by recomputing its digest.

A deletion/revocation race resolves fail-closed: once the payload tombstone commits, `resolve_qualified_compact_payload` and current selection stop returning bytes even if historical checkpoint metadata remains immutable. GC before revocation is rejected; after revocation it may remove only the payload bytes.

Current selection is never inferred from “latest row”. It requires final-use re-admission against the current authoritative cut and compatibility digest. Frontier, authority, model/tokenizer/template/tool-schema, source-memory digest, generation or payload-availability drift makes the checkpoint stale.

Rollback does not select an old checkpoint in place. `rollback_compaction_payload_candidate` may expose a historical payload only after current-cut re-admission and only while the payload still resolves. The caller must then construct, independently qualify and publish a new successor generation through the normal canonical path. Deleted/revoked payloads, stale authority and stale compatibility cannot be resurrected by rollback.

## 9. Security, privacy and threat controls

The posture is least authority, bounded input, typed contracts, digest binding and independently authenticated evidence.

Tokenizer accounting is not caller self-report. `CompactionPolicyV2` binds tokenizer semantic identity and implementation digest; `TrustedTokenizerV1` is host-enrolled; every `TokenizationReceiptV1` is Ed25519-signed over subject digest, tokenizer identity/implementation and exact byte/token counts. Policy tokenizer, snapshot tokenizer and trust-root tokenizer must be identical.

Independent semantic qualification is also cryptographically authenticated. `TrustedCompactionEvaluatorV1` is host-enrolled; `CompactionQualificationV2` signs the exact candidate digest, evaluator implementation/attestation, evaluation artifact, retained-query/reconstruction/contradiction evidence and all pass/fail outcomes. `prove_compaction` verifies that Ed25519 signature itself and derives the proof's signature and verification-receipt digests. A non-zero digest or caller boolean is not proof.

Production authority remains separate. The engine and proof artifacts are `DENY_ALL`; only the externally verified `ProductionDurableWriter` may publish/revoke/GC. The tokenizer/evaluator keys do not grant write authority, and the production authority verifier cannot substitute for semantic qualification.

Negative tests cover resurrection, stale/missing protected support, forged tokenization receipts, tokenizer substitution, payload-byte drift, evaluator-signature tampering, stale current cuts, revoke/GC ordering, lease/fence drift, concurrent generation conflicts and persisted corruption. Credentials and raw trust secrets never enter general logs, learning artifacts or checkpoint metadata.

## 10. Performance, capacity and hot-path policy

Canonical hard source limits are:

- at most 65,536 input revisions;
- at most 4,096 protected references;
- at most 64 MiB for bounded encoded compaction input/output;
- at most 8,000,000 tokenizer-counted tokens.

Each policy may choose stricter retained-record, retained-byte, retained-token, semantic-payload-byte and semantic-payload-token ceilings, but may not raise the repository hard ceilings. Every byte/token figure admitted by the engine is bound to a signed tokenizer receipt. Protected live references must fit all active budgets or planning fails instead of silently omitting them.

The current 4,096-record deterministic regression is a source capacity fixture, not a latency/SLO claim. Target-host qualification must separately measure CPU, RSS, SQLite transaction/reopen cost, payload resolution, p50/p95/p99 and foreground interference on the selected host.

## 11. Observability and operations

Keep checkpoint generation/predecessor, source snapshot, source-memory digest, support manifest, omissions, resource accounting, generator provenance, tokenizer identity, evaluator provenance, qualification proof, payload digest and deletion frontier queryable for every publication.

The compacted payload body is not embedded in checkpoint JSON. It is separately content-addressed in the same CognitiveStore so it can be revoked and garbage-collected without rewriting historical checkpoint/proof evidence. Operational reads distinguish: metadata present, payload live/resolvable, payload revoked, payload GC'd, and checkpoint stale against current cut.

Current operating/state references:

- `codex-rs/hepta-compact-engine/src/qualified.rs` — canonical planning/trust/proof kernel;
- `codex-rs/hepta-memory/src/qualified_compact_store.rs` — checkpoint, payload, revocation, resolver and re-admission owner;
- `codex-rs/hepta-memory/migrations/0011_qualified_compact_checkpoints.sql` — physical schema;
- `codex-rs/hepta-memory/src/production_writer.rs` — externally authorized publish/revoke/GC boundary;
- `codex-rs/hepta-agentd/src/production_writer_host.rs` — named product façade and trust root.

Replay scheduling and learned-skill induction remain separate capabilities; checkpoint subsystem closure does not imply them.

## 12. Verification and qualification

Current focused source tests include:

- `hepta-compact-engine/src/qualified_tests.rs`: deletion non-resurrection, complete-source coverage, deterministic ordering, protected-reference behavior, record/byte/token budgets, hard bounded regression, signed tokenizer receipts, policy/snapshot tokenizer equality, exact semantic payload bytes and host-trusted Ed25519 evaluator verification;
- `hepta-memory/src/qualified_compact_store_tests.rs`: idempotent publication, content-addressed payload reopen/resolution, generation/predecessor CAS, concurrent same-generation winner, exact-current-cut selection, revocation-before-GC, rollback-candidate re-admission, crash-before-commit, raw proof-signature replay/tamper rejection, bounded checkpoint-capacity stop, and schema/data corruption fail-closed behavior;
- `hepta-agentd/src/production_writer_host_tests.rs`: full authoritative snapshot -> signed tokenizer -> build -> signed evaluator -> prove -> authorized durable publication -> current re-admission -> restart payload-resolution path, plus missing-host-trust rejection;
- `hepta-cognitive-types/src/lane_c_tests.rs`: canonical checkpoint/proof contract digest invariants.

Tracked `IMPLEMENTATION_MAP.sourceBase` is a relevant-source baseline, not an “exact HEAD” claim: the verifier requires that it is an ancestor whose declared module roots/guide/dossier/common mapping inputs have no drift. The map file itself is excluded to avoid self-reference. **Exact-head evidence** means the CI execution receipt records the actual source-head commit/tree being compiled and tested; **synthetic-merge evidence** records the deterministic merge commit/tree. These are distinct concepts and must not be conflated.

`cognitive_qualified_compact_checkpoints` is bounded to 16,384 immutable rows per owner. Identical replay remains valid at the bound; a new successor at capacity returns `CapacityExceeded` rather than misclassifying a healthy store as corruption. This is an explicit bounded-stop state, not silent truncation or automatic audit-lineage deletion.

Source completion requires both source-head and deterministic synthetic-merge compile/test/lint/format gates to reach terminal success. Target-host qualification, independent semantic acceptance, activation, promotion and release remain later external gates.

## 13. Implementation sequence and work packages

Applicable work package: `MEM-5-COMPACT`.

The exact cross-owner convergence envelope is canonical in `docs/delivery/WORK_PACKAGES.json`. It explicitly includes the compact-engine root plus the bounded Lane C contract, CognitiveStore migration/store/writer, Agentd product-host, caller-registry, compatibility tests and documentation/evidence tooling touched by this convergence. Co-owner modules are `cognitive.types`, `cognitive.store`, `runtime.agentd`, `runtime.codex` and `context.compiler`. This replaces the former inaccurate statement that MEM-5 could modify only `hepta-compact-engine/**`.

Development predecessor remains `MEM-0-TYPES`; activation predecessor remains `MEM-1-STORE`. The work package is still `planned` in the canonical delivery state until exact-candidate gates justify a state transition. Source code existing on a PR does not by itself update delivery/activation/acceptance state.

Required source deliverables remain exact source identity, source inventory, static verification, focused/package tests, all-target compilation, strict lint, clean tracked state, exact-head execution and merge-candidate execution. Cross-owner writes outside the explicit envelope remain a stop condition.

## 14. Activation, compatibility and retirement

The single canonical product façade is `AgentdProductionWriterHost`; #959's parallel production-event-journal / publish-only host topology is retired. The canonical durable owner is the qualified checkpoint/payload tables in the existing CognitiveStore.

Source composition does not mean runtime activation. Default Agentd startup still does not mint a production writer or semantic trust root. Activation requires an external production authority lease/verifier plus deployment-enrolled tokenizer/evaluator trust identities and successful target-host qualification.

Compatibility adapters must not recreate the removed legacy `compact()` checkpoint surface. Retirement requires all named callers on the canonical path, no old-path use, current-cut re-admission, restart/reopen qualification, rehearsed rollback-as-new-successor behavior and independent acceptance.

## 15. Definition of module completion

Documentation completion requires this guide, canonical registry/work-package truth and closed-world validation. Checkpoint-subsystem source completion requires the canonical engine, trust contracts, durable payload owner/resolver, current/rollback re-admission and named product call chain to compile/test at exact source head and deterministic synthetic merge.

Product composition means the named Agentd façade actually traverses authoritative snapshot -> build -> prove -> durable publication and exposes final-use re-admission; a store method or test helper alone is not composition. Product execution is not claimed until exact-candidate execution evidence passes.

Replay scheduling and skill induction are later target capabilities and do **not** block checkpoint-subsystem source closure. Independent semantic acceptance, target-host qualification, activation, canary, promotion and release remain separate externally governed states.

For `compact.engine`, source changes grant no runtime/model/provider/network/filesystem/secret/release authority. The engine/proofs remain `DENY_ALL`; durable mutation exists only through the externally authorized production writer.

### MEM-5-COMPACT execution envelope

- State: `planned`; priority: `3`; parallel class: `contract_coordinated`.
- Owner/deputy: `cognitive-platform` / `durability-kernel`.
- Canonical allowed paths and co-owners: see `docs/delivery/WORK_PACKAGES.json`; that machine-readable row is authoritative.
- Development predecessor: `MEM-0-TYPES`; activation predecessor: `MEM-1-STORE`.
- Stop conditions remain authority violation, base drift, claim/evidence mismatch, writes outside the explicit cross-owner envelope, and unbounded resource/retry behavior.

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `compact.engine` to primary lane `LANE-C-MEMORY`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-EMB`](../../readiness/EMBODIED_RUNTIME_EXECUTION.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The bootstrap source-location obligation for `compact.engine` is implemented by work package `MEM-5-COMPACT` in:

- `codex-rs/hepta-compact-engine`

The source candidate is checked by `.github/workflows/hepta-consolidated-source.yml`, including closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state. This receipt is source implementation evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
