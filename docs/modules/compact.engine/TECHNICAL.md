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

The registered primary source is [codex-rs/hepta-compact-engine/src/lib.rs](../../../codex-rs/hepta-compact-engine/src/lib.rs); observed identifiers include `CompactCheckpoint`, `compact`. This is a source navigation binding, not proof that every target operation or production consumer exists. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/compact.engine.md#8-current-native-implementation) alongside the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/compact.engine.md) for the implemented subset and remaining product work.

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

The bounded components are:

- `bounded input stage`
- `deterministic algorithm core`
- `generation publisher`
- `checkpoint and recovery layer`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Shared-experience and isolated-Agent integration target

Propose bounded semantic/procedural consolidation and replay plans without rewriting source evidence or becoming the trainer. Summaries keep support and permissions; distillation does not erase source lineage. Current facts, historical lessons and skill candidates have separate validity.

The target [HNMF contract](../../hnmf/TECHNICAL.md) and
[migration sequence](../../hnmf/MIGRATION.md#7a-shared-experience-delivery-through-existing-owners)
retain current source, wire and capability states.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::compact_checkpointV1`

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

Owned authoritative or rebuildable domains:

- `compact_checkpoint`

Read-only data dependencies:

- `cross_owner_outbox`
- `operation_ledger`

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/compact.engine.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/compact.engine.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/compact.engine.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/compact.engine.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

None.

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/compact.engine.md) specifies this module's algorithm, pilot ceilings and capacity fixtures. Those target ceilings are not measurements and must not be reported as enforcement of an unimplemented API. Current native limits belong to [codex-rs/hepta-compact-engine/src/lib.rs](../../../codex-rs/hepta-compact-engine/src/lib.rs) and the linked implementation components.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Checkpoint/projection library. Keep source lineage, omissions and deletion frontiers with every compact result and retain the prior complete generation on failed construction. A compact receipt does not implement the entire replay or learned-skill pipeline; lifecycle/storage publication belongs to the composed owner.

Current operating and state-format references:

- [codex-rs/hepta-compact-engine/src/lib.rs](../../../codex-rs/hepta-compact-engine/src/lib.rs).
- [codex-rs/hepta-compact-engine/src/qualified.rs](../../../codex-rs/hepta-compact-engine/src/qualified.rs).
- [codex-rs/hepta-compact-engine/src/candidate.rs](../../../codex-rs/hepta-compact-engine/src/candidate.rs).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-compact-engine/src/lib_tests.rs](../../../codex-rs/hepta-compact-engine/src/lib_tests.rs); named case: `latest_revision_and_tombstone_are_preserved`.
- [codex-rs/hepta-compact-engine/src/qualified_tests.rs](../../../codex-rs/hepta-compact-engine/src/qualified_tests.rs); named case: `protected_live_reference_is_retained_before_higher_priority_optional_record`.

In `codex-rs`, run `just test -p codex-hepta-compact-engine`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips. The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/compact.engine.md) separately labels target acceptance designs.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `MEM-5-COMPACT`

The bootstrap package is `MEM-5-COMPACT`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `compact.engine`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `MEM-5-COMPACT`

- State: `planned`; priority: `3`; parallel class: `contract_coordinated`.
- Owner/deputy: `cognitive-platform` / `durability-kernel`.
- Allowed write paths:
- `codex-rs/hepta-compact-engine/**`
- Development predecessors:
- `MEM-0-TYPES`
- Activation predecessors:
- `MEM-1-STORE`
- Required deliverables:
- `exact_source_identity`
- `source_inventory`
- `static_verification`
- `focused_tests`
- `package_tests`
- `all_target_check`
- `strict_lint`
- `clean_worktree`
- `exact_head_execution`
- `merge_candidate_execution`
- Stop conditions:
- `authority_violation`
- `base_drift`
- `claim_evidence_mismatch`
- `cross_owner_write`
- `unbounded_resource_or_retry`

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

## 18. Native API and adversarial audit scope

Source review updated **2026-10-01 (Asia/Shanghai)**. This section records native behavior and composition gaps; it does not record a passed test run. Sections 1–17 and the dossier's target replay/skill designs remain applicable.

### Callable surfaces and selection algorithm

| Native surface | Inputs and result | Implemented behavior |
| --- | --- | --- |
| `compact(generation, source_snapshot_digest, records)` | Complete per-record revision chains → legacy `CompactCheckpoint` | Validate and sort by record ID/revision; require revision 1, consecutive revisions and exact predecessor digests; retain the latest head, including tombstones. Reject a live successor after a tombstone. |
| `build_qualified_candidate(source_snapshot, generation, predecessor_checkpoint_digest, policy, inputs)` | `CognitiveSnapshotKeyV1`, `CompactionPolicyV2`, complete revision chains with retention metadata → `QualifiedCompactionCandidateV2` | Validate policy/lineage; reject absent protected IDs; separate tombstoned heads from selectable payload; retain every protected live head before optional heads; record live omissions, terminal tombstone digests and deletion counts. |
| `QualifiedCompactionCandidateV2::validate()` | Caller-visible candidate → integrity result | Revalidate contracts, resource bounds, live/unique retained records, disjoint unique retained/omitted/deleted digest sets, counts, payload/omission/support digests, nonzero selection-input commitment, tombstone cutoff and candidate digest. This is essential after transport or mutation of public fields. |
| `QualifiedCompactionCandidateV2::validate_against_inputs(policy, inputs)` | Structurally valid candidate plus frozen policy and complete input preimage → integrity result | Rebuild with the same source snapshot, checkpoint generation and predecessor, then compare the complete semantic candidate digest. Equivalent citation permutations remain valid. Reject a different protected set, retention decision, current-head reason/priority or source head as `CandidateSourceMismatch`; this verifies the supplied preimage, not its external authenticity. |
| `prove_compaction(candidate, qualification)` | Validated candidate and `CompactionQualificationV2` observation claims → Lane C `CompactionProofV1` | Require the exact `qualification.candidate_digest`, three nonzero obligation digests and four successful checks; bind the checkpoint, deletion cutoff and source/retained counts. It does not execute the checks or authenticate their producer. |

The qualified selector ranks live current heads by protected membership first, then descending `retention_priority`, then ascending record ID/revision. Input arrival order has no effect. There is no model call, generated prose summary, semantic merger, replay scheduler or skill induction in this crate. `algorithm_digest`, `compatibility_digest` and `retention_reason_digest` are caller-supplied labels; validating them does not attest an algorithm implementation or independently verify its declared rationale.

Both paths require the full supplied lineage from revision 1. A current-head-only reader cannot feed a revised record into these APIs without an explicit consumer-owned adapter or future authenticated predecessor contract. Do not silently relax lineage checks to make an incompatible reader work.

### Integrity bindings and trust limits

| Binding | Exact meaning |
| --- | --- |
| Legacy checkpoint digest | Domain `hepta.compact.checkpoint.v1`, generation, declared source snapshot digest and retained head digests; records are ordered by ID. |
| Policy digest | Domain `hepta.compaction-policy.v2`, policy ID, algorithm/compatibility digests, retention ceiling and sorted protected IDs. |
| Payload digest | Domain `hepta.compaction-payload.v2` and sorted retained live record digests. |
| Omitted-information digest | Domain `hepta.compaction-omitted.v2` and sorted omitted live record digests; deleted heads are excluded. |
| Support manifest digest | Domain `hepta.compaction-support-manifest.v3` and the sorted union of retained, omitted and terminal tombstone head digests. The live set is exactly the union of retained and omitted digests; the candidate's separate `deleted_record_digests` partition preserves deletion accounting. It is not an authenticated complete source ledger. |
| Loss report digest | Domain `hepta.compaction-loss-report.v2` and all eight counts; validation uses checked arithmetic and enforces protected counts as subsets of their corresponding populations. |
| Selection-input digest | Domain `hepta.compaction-selection-input.v1`, current-head count, then each head's record digest, priority as u64 and reason digest in ascending record-ID order, including tombstone heads. The owner must retain the exact input preimage to audit ranking; a nonzero commitment alone cannot reconstruct or verify the declared priority/reason. |
| Candidate digest | Domain `hepta.compaction-candidate.v3`, source vector, policy, selection-input commitment, checkpoint, loss report and the supplied retained/omitted/deleted sequences. Builders canonicalize order; validation binds the order actually supplied. |
| Lane C checkpoint/proof | The V1 types and digest encoders in [lane_c.rs](../../../codex-rs/hepta-cognitive-types/src/lane_c.rs) bind their declared fields and require `DENY_ALL`; they are separate from the legacy Rust checkpoint type. |

Checkpoint IDs include the complete source-vector digest and checkpoint generation to prevent same-generation identity reuse across snapshot scopes. The audit changes the unpublished local candidate's support/candidate digest domains to V3 while retaining the Rust `V2` type names. This is not in-place wire compatibility: no serialized wire contract or migration is implemented here, and consumers of old local candidates must rebuild them from authenticated source inputs.

Self-consistent digests do not establish source membership, complete input coverage, current deletion state, caller access or authentic ledger frontiers. `MemoryRecord` has no owner/fence/frontier field. The consumer must obtain the inputs and snapshot from one authenticated coherent read and revalidate current lineage/revocation before publication and every selection. Truncated input can otherwise describe an internally consistent but incomplete set.

The candidate stores policy and selection-input digests rather than their full preimages. `validate()` checks structural consistency; `validate_against_inputs()` re-runs policy membership and retention ranking against the supplied preimage. The owner retains the frozen `CompactionPolicyV2` and exact authenticated inputs, calls both checks before independent evaluation/publication, and revalidates current source/deletion state before selection. Rebuilding from a caller's invented but internally consistent preimage still does not authenticate a source or establish external completeness.

The qualification struct requires the exact candidate digest and carries a caller-supplied `evaluator_id`; the current proof assembler does not authenticate that evaluator or bind its identity into `CompactionProofV1`. The returned V1 proof preserves the checkpoint digest, not the complete candidate/policy/selection commitment; the independent receipt must retain those bindings alongside it. Three suite digests and four booleans are observation declarations. They must be backed by independently authenticated, candidate-specific execution receipts before a composed owner treats a checkpoint as qualified. This structural proof does not authenticate an execution observation or authorize source deletion, checkpoint publication, generation selection or promotion.

### Limits, errors and cost model

Native legacy and qualified input ceilings are 65,536 revision records; the qualified protected-ID ceiling is 4,096, and `maximum_retained_records` must be 1..=65,536. Both builders and imported-candidate validation preflight aggregate resources before record validation, hashing, sorting or cloning: at most 65,536 citations and 16 MiB of canonical record-preimage bytes plus 32 bytes per supplied omitted/deleted digest. Imported candidates also share one 65,536-head ceiling across all three partitions. Exceeding a ceiling rejects the whole request as `ResourceBudgetExceeded`; it never silently truncates. The byte profile counts the exact V1 record digest encoder, including domain, length-prefixed IDs, revision, kind/state, content digest, optional predecessor and each citation, and excludes repeated derived hash buffers. It is a payload ceiling, not a measured peak-RSS limit. Accepted payload digest encodings are unchanged. Raw `CompactionPolicyV2::digest` and `QualifiedCompactionCandidateV2::compute_candidate_digest` remain unchecked canonical hash helpers for bounded, trusted construction data; they are not admission APIs. Importers must use the validating entrypoints before invoking these helpers on caller-controlled vectors. The input ceiling counts historical revisions, while the retention ceiling counts live current heads. Empty input is structurally representable when no protected reference is requested; it does not prove an external store empty. Each record independently inherits cognitive-types citation and identifier bounds. These are metadata limits, not a compressed-byte ratio or a measured host budget.

| Rejection group | Consumer action |
| --- | --- |
| Invalid record/contract, zero required digest, broken or duplicate revision lineage, live resurrection | Reject the candidate; correct the source adapter rather than retrying the same semantics. |
| Invalid retention ceiling, too many inputs/protected IDs, protected references missing or exceeding retained capacity | Reject or plan a new bounded policy; do not drop required support. |
| Payload/support/omission/candidate digest drift, overlapping/duplicate live/deleted sets, accounting/cutoff/qualification-candidate mismatch, `CandidateSourceMismatch`, granted authority | Reject as an invalid candidate; never publish a partially validated object. |
| Failed retained-query, reconstruction, contradiction or deletion obligation | Preserve the previous selected generation; obtain a different candidate or independent corrected observation. |
| External reader/publication failure or uncertain durable outcome | No corresponding native durable operation exists; the composed owner must retain/reconcile its intent without inferring success from candidate construction. |

For `n` revision records and `p` protected IDs, construction performs bounded sorting/map/set work of order `O(n log n + p log p)` and uses `O(n + p)` metadata storage, including lineage and digest buffers. Candidate validation rehashes retained records and omitted/deleted digests; `validate_against_inputs()` performs an additional complete bounded rebuild and comparison with the same asymptotic cost. Digests reference content; raw source bodies are not loaded by this library. CPU, RSS, foreground interference, retained-query loss and storage reduction still require measurements on the selected host. The HNMF replay ceilings in the dossier describe a separate future scheduler.

### Actual project integration and remaining work

| Surface inspected | Current relationship to `compact.engine` |
| --- | --- |
| [hepta-compact-engine/Cargo.toml](../../../codex-rs/hepta-compact-engine/Cargo.toml) | Dependencies are bounded cognitive/types values and the existing learning-ledger evidence verifier. There is no operation-ledger client, SQL store or runtime adapter in this crate. |
| [hepta-memory cognitive_compact.rs](../../../codex-rs/hepta-memory/src/cognitive_compact.rs) | Defines a distinct `local_development_only` checkpoint/lease/summary/loss handshake; it is not an adapter for this crate's legacy checkpoint or Lane C candidate/proof. |
| [hepta-memory local_compact_executor.rs](../../../codex-rs/hepta-memory/src/local_compact_executor.rs) and [local_compact_hooks.rs](../../../codex-rs/hepta-memory/src/local_compact_hooks.rs) | Persist local lease-bound append-only intent/commit/rehydration witnesses. These qualification surfaces use hepta-memory's checkpoint and cannot be counted as native checkpoint publication/reload for this module. |
| [hepta-agentd qualification_writer.rs](../../../codex-rs/hepta-agentd/src/qualification_writer.rs) | Composes the existing local executor for qualification turn lifecycle. It does not call this crate's candidate builder/proof assembler, and its payload explicitly records `production_caller=false`. |
| [CALLERS.toml](../../../CALLERS.toml) and [IMPLEMENTATION_MAP.json](IMPLEMENTATION_MAP.json) | No named product callsite currently composes this module. The privileged caller registry is an authority inventory, not proof that a pure library is consumed. The implementation map retains `productionImplementation=false` and `productCallerState=not_composed`. |

Complete integration in the existing execution spine: add an authenticated coherent-read adapter with full lineage and protected coverage; retain the frozen policy/input preimage and call `validate_against_inputs()`; bind independent observations to the exact candidate; publish/reload through the declared `compact_checkpoint` owner with fenced intent, idempotency and revocation-aware selection; then compose a named caller and execute COMPACT-01..04 against that path. Existing hepta-memory stores must remain under their own owner; introducing a bridge requires explicit contract/owner coordination, not direct cross-owner writes or a replacement memory store. Replay scheduling and skill induction remain separate declared capabilities. Target-host qualification, independent acceptance and activation remain separate gates.

The 2026-10-01 adversarial regressions address legacy resurrection, missing protected input, forged payload/support/omission/deletion/accounting, arithmetic overflow, unbound qualification observations and checkpoint identity reuse across snapshots. Their source presence and this document are not execution receipts. Run the focused package checks and inspect their exact-candidate output before claiming source validation; product completion stays open until the integration above is executable and evidenced.

## 19. Owner lineage and authenticated observation stage

Source follow-up reviewed **2026-10-01 (Asia/Shanghai)**. This section describes callable code, not a production execution or independent acceptance receipt.

### Complete owner-read inputs

The existing SQLite physical owner now exposes `CognitiveStore::lane_c_lineage(access, scope, now)` through [lane_c_lineage.rs](../../../codex-rs/hepta-memory/src/lane_c_lineage.rs). `DurableCognitiveLineageObservation` has private fields and originates from the same transaction, authorization and complete ancestry validator as `lane_c_snapshot`. It preserves original revisions, predecessor digests and citations. It never resets a revised head to revision 1. The existing head-only API preserves its head-only projection for healthy inputs and avoids full-lineage capture. Every read now rejects corrupt metadata, head references and citation joins.

Eligibility applies to the **current head**. A verified live head within its validity window retains the whole chain; a terminal tombstone also retains its whole chain as deletion evidence. An unverified, expired or future live head excludes its entire chain, preventing an eligible historical ancestor from becoming a substitute current fact. The receipt records physical and excluded head counts and commits the complete physical head manifest, eligible ancestry, owner cut and observation time. The compact source domain is the eligible subset; it does not claim all physical heads were selected or all excluded sources were evaluated. Missing protected IDs still fail closed.

The read ceiling is 16,384 physical revision rows and 65,536 citations across all inspected revisions, with the existing source-row ceiling. Whole and paged reads check the physical owner's shared join keys and filter-column metadata globally, then scoped metadata, in the same transaction before fetching TEXT into Rust, rejecting oversized identifiers, malformed digest metadata and invalid verification/lifecycle values rather than filtering away corrupt rows. SQLite/index RSS and read latency remain target-host measurements. Citation sources must exist and match the authenticated owner/scope; a later database mutation cannot bypass provenance admission merely because initial open succeeded. Capacity failure rejects the whole cut. The SQLite schema currently projects only `MemoryKind::Fact`; no task or modality classification is inferred. `into_records()` moves the ancestry without another consumer clone. Use `owner_cut().bind_context()` to attach independently frozen external Lane C generations; the cognitive owner verifies its own frontier components and scope.

`revalidate_lane_c_lineage` reacquires the scope-authorized cut, rejects clock regression and checks physical-head/eligible-source bindings, including time-only eligibility transitions. It is a read boundary, not a publication transaction fence. A signed source binding should use `source_binding_digest()` so excluded physical heads and full ancestry remain committed. `observation_digest()` additionally binds the acquisition time. Authentication of other owners' generations remains a host obligation.

### Signed qualification and use-time revalidation

[authenticated.rs](../../../codex-rs/hepta-compact-engine/src/authenticated.rs) adds `compaction_qualification_payload_v1` and `prove_compaction_with_signed_evidence_v1`. The host supplies an existing `LearningEvidenceVerifierV1` obtained from its independently provisioned authority state; submitted evidence cannot choose the trusted keys. The module does not sign or activate trust.

The external signing payload uses `hepta.compaction.signed-qualification.v1`. It binds the candidate, source vector, owner-source cut, host scope/objective/authority epoch, policy, selection inputs, V1 proof and complete qualification observation. The latter binds evaluator identity, exact candidate, three suite digests and all four results. Admission requires separate Generator and Evaluator roles, verifies both signatures, matches the evaluator principal to `evaluator_id`, and uses the existing controller/key/credential/principal separation checks. Host scope/objective/epoch must match the submitted source authority binding, and the epoch must match the source vector. Scope-to-owner mapping is explicitly a host assertion: a StableId is not converted into an invented authority scope digest.

`AuthenticatedCompactionProofV1` is sealed with private fields. It retains the structural proof, full candidate/source/policy/selection/qualification bindings, original signatures, verified actor receipts and trust/authentication digests. `revalidate_for(candidate, current_source_cut, current_verifier, now)` rechecks the exact bindings, original signatures, current trust, expiry and revocation, and compares the complete reconstructed receipt. Old receipts fail after trust rotation. Its authority is always `DENY_ALL`.

Signatures authenticate declarations. They do not execute retained-query, reconstruction, contradiction or deletion tests, prove source completeness, authorize publication or select a generation. The compatibility `prove_compaction` API remains a structural assembler. A consumer must retain frozen policy/input preimages and run `validate_against_inputs`, obtain the current owner cut and current host trust, and use the signed API before treating observations as authenticated. SQLite-to-native-builder regression coverage is in [lane_c_lineage_tests.rs](../../../codex-rs/hepta-memory/src/lane_c_lineage_tests.rs); these tests are not a named production caller.

### Required durable composition

The authoritative `compact_checkpoint` writer remains `compact.engine` in [DATA_AUTHORITY.json](../../data/DATA_AUTHORITY.json). A future SQLite bridge may mechanically execute a compact-owned command; the cognitive owner and Agentd must not independently decide checkpoint publication. Existing `local_development_only` checkpoint types remain separate.

A complete durable stage must implement all of the following together:

- A sealed compact-owned command binding the frozen inputs, authenticated proof, exact source cut, scope/purpose, selected predecessor, adjacent generation and operation/payload identity.
- Same-transaction current source/eligibility verification under `BEGIN IMMEDIATE`, immutable generation receipt insertion, selected-pointer compare-and-swap and destination dedupe. Calling a separate read revalidator before a later write transaction leaves a deletion/correction race.
- The existing lifetime durable-writer fence and an exact compact-domain final-use grant held across the asynchronous transaction using the existing final-use authority. Learning signatures and ordinary cognitive-mutation capabilities are not publication grants.
- A restart-resolvable bounded format. Existing outbox payload JSON is capped at 65,536 bytes and store rows at 2 MiB; a 16 MiB source/candidate cannot be put in one envelope or row. A lower complete-command profile or bounded staged rows with a verified digest reference is required.
- Registered schema objects, recovery-schema oracle and complete recovery state digest, independent latest recovery witness, explicit selected-pointer reload, signature/source revocation checks and crash/CAS/rollback tests. Bootstrap must represent absent selected state separately from the Lane C vector's nonzero compact-generation placeholder.

Cold support must resolve exact omitted ID/revision/digest against the bound source and current owner eligibility. `latest_memory` alone checks authorization/decoding and is insufficient to admit a currently verified, live and valid cold reference. An updated, pending, expired or deleted head must not resurrect retained or omitted historical support.

Named production composition, independently executed COMPACT-01..04, target-host budgets, durable publication/reload/selection, replay scheduling and skill induction remain open. No product, deployment, acceptance, activation or release claim is changed by this source stage.

## 20. Sealed publication proposal admission

The source-only publication admission stage is implemented in [publication.rs](../../../codex-rs/hepta-compact-engine/src/publication.rs), with adversarial regressions in [publication_tests.rs](../../../codex-rs/hepta-compact-engine/src/publication_tests.rs). It creates an immutable typed proposal, not a durable publication receipt. No SQLite writer, selected pointer, outbox destination handler, final-use grant or restart codec is added.

`CompactionPublicationRequestV1` carries owner/scope/purpose and operation IDs, configured policy generation, expected selected state, the candidate, full frozen policy/input preimages and sealed authenticated proof. `CompactionPublicationContextV1` supplies independently obtained current owner/scope/purpose, policy generation and content digest, selected state, source cut, host verifier and use time. Matching declarations do not establish their external authenticity; host composition must derive them from the actual owners. Stable IDs are bounded identifiers, not agent credentials or writer capabilities.

`CompactionPublicationProposalV1::new` checks the namespace against both host context and the candidate's source vector, and requires both the current configured policy generation and nonzero content digest, and exact expected/current selection. It bounds input count and aggregate canonical bytes/citations before cloning for `validate_against_inputs`, then revalidates the original signed proof under current source/trust/time. The private proposal preserves the original typed candidate, policy, inputs and evidence; borrowed getters cannot mutate them. Its authority remains `DENY_ALL`.

Selection has two explicit states:

| Selected state | Admission rule |
| --- | --- |
| `Empty` | Candidate generation is 1 with no predecessor; the source vector's compact generation is the nonzero bootstrap placeholder 1. That placeholder does not mean a checkpoint already exists. |
| `Selected { generation, checkpoint_digest }` | Digest is nonzero; candidate generation is checked `generation + 1`; predecessor equals that exact digest; the frozen source vector names the same selected generation. Overflow, skipped generation, wrong predecessor or stale selection fails closed. |

`revalidate(context)` repeats admission with newly obtained host state before use. It detects changed selection, namespace, policy generation, source binding, expired evidence and trust rotation. A separate read followed by a later write remains racy: the durable writer must acquire current declarations and repeat these checks inside the same fenced transaction that validates source eligibility and performs selected-pointer CAS, dedupe and immutable receipt insertion. A valid proposal is not evidence that any of those effects happened.

The native semantic intent bytes are fixed-order binary identity bytes:

1. UTF8 domain `hepta.compaction.publication-intent.v1` followed by one NUL byte.
2. Owner, scope, purpose, fixed destination `compact.engine.checkpoint.publish.v1`, and operation IDs, each framed by its UTF8 byte length as unsigned u32 big-endian.
3. Policy generation as u64 big-endian; selected discriminator (`0` for Empty, `1` for Selected). Selected appends its generation as u64 big-endian and 32-byte checkpoint digest.
4. Candidate checkpoint generation as u64 big-endian, then eight 32-byte digests in order: candidate, checkpoint, source vector, owner-source cut, policy, current-head selection inputs, authenticated admission, structural proof.

The SHA256 of these exact bytes is `intent_digest()`. Four bounded IDs, a fixed destination and fixed-width fields keep the complete identity below 2 KiB. Use time is deliberately excluded, so retrying the same operation under unchanged valid owner/trust state preserves identity. Signed issuance/expiry and trust are already committed by the authenticated-proof digest and are rechecked at use. Input arrival order and other semantically equivalent preimages do not create different intent identities; this commits validated semantic bindings, not every raw field/order of a future body encoding.

These compact identity bytes are **not** the existing outbox's JSON payload and **not** a restart-resolvable body. A writer must freeze an exact bounded transport/body codec, hash the actual admitted JSON bytes for the existing operation/final-use payload binding, preserve or resolve every required preimage after restart, and compare both semantic identity and exact payload identity for dedupe. A digest-only envelope or process-local proposal cache cannot establish durable restart support. The small complete-command versus bounded immutable staged-row choices and all source/trust/fence/recovery requirements in section 19 remain open.
