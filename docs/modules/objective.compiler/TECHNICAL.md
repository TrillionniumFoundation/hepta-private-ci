# objective.compiler technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `objective.compiler`

**Owner:** `intelligence-platform`

**Deputy:** `kernel-contracts`

**Lifecycle:** `target`

**Source status:** `existing_bound`

**Bootstrap work package:** `OBJ-0-OBJECTIVE-CONTRACTS`

This stable document is the implementation guide for `objective.compiler`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, exact-head qualification, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Freeze each request into an immutable objective revision with explicit success predicates and hard constraints.

The primary owner `intelligence-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `kernel-contracts` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `domain`, kind `compiler`, state model `stateless` and architecture role `objective_compiler` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `codex-rs/hepta-objective`

Existing declared roots at this source candidate:

- `codex-rs/hepta-objective`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact. It means the declared source root exists and is bound to this module; it does **not** itself prove focused tests, all-target compilation, strict lint, exact-head qualification or synthetic-merge qualification for the current candidate. Those are run-specific evidence and must be read from the exact candidate's qualification workflows.

The current source candidate contains a strict JSON decoder, structural/aggregate bounds, authenticated/profile-bound admission, a general feasibility solver, a V1 feasibility gate, deterministic native compilation, typed conflict/abstain outcomes, canonical `ObjectiveFunctionV1` projection and `RunStartSnapshotV1` binding. Two named source-level composition paths now exist: the learning-ledger-backed `codex-hepta-intelligence::prepare_intelligence_run_v1` path consumed by Agentd, and `codex-rs/hepta-agentd/src/objective_runtime.rs::admit_publish_and_start_objective_run_v1`, which publishes an immutable caller-owned objective/run envelope before bounded runtime admission. These source compositions remain deny-all and do not by themselves establish deployment activation, current exact-head qualification, target-host qualification, independent acceptance, promotion or release.

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

- strict source JSON decoder;
- structural and aggregate-capacity validator;
- authenticated/profile-bound admission mapper;
- profile-bound general-feasibility gate for V1 hard scalar atoms;
- deterministic native compiler with a legacy scalar defense-in-depth recheck;
- digest and receipt emitter.

The public V1 call graph is specified in [`docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md`](../../readiness/OBJECTIVE_COMPILER_EXECUTION.md). In particular, public admission runs `check_feasibility_v1` over the complete V1 hard scalar set (source hard constraints plus six generated resource constraints plus four generated risk constraints) before native compilation.

The general feasibility API supports scalar, finite-enum, action-implication and immutable-identity atoms. `ObjectiveSourceEnvelopeV1` is narrower: its hard-constraint row carries one Q32 bound and no enum-set or action-implication payload. The V1 source adapter therefore uses only the scalar subset. Rich solver capability must not be reported as rich V1 wire capability.

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state. Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Target produced contracts:

- `ModulePort::objective.compiler::intelligence.control`
- `ObjectiveFunctionV1`
- `RunStartSnapshotV1`

Consumed contracts:

- `ModulePort::cognitive.read::objective.compiler`
- `ModulePort::platform.types::objective.compiler`

Critical protocol schemas:

- `ObjectiveFunctionV1`
- `RunStartSnapshotV1`

Native `ObjectiveFunction` remains the deterministic owner IR rather than the public wire object. `project_objective_function_v1` now validates that IR against the admitted source and emits the exact canonical JSON projection registered as `ObjectiveFunctionV1`; `RunStartSnapshotV1::bind` binds that projection digest to the frozen run identity. `ObjectiveCompileReceiptV1` and `ObjectiveConflictReceiptV1` remain stable Rust aliases for the native typed receipts. Product persistence is caller-owned: the learning-ledger path publishes the canonical projection and run-start lineage through its authoritative ledger, while the Agentd objective runtime uses a narrow immutable file publication store with fsync and atomic no-replace publication.

Every eventual canonical producer must validate output before publication and bind semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Canonical wire round-trip, maximum-bound, unknown-field, canonical-ordering and digest-stability tests become mandatory before the canonical wire projection can be claimed complete.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

None.

The compiler itself is stateless and owns no objective database. The product owner that publishes an objective must atomically or transactionally bind the canonical `ObjectiveFunctionV1`, matching `RunStartSnapshotV1`, admission/compile receipts and reconciliation identity so no run observes an objective revision without its matching start snapshot.

The compiler still owns no durable store. Named caller-owned publication now exists in both the learning-ledger-backed intelligence path and the Agentd `ObjectiveRunFileStore` path. Both bind immutable objective/run identity before runtime admission, preserve identical replay, and reject semantic drift under a reused run identity. They are source-level product composition, not evidence of deployed activation or a new objective-owned database. Crash/restart, backpressure and latency on the selected target host remain qualification work.

For every future owned durable domain, the owner is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/objective.compiler.md#8-current-native-implementation) identifies the stateless compiler surfaces and the separate product-composition boundary. Use that implementation scope when composing the module; target state-machine operations are identified in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/objective.compiler.md).

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary. The compiler may not invent a durable transaction owner merely to satisfy a target contract.

## 8. Failure semantics, recovery and rollback

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/objective.compiler.md#8-current-native-implementation) and the module-specific fault cases in the [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/objective.compiler.md). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

`ObjectiveConflictReceiptV1` and `CompileDisposition::ExplicitAbstain` are non-error semantic outcomes. New read-only vertical callers can use `run_read_only_vertical_outcome_v1` so an objective abstain is represented as `ReadOnlyVerticalOutcomeV1::ExplicitAbstain` rather than telemetry that looks like a system failure. The legacy vertical error variant remains for compatibility.

`OBJ-E007` is a stable compatibility code, not a blanket retry instruction. Variant-specific retry guidance is defined in [`docs/contracts/OBJECTIVE_RETRY_POLICY.json`](../../contracts/OBJECTIVE_RETRY_POLICY.json) and exported as `ObjectiveRetryDirectiveV1`.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `objective_substitution`
- `success_predicate_downgrade`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

Current bounded V1 source capacity is tied to the actual lowered native capacity, not merely to per-array structural ceilings:

- source hard constraints: `<=246`;
- generated resource constraints: exactly `6`;
- generated risk constraints: exactly `4`;
- native hard-constraint aggregate: `<=256`;
- `successPredicates + terminalConditions + evidenceRequirements`: `<=128` aggregate;
- caller legal actions at the bounded V1 boundary: `0..=127`;
- compiled legal actions including intrinsic `abstain`: `<=128`;
- soft dimensions: `<=64`;
- feasibility oracle calls: `<=257`.

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/objective.compiler.md) specifies the algorithm and acceptance fixtures. Target ceilings are not measurements. The in-crate V1 feasibility gate is deterministic and call-bounded; host wall-clock/SLO measurements belong to the selected product host and may not change semantic results.

The current admission profile-size guard still uses owner-local byte accounting rather than measuring an exact canonical profile wire encoding. If the 256 KiB profile ceiling remains protocol-hard, the exact canonical profile encoding and its measured byte length must replace that parallel estimator before the boundary is called canonical wire enforcement.

The executable target-host procedure is [OBJECTIVE_TARGET_HOST_MEASUREMENT.md](../../readiness/OBJECTIVE_TARGET_HOST_MEASUREMENT.md), recorded by `scripts/hepta-objective-target-measure.py`; ordinary admission and maximal conflict extraction are measured separately.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

`objective.compiler` is a stateless compiler/admission library. Embed it at a request boundary; do not deploy a private objective database or infer product persistence from the library.

The current candidate has named source consumers at `codex-hepta-intelligence::prepare_intelligence_run_v1`, `codex-hepta-agentd::start_intelligence_run_v1`, and `codex-hepta-agentd::admit_publish_and_start_objective_run_v1`. The first path publishes through the sealed learning-ledger owner; the second consumes its deny-all host envelope; the third performs authenticated admission, immutable fsync+atomic publication and bounded AgentRunCoordinator admission directly in Agentd. These are source-composition facts only. Deployment still requires the authenticated ingress identity, target-host crash/restart/backpressure measurements and current exact-head/synthetic-merge qualification.

Unsupported language, hard infeasibility, availability/retry conditions and explicit abstention remain distinct outcomes. Changing goal semantics requires a new authorized revision.

Current operating and state-format references:

- [docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md](../../readiness/OBJECTIVE_COMPILER_EXECUTION.md)
- [docs/contracts/OBJECTIVE_RETRY_POLICY.json](../../contracts/OBJECTIVE_RETRY_POLICY.json)

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-objective/src/compiler_tests.rs](../../../codex-rs/hepta-objective/src/compiler_tests.rs); named case: `compilation_is_permutation_invariant`.
- [codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs](../../../codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs); named case: `all_three_action_graphs_match_truth_table_and_have_minimal_conflicts`.
- [codex-rs/hepta-objective/tests/admission_closure.rs](../../../codex-rs/hepta-objective/tests/admission_closure.rs); hostile aggregate-bound, zero-action abstain and public feasibility-conflict coverage.
- [codex-rs/hepta-agentd/src/objective_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/objective_runtime_tests.rs); publish-before-run, idempotent replay, semantic-identity conflict and durable explicit-abstain coverage.

In `codex-rs`, run `just test -p codex-hepta-objective`. The command is a test invocation, not a stored result. Inspect the exact-candidate output for passes, failures and skips.

A green historical PR or a test source in the tree is not current qualification. Source-complete claims require current exact-head plus synthetic-merge evidence under the repository's qualification policy. Product caller, independent acceptance, activation, promotion and release remain separate gates even when source qualification is green.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `OBJ-0-OBJECTIVE-CONTRACTS`
- `OBJ-1-OBJECTIVE-COMPILER`

The bootstrap package is `OBJ-0-OBJECTIVE-CONTRACTS`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned product packages may remain without invalidating documentation closure, but their absence must remain explicit.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, persistence, resource and failure behavior. Shadow, read-only and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root, registry/source agreement, candidate tests, exact-head evidence and merge-candidate evidence. Composition requires a named authenticated production caller and owner store. Canonical contract completion requires an exact `ObjectiveFunctionV1` projection and `RunStartSnapshotV1` persistence path. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion, activation and release are separate externally governed states.

For `objective.compiler`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `OBJ-0-OBJECTIVE-CONTRACTS`

- State: `planned`; priority: `1`; parallel class: `contract_first_parallel`.
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

- State: `planned`; priority: `1`; parallel class: `contract_coordinated`.
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

## 17. Source implementation receipt

The source location for `objective.compiler` is materialized in:

- `codex-rs/hepta-objective`

Repository workflows such as `.github/workflows/hepta-consolidated-source.yml` are expected to check closed-world inventory, package tests, all-target compilation, strict Clippy and clean tracked state for an exact candidate. Their existence is not a pass receipt; only the result attached to the exact candidate SHA is evidence for that candidate.

This source-location receipt grants no runtime, production-writer, canonical wire, durable owner-store, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
