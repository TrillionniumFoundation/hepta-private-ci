# objective.compiler technical development guide

<!-- BEGIN GENERATED OBJECTIVE.COMPILER STATUS -->
## Generated source-state status

This block is generated from `docs/modules/objective.compiler/CURRENT_STATE.json`. The manifest contains static source and policy facts only. Exact source-head, synthetic-merge and target-host observations are never hand-maintained here; they are emitted by the receipt-bound evidence projection named below.

- Manifest SHA-256: `14bc95a145f63da905593f3022ecb309dbd1d6094f0bd9912871a52fe35e47a2`
- Core: `source_complete`
- Product composition: `source_composed_durable_proof_bound_not_activated`
- Semantic hardening: `source_complete_pending_exact_candidate_receipts`
- Qualification evidence policy: `dynamic_receipt_projection_required`
- Independent acceptance: `external_receipt_required`
- Canary/promotion/rollback: `source_policy_not_activated`
- Dynamic projection schema: `hepta.objective-evidence-projection.v2`
- Dynamic projection producer: `scripts/hepta-objective-evidence-project.py`
- Manual dynamic pass fields: `forbidden`

| Source claim | Value |
| --- | --- |
| `productionImplementation` | `false` |
| `accepted` | `false` |
| `activated` | `false` |
| `released` | `false` |

### Dynamic claims projected only from artifacts

- `sourceHeadQualification`
- `syntheticMergeQualification`
- `targetHostMeasurement`

### Required repository checks

- `Hepta objective admission qualification`
- `Hepta objective product composition / source-head`
- `Hepta objective product composition / synthetic-merge`
- `Hepta Lane D semantic conformance`
- `objective.compiler current-state projection`
- `Agentd objective product E2E`
- `strict objective clippy`
- `objective release guard`

### External evidence gates

- selected deployment target-host measurement and resource-policy acceptance
- independent semantic and security review
- operator acceptance
- canary observation
- promotion approval
- rollback authority validation
- release authority approval

<!-- END GENERATED OBJECTIVE.COMPILER STATUS -->

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `objective.compiler`

**Owner:** `intelligence-platform`

**Deputy:** `kernel-contracts`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `OBJ-0-OBJECTIVE-CONTRACTS`

This stable document is the implementation guide for `objective.compiler`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Freeze each request into an immutable objective revision with explicit success predicates and hard constraints.

The primary owner `intelligence-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `kernel-contracts` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `compiler`, state model `stateless` and architecture role `objective_compiler` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-objective`

Existing declared roots at this exact source snapshot:

- `codex-rs/hepta-objective`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate. Closed-world inventory, focused tests, all-target compilation, strict lint and exact-head qualification remain required checks; their existence is not a current pass receipt. A pass claim must identify the exact source/tree, workflow/run, observed result and artifact evidence described in [DELIVERY_EVIDENCE.md](DELIVERY_EVIDENCE.md). Missing, queued, interrupted or failed execution is not passed. This status does not activate `objective.compiler`, create a production caller, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

### Current source change and evidence boundary

The ordinary source path identified in [DELIVERY_EVIDENCE.md](DELIVERY_EVIDENCE.md) keeps the existing Agentd/intelligence/destination-journal ownership chain. Agentd now freezes one `ValidatedAdmissionProfileV1` at host open and reuses only its static validation, indexes, exact digest, revision and compiler-contract identity. Every request still rechecks authenticated source identity, principal scope, intent/schema/normalization digests, freshness and deadline; final use still rechecks trust, generation and fence. The Rust regression tests and measurement harnesses are source artifacts, not execution receipts. Versioned durable admission-proof recovery is implemented on the existing RunStart owner path (see the lifecycle contract below). Exact-candidate execution, selected deployment-host acceptance and independent acceptance remain receipt-bound gates. Canonical accepted/activated/released state is not changed by this guide.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`
- `cognitive.read`

Authoritative write domains:

None.

Explicitly denied capabilities:

- `runtime_objective_rewrite`
- `hard_constraint_mutation`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- `input normalizer`
- `constraint validator`
- `deterministic compiler`
- `digest and receipt emitter`

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

### Multiscale DecisionCell integration target

Keep one immutable external task objective and legal action boundary for a cooperating organ and its cells. Local preferences, predicted confidence or trainable critics may change allocation, not redefine success. Joint action/parameter controls consume the declared inference/training/evaluation budget.

Required targeted tests: local reward goal drift, unsupported action classes, shared budget double charging and immutable objective revisions.

The shared contract and record design are in
[DecisionCell mechanics](../../learning/NEURAL_BIOMIMICRY_SPEC.md);
[organ composition](../../cns/TECHNICAL.md) defines the stable outer boundary.
This target does not change the current native implementation, source status or
product/activation evidence recorded below. No existing wire version is redefined.

## 5. Contracts, ports and compatibility

Produced contracts:

- `ModulePort::objective.compiler::intelligence.control`
- `ObjectiveFunctionV1`
- `RunStartSnapshotV1`
- `ObjectiveRunExecutionBinding`

Consumed contracts:

- `ModulePort::cognitive.read::objective.compiler`
- `ModulePort::platform.types::objective.compiler`

Critical protocol schemas:

- `ObjectiveFunctionV1`
- `RunStartSnapshotV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

`ObjectiveFunction` has two deliberately separate identities. `ObjectiveFunction::semantic_digest` is the compact owner-native compiler identity used by `RunStartSnapshotV1.objectiveDigest`; the product facade now uses `encode_proof_bearing_objective_function_v1` on the opaque result of `compile_authoritative_objective_v1`. The encoder rebinds the complete source-envelope and frozen-profile identity, retains native/source/receipt validation and materializes the registered canonical JSON `ObjectiveFunctionV1` with its separate protocol-wire digest without a second native compilation. `encode_authenticated_objective_function_v1` remains the compatibility entrypoint for separate receipts and independently repeats authenticated admission and compilation. The crate-private encoder is not a caller-controlled bypass. `decode_objective_function_v1` validates exact canonical bytes plus semantic uniqueness, ordering, intrinsic-abstain, allowed/forbidden disjointness and soft-weight bounds. New durable run-start V3 records bind both byte strings and both digests plus the complete canonical admission proof. V1/V2 records remain readable without proof synthesis, but Agentd refuses them at final use; current profile/revision/compiler-contract and live authorization are separately checked. For a compiled compatibility-path run, `ObjectiveStart` also returns an optional `ObjectiveRunExecutionBinding` copied from the daemon-owned durable record. The binding contains only the exact request/objective/body/artifact/authority/generation/fence/deadline identity needed by a trusted execution owner to attach independently produced context; it grants no effect authority. Test sources cover source/profile/context drift, duplicate or reordered wire identities, unknown/non-canonical JSON, native/protocol digest separation, maximum bounds and durable revalidation. Their execution remains exact-candidate evidence. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

None.

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/objective.compiler.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and lock/transaction boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/objective.compiler.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/objective.compiler.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/objective.compiler.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `objective_substitution`
- `success_predicate_downgrade`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/objective.compiler.md) specifies this module's algorithm, admission-safe aggregate ceilings and capacity fixtures. The exact Source-V1-to-native support boundary is recorded in [`SEMANTIC_SUPPORT.md`](SEMANTIC_SUPPORT.md); syntactically accepted source operators that lack a lossless native representation are deterministic rejections, not implemented compiler semantics. Target ceilings are not measured latency. Current native limits belong to [codex-rs/hepta-objective/src/objective_admission.rs](../../../codex-rs/hepta-objective/src/objective_admission.rs), [source_envelope_validation.rs](../../../codex-rs/hepta-objective/src/source_envelope_validation.rs) and the linked implementation components. The executable named-host procedure is [OBJECTIVE_TARGET_HOST_MEASUREMENT.md](../../readiness/OBJECTIVE_TARGET_HOST_MEASUREMENT.md) with recorder `scripts/hepta-objective-target-measure.py`; ordinary admission/compile and maximum-conflict extraction are measured separately.

Removing a repeated native solve and constructing the validated profile once per `ObjectiveRuntimeHost` generation are source-level optimizations, not measured speedups. The reuse key binds the exact profile digest, profile revision and compiler-contract digest. It deliberately excludes source authentication, clock state, deadline, revocation, generation, fence and effect grants. The named-host recorder separately reports cold profile validation, warm authenticated admission, native compile, protocol encode/decode, maximum-conflict extraction and observable product boundaries. The atomic destination-owner append/checkpoint/Agentd-handoff boundary is reported as one boundary rather than split into invented timings. Stage-level and selected-host observations remain required as specified in [DELIVERY_EVIDENCE.md](DELIVERY_EVIDENCE.md).

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Stateless compiler/admission library with a named product-source composition in Agentd. `ObjectiveRuntimeHost::open` validates and freezes the immutable owner-local profile once for that process generation. `ObjectiveRuntimeHost::submit` authenticates each signed structured request against current AuthBus trust, derives the request-local admission context/generation/fence, and calls `compile_and_publish_validated_objective_run_v1`; the destination-owned `DurableRunStartStore` synchronously persists the admission binding, native semantic bytes, canonical protocol bytes and `RunStartSnapshotV1` before a non-abstain run reaches `AgentRunCoordinator`. The store rotates bounded segments, compacts only complete expired sealed prefixes, and binds every append and compaction transition by CAS to an independent monotonic checkpoint file outside the Agent-home rollback domain. Agentd requires `--objective-profile-file` and `--objective-checkpoint-file` together; the checkpoint owner uses a private sidecar writer lock and atomic replace on Unix. Restart recovery rejects missing, stale, wrong-binding or ahead-of-local checkpoints, reconciles acknowledgement loss, and revalidates retained signatures against current trust. A compiled fallback admission exposes the exact daemon snapshot through `ObjectiveRunExecutionBinding`; the trusted worker must attach its context/envelope, obtain current final-use authority, durably commit dispatch, perform exactly one physical App Server turn, and publish the observed terminal state back to that same Agentd run. Exact durable retry returns the stored observation without a second provider send. The compiler still owns no daemon or private objective database. This is source composition, not deployment activation. Unsupported language, resource exhaustion and infeasibility remain different outcomes; changing goal semantics requires a new authorized revision.

Current operating and state-format references:

- [docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md](../../readiness/OBJECTIVE_COMPILER_EXECUTION.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-objective/src/compiler_tests.rs](../../../codex-rs/hepta-objective/src/compiler_tests.rs); named case: `compilation_is_permutation_invariant`.
- [codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs](../../../codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs); named case: `all_three_action_graphs_match_truth_table_and_have_minimal_conflicts`.
- [codex-rs/hepta-objective/src/objective_function_v1_strict_tests.rs](../../../codex-rs/hepta-objective/src/objective_function_v1_strict_tests.rs); authenticated projection rebinding, wire uniqueness/order, intrinsic abstain, disjoint actions, capacity and microsecond-deadline projection.
- [codex-rs/hepta-objective/src/proof_projection_tests.rs](../../../codex-rs/hepta-objective/src/proof_projection_tests.rs); opaque-projection parity against independent recompilation, metadata/intent/profile substitution, per-request authentication/freshness rejection, hard-conflict rejection and explicit-abstain preservation.
- [codex-rs/hepta-agentd/src/objective_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/objective_runtime_tests.rs); signed ingress, replay frontier, product capacity identity, conservative deadline final use, explicit revoked/stale owner-trust recovery rejection, generation/fence rejection and runtime handoff.
- [codex-rs/hepta-agentd/src/objective_run_start_checkpoint_tests.rs](../../../codex-rs/hepta-agentd/src/objective_run_start_checkpoint_tests.rs); private checkpoint creation/reopen, writer exclusion, binding checks, missing-witness rollback detection and Agent-home separation.
- [codex-rs/hepta-agentd/tests/objective_product_e2e.rs](../../../codex-rs/hepta-agentd/tests/objective_product_e2e.rs); real daemon signed ObjectiveStart, durable explicit-abstain terminal, compiled-run execution binding, context attachment, current final-use grant, one physical mock-provider App Server turn, terminal observation, exact retry without resend, process restart, checkpoint-frontier recovery, missing-witness startup rejection and structured target-host round-trip/restart measurement.
- [codex-rs/hepta-learning-ledger/src/run_start_tests.rs](../../../codex-rs/hepta-learning-ledger/src/run_start_tests.rs) and [run_start_store_tests.rs](../../../codex-rs/hepta-learning-ledger/src/run_start_store_tests.rs); durable append, exact replay, segment rotation, compacted-prefix recovery, checkpoint acknowledgement loss, rollback detection and semantic/protocol drift conflict.

In `codex-rs`, run `just test -p codex-hepta-objective`, plus the focused `codex-hepta-learning-ledger` run-start, `codex-hepta-intelligence` objective-run, `codex-hepta-agentd` objective-runtime and objective-checkpoint tests. `.github/workflows/hepta-objective-admission.yml` executes those owner/caller checks, the exact-source verifier and measurement-recorder self-test. `.github/workflows/hepta-lane-d-semantic-conformance.yml` supplies cross-platform Lane-D package checks; the consolidated source workflow also carries `codex-hepta-objective` in this candidate. These commands/workflows are invocations and exact-candidate evidence surfaces, not permanent pass receipts.

`.github/workflows/hepta-objective-exact-execution.yml` adds read-only execution on a fixed source and deterministic synthetic merge with actual per-command logs and incremental receipts. Each run also derives `evidence-projection.json` from the observed receipt; it never hand-edits canonical pass flags. `.github/workflows/hepta-objective-target-measurement.yml` records the named macOS qualification host separately and explicitly leaves selected deployment-host acceptance false. These workflows do not replace registry, Lane-D, independent acceptance, deployment-host or release gates. The old source-writing closure materializer is retired; the admission workflow no longer embeds a source-mutating artifact job. Normal source repairs are ordinary commits before qualification. Recorder unit tests exercise recorder behavior, not the Rust compiler or product runtime. Exact-source evidence interpretation is defined in [DELIVERY_EVIDENCE.md](DELIVERY_EVIDENCE.md).

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `OBJ-0-OBJECTIVE-CONTRACTS`
- `OBJ-1-OBJECTIVE-COMPILER`

The bootstrap package is `OBJ-0-OBJECTIVE-CONTRACTS`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

## 14. Activation, compatibility and retirement

Source composition now names Agentd's signed objective ingress and durable run-start owner path. Activation remains separate: the deployed Agentd identity, current AuthBus trust distribution, selected store/host profile, crash/restart/backpressure behavior and target-host performance receipts must be qualified before activation. Shadow/qualification callers and source-composed fixtures are not deployment evidence.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `objective.compiler`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `OBJ-0-OBJECTIVE-CONTRACTS`

- State: `source_implemented`; priority: `1`; parallel class: `contract_first_parallel`.
- Owner/deputy: `intelligence-platform` / `kernel-contracts`.
- Allowed write paths:
- `codex-rs/hepta-objective/**`
- `codex-rs/hepta-types/**`
- Development predecessors:
- `DOC-1-V8-SEMANTIC-UPGRADE`
- Activation predecessors:
- `DOC-2-DEFAULT-BRANCH-SELECTION`
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

#### `OBJ-1-OBJECTIVE-COMPILER`

- State: `source_implemented`; priority: `1`; parallel class: `contract_coordinated`.
- Owner/deputy: `intelligence-platform` / `kernel-contracts`.
- Allowed write paths:
- `codex-rs/hepta-objective/**`
- Development predecessors:
- `OBJ-0-OBJECTIVE-CONTRACTS`
- `MEM-0-TYPES`
- Activation predecessors:
- `P0.7B-B4-CALLSITE-PROOF`
- `OBJ-0-OBJECTIVE-CONTRACTS`
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

The canonical readiness overlay binds `objective.compiler` to primary lane `LANE-D-OBJECTIVE-VALUE`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)
- [`RDY-OBJ`](../../readiness/OBJECTIVE_COMPILER_EXECUTION.md)
- [`RDY-NDU`](../../readiness/NDU_SYSTEM_EXECUTION.md)

Owned readiness protocols:

- `ObjectiveCompileReceiptV1`
- `ObjectiveConflictReceiptV1`
- `ObjectiveConstraintSetV1`
- `ObjectiveSourceEnvelopeV1`

Consumed readiness protocols:

- `ParallelLaneEnvelopeV1`

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation evidence requirements

The bootstrap source-location obligation for `objective.compiler` is implemented by work package `OBJ-0-OBJECTIVE-CONTRACTS` in:

- `codex-rs/hepta-objective`

`.github/workflows/hepta-consolidated-source.yml` declares closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked-state checks for this source candidate. This paragraph records the implementation location and required evidence surfaces; it is not an execution receipt. An actual current-source pass must be obtained from the exact candidate's recorded run and artifacts. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.


### RunStart rotation writer fence (2026-09-25)

The destination-owned segmented store now retains a directory writer lease
across active-file close/rename/create and compaction. Same-process and
cross-process regression probes must reject a competing writer at those cuts;
reopening after the original owner exits preserves the exact run and chain.
Compacted summary count/length validation precedes allocation. The authoritative
protocol and retained-index capacity boundary are specified in
`../../readiness/OBJECTIVE_COMPILER_EXECUTION.md`; neither a passing local test
nor filesystem metadata grants target-host acceptance or activation.

## Admission-proof persistence and recovery contract (2026-09-29)

`ObjectiveAdmissionProofV1` remains privately constructed by authoritative
admission. Its read-only `canonical_bytes()` export uses the same encoding
helper as proof issuance: domain `hepta.objective.admission-proof.v1`, followed
by five 32-byte digests in source-envelope, profile, authenticated context,
compiler-contract and admitted-source order. The canonical proof has 192 bytes;
its digest is SHA-256 of exactly those bytes. Export does not re-admit, re-solve,
cache authorization or create a constructor for the opaque compiler proof.

The intelligence facade places that evidence in the existing RunStart
transaction as `RunStartAdmissionProofV1`. This historical integrity wrapper
has private bytes and rejects unknown versions, zero component identities,
wrong length, trailing bytes and digest drift. It is deliberately not the
opaque compiler capability and cannot be converted into one. New run-record
V3 and conflict-record V2 payloads contain the proof digest and canonical bytes
immediately after `admitted_source_digest`; their normal frame digest, predecessor
chain, external checkpoint and publication acknowledgement bind the added
224 bytes. Profile and admitted-source identities must also match the enclosing
admission. There is no additional proof database or independent proof authority.

Old run V1/V2 and conflict V1 payloads decode with an absent proof. Re-encoding
preserves their version and byte identity. New append validation rejects an
absent proof; it does not retrofit old evidence. Inspection/replay-frontier
recovery remains possible, but runtime admission requires a proof, the current
profile and compiler contract, and all existing live trust/deadline/generation/
fence checks. An authorized new revision or request is required for migration;
recovery never manufactures one. Exact retries use the original durable proof,
not a proof recomputed with a later clock. Expired compacted payloads are not
reconstructed from summary indexes; surviving payloads retain their exact
proof and record identities.

Regression coverage is indexed in `CLOSEOUT_20260929.md`. Test source is not a
passing execution receipt; all acceptance and activation claims remain external.
