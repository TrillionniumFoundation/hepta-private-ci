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

Non-authoritative implementation evidence roots: none. Declared roots not yet present: none.

`existing_bound` is a source-location fact. The source root is materialized and has focused tests and dedicated qualification workflows. It does **not** mean the current exact head or synthetic merge has passed every required workflow. Current readiness must be read from `docs/readiness/LANE_D_MATURITY.json` and exact-candidate CI; source completion cannot be inferred from historical PRs or an earlier sealed source receipt.

This status does not activate `objective.compiler`, create a production caller, materialize the canonical wire adapter, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `platform.types`
- `cognitive.read`

Authoritative write domains: none.

Explicitly denied capabilities:

- `runtime_objective_rewrite`
- `hard_constraint_mutation`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, or converting qualification evidence into deployment authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- bounded JSON decoder and structural validator;
- authenticated admission/profile mapper;
- native feasibility projection;
- registered feasibility engine and conflict minimizer;
- deterministic compiler and intrinsic-abstain grammar;
- digest and native receipt emitter.

The current source call graph is:

```text
ObjectiveSourceEnvelopeV1
-> admit_and_compile_objective_v1
-> adapt/map executable V1 semantics into ObjectiveSourceEnvelope
-> compile
   -> native_feasibility::check_native_feasibility_v1
   -> check_feasibility_v1
   -> freeze objective or emit conflict
```

`compile` owns the mandatory feasibility stage for the native IR. There is no independent pre-compile rich-feasibility pass in `admit_and_compile_objective_v1`.

The general registered feasibility engine supports scalar intervals, bounded enum include/exclude sets, positive action implications and immutable identity equality. The current `ObjectiveSourceEnvelopeV1` payload does not expose all of those semantics: a source constraint has only one scalar `boundQ32`, and V1 admission faithfully maps only `eq`, `lte` and `gte`. Strict/not-equal operators, `in`/`not_in`, and terminal hard constraints fail closed rather than being approximated. Rich feasibility capability must not be confused with rich source-admission capability.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, native outputs and compatibility

Produced target contracts:

- `ModulePort::objective.compiler::intelligence.control`
- `ObjectiveFunctionV1`
- `RunStartSnapshotV1`

Consumed contracts:

- `ModulePort::cognitive.read::objective.compiler`
- `ModulePort::platform.types::objective.compiler`

Critical target protocol schemas:

- `ObjectiveFunctionV1`
- `RunStartSnapshotV1`

The current Rust source candidate emits native `ObjectiveFunction`, `ObjectiveCompileReceipt` and `ObjectiveConflictReceipt`. Admission folds terminal/evidence predicates into the native success-predicate collection and resource/risk policy into generated native constraints. Forbidden actions participate in conflict construction rather than being retained as a distinct native output collection.

Therefore the native structs are **not yet the canonical `ObjectiveFunctionV1` / `ObjectiveCompileReceiptV1` wire representation** required for product publication. The canonical output adapter must explicitly materialize the immutable core and bounded adaptive surface, validate the final payload, bind the canonical digest scope and reject unknown critical fields. Digest binding inside the native compiler is necessary but is not a substitute for that adapter.

Compatibility is additive only where registered. Contract identifiers, meaning and authority interpretation cannot change in place. A future source grammar that makes enum-set or implication semantics executable must be versioned rather than silently changing V1 interpretation.

## 6. Data authority, persistence and publication

Owned authoritative or rebuildable domains: none. Read-only data dependencies: none.

`objective.compiler` is stateless. The owning product caller is responsible for atomically publishing the canonical `ObjectiveFunctionV1`, `RunStartSnapshotV1` and associated admission/compile receipts after all source, intent, profile, constraint and objective bindings agree. That product caller and durable owner-store composition are not established by the current source candidate.

A read-only vertical or qualification façade is useful integration evidence but is not a production writer. Durable identity reuse with different semantics is a caller/store conflict; the stateless compiler does not invent persistence or reconciliation authority.

## 7. Runtime, concurrency and transaction model

The [current native implementation](../../../qualification/module-execution-dossiers/detail/objective.compiler.md#8-current-native-implementation) identifies the actual state owner, in-memory versus persistent surfaces, and transaction boundary. Use that implementation scope when composing the module; do not infer a durable store from the existence of source structs.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, abstention and retry

`ObjectiveConflictReceipt` and `CompileDisposition::ExplicitAbstain` are non-error outcomes. The bounded source structure permits zero caller legal actions; compilation then injects intrinsic `abstain` and returns `ExplicitAbstain`. Downstream integrations must preserve that as a safe outcome rather than converting it into a generic system error or blind retry signal.

`OBJ-E007` is a stable code family with variant-specific retry semantics. Feasibility-budget exhaustion and a source slightly ahead of local time may become admissible when transient state changes. Locale rejection, stale source, missing/before-observation/expired deadlines require new input or configuration. Rust callers use the variant-level `retryable()` policy rather than the code alone.

Use the error/recovery path linked by the [current native implementation](../../../qualification/module-execution-dossiers/detail/objective.compiler.md#8-current-native-implementation). A source library or fixture cannot stand in for an unimplemented durable recovery or external reconciler.

## 9. Security, privacy and threat controls

Owned threat entries:

- `objective_substitution`
- `success_predicate_downgrade`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and bounds

Admission-safe source ceilings are derived from the final native aggregate:

- source hard constraints: `<=246`; six resource constraints and four risk/rollback/compensation/abstention constraints reserve the remaining native slots up to `256`;
- `successPredicates + terminalConditions + evidenceRequirements <=128` in aggregate;
- caller legal actions: `<=127` when intrinsic abstain is implicit; compiled actions `<=128`;
- soft dimensions: `<=64`;
- feasibility conflict extraction: `<=257` oracle calls.

The admission profile currently has a 256 KiB guard implemented by `profile_encoded_size()`. That helper is a conservative parallel byte-accounting estimate, not a byte-for-byte canonical wire encoding. If the 256 KiB value is promoted to a protocol-hard canonical encoded-size requirement, the implementation must measure the actual canonical serialized bytes and eliminate the parallel estimator.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define measurement/overload obligations for a selected host.

## 11. Observability and operations

Stateless compiler/admission library; embed it at a request boundary and preserve its immutable canonical objective/run snapshot in the owning caller. No compiler daemon or private objective database is needed. Unsupported language, resource exhaustion, infeasibility and explicit abstain remain distinct outcomes; changing goal semantics requires a new authorized revision.

Current operating and state-format reference:

- [docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md](../../readiness/OBJECTIVE_COMPILER_EXECUTION.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Focused source references include:

- [codex-rs/hepta-objective/src/compiler_tests.rs](../../../codex-rs/hepta-objective/src/compiler_tests.rs): permutation invariance, conflict minimization, intrinsic abstain and action-slot reservation;
- [codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs](../../../codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs): bounded exhaustive Horn feasibility fixtures;
- [codex-rs/hepta-objective/src/source_envelope_v1_tests.rs](../../../codex-rs/hepta-objective/src/source_envelope_v1_tests.rs): UTF-8 bounds, generated-slot reservation, aggregate predicate ceilings and empty caller-action structure;
- `error_policy.rs`: variant-specific retry classification.

In `codex-rs`, run `just test -p codex-hepta-objective`. The command is a test invocation, not a stored result. Exact-head and deterministic synthetic-merge qualification must be current for the candidate being claimed; closed/unmerged historical PR evidence cannot satisfy that gate.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `OBJ-0-OBJECTIVE-CONTRACTS`
- `OBJ-1-OBJECTIVE-COMPILER`

The bootstrap package is `OBJ-0-OBJECTIVE-CONTRACTS`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics.

The implementation sequence is: bounded decoder -> admission-safe structure -> authenticated/profile-bound mapping -> native feasibility projection -> general feasibility/conflict extraction -> intrinsic abstain/legal-action freeze -> native digests/receipts -> canonical output adapter -> product caller/durable atomic publication -> exact-head/synthetic-merge qualification -> independent acceptance and activation gates.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source candidates remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Native source-candidate implementation requires code in the declared root and candidate tests. Canonical source completion additionally requires the declared public protocol surface, canonical output adapter and exact-head plus merge-candidate evidence. Composition requires a named product caller and durable publication boundary. Qualification, acceptance, activation, selection, promotion and release are separate states.

For `objective.compiler`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

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

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Current source-candidate receipt boundary

The source location for `objective.compiler` is materialized at:

- `codex-rs/hepta-objective`

Dedicated workflows and repository-wide gates provide candidate evidence. Their status must be read from the exact PR/head under review. This section records no evergreen pass claim. In particular, it does not establish canonical wire-output completion, a production caller/writer, independent acceptance, selection, promotion, merge or release authority.
