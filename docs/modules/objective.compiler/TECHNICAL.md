# objective.compiler technical development guide

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

`existing_bound` is a source-location fact. The declared roots above are materialized in the bounded V8 source candidate. Dedicated objective and Lane-D workflows provide focused tests, all-target compilation and strict lint; exact-head qualification is an execution receipt for the current candidate, not a property inferred from this document. This status does not activate `objective.compiler`, grant runtime or effect authority, issue independent acceptance, select or promote a candidate, or authorize release. Any later source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide in one candidate.

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

The admitted production path and the richer typed feasibility API are intentionally distinguished. See [`SEMANTIC_SUPPORT.md`](SEMANTIC_SUPPORT.md) and [`SEMANTIC_SUPPORT.json`](SEMANTIC_SUPPORT.json). The current native admitted call graph is `decode -> structural validation -> canonical intent digest -> authenticated admission -> adapt_source -> compile -> scalar_conflict -> check_feasibility_v1`. Unsupported Source V1 semantics are rejected explicitly rather than approximated. The legacy scalar compiler is crate-private by default; qualification fixtures must opt into `qualification-legacy-compiler`.

Ingress validates identity, version, size, scope and revision before domain logic. The deterministic core receives typed values and is testable without network, filesystem or process-global state unless the module owns that boundary. State-bearing components use one transaction boundary per logical mutation. Publication occurs only after invariants and lineage checks pass.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, model identity, objective semantics or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `ModulePort::objective.compiler::intelligence.control`
- `ObjectiveFunctionV1`
- `RunStartSnapshotV1`

Consumed contracts:

- `ModulePort::cognitive.read::objective.compiler`
- `ModulePort::platform.types::objective.compiler`

Critical protocol schemas:

- `ObjectiveFunctionV1`
- `RunStartSnapshotV1`

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

Rust types and canonical JSON represent identical semantics. Tests cover round trips, maximum bounds, missing fields, unknown fields, invalid enums, canonical ordering and digest stability. Error mapping preserves rejected, unavailable, timed out, indeterminate, quarantined and terminally failed outcomes.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

None.

Read-only data dependencies:

None.

For every owned domain, this module is the only authoritative writer. Mutations are revision- or generation-bound, idempotent for identical semantics and conflicting for a reused identity with different content. Records bind source identity, schema revision, logical sequence and lineage sufficient for correction, deletion and revocation.

Migrations are deterministic and checksum-bound. Store open verifies required schema objects and integrity constraints before reads or writes. Migration failure leaves a recoverable predecessor. Rollback across a schema boundary restores compatible state with the binary.

Projection domains rebuild from declared sources and publish complete generations atomically. Projections never become sources of truth. Retention and deletion preserve lineage and prevent resurrection through indexes, caches, artifacts or backup restore.

## 7. Runtime, concurrency and transaction model

The compiler itself remains stateless. `prepare_intelligence_run_v1` in `codex-rs/hepta-intelligence` performs authenticated admission, revalidates the compiled objective, binds `RunStartSnapshotV1`, and appends one atomic `RunStartPublicationV1` through the sealed `learning.ledger` durable owner port. The named product-host candidate is `runtime.agentd::prepare_and_start_intelligence_run_v1`, which composes that durable publication with runtime admission in a fixed order and retains the opaque publication receipt on post-fsync runtime failure. Agentd admits only matching authority epoch, generation and fence state and never owns the objective facts. Exact-head qualification of this cross-owner composition remains required before the caller is considered established.

[Shared concurrency and transaction requirements](../README.md#shared-concurrency-and-transactions) apply at the corresponding owner boundary.

## 8. Failure semantics, recovery and rollback

Compiler errors remain fail-closed and side-effect free. For a compiled product run, admission receipt, compiled objective and `RunStartSnapshotV1` are encoded into one learning-ledger frame; the existing durable journal syncs the frame before publishing it in memory. Equal record retries are idempotent, a reused run identity with different record semantics conflicts, and anchored reopen replays the same objective/snapshot binding. A durable journal receipt is still not runtime/effect authority, and external reconciliation/activation remain separately governed.

[Shared failure, recovery and rollback requirements](../README.md#shared-failure-and-recovery) remain mandatory.

## 9. Security, privacy and threat controls

Owned threat entries:

- `objective_substitution`
- `success_predicate_downgrade`

The posture is least authority, bounded input, typed contracts, digest binding and independent evidence. Sensitive values are redacted or represented by digests at evidence boundaries. Credentials never enter general logs, learning datasets, prompt factors or cross-module receipts. Authority is operation-bound, final-payload-bound, short-lived and revocation-aware.

Negative tests cover denied capabilities, cross-owner writes, stale or revoked grants, replay with payload drift, unknown fields, oversize input, scope escape, untrusted instruction escalation and secret/provider leakage. Security review is mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

The [module-specific implementation design](../../../qualification/module-execution-dossiers/detail/objective.compiler.md) specifies this module's algorithm and pilot ceilings. `compile` is semantically deterministic and its scalar compatibility oracle uses `Duration::MAX`; the standalone `check_feasibility_v1` may instead use a finite wall-clock availability budget, so `Exhausted` near that deadline and its `elapsed` field are not canonical semantic state. The dedicated product-composition workflow records host/compiler identity and separately measures, in release profile, authenticated admission + compile + durable fsync, the composed Agentd product-host path through runtime admission, and the 256-atom inclusion-minimal-conflict path. The conflict fixture asserts the 257-call oracle ceiling. These CI measurements are qualification telemetry, not target-production-host claims.

[Shared performance and capacity requirements](../README.md#shared-performance-and-capacity) define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Stateless compiler/admission library. The repository now contains a bounded compiler caller in `intelligence.control` and a named product-host candidate `runtime.agentd::prepare_and_start_intelligence_run_v1` that publishes the immutable objective/run snapshot through `learning.ledger` before admitting the digest-bound runtime snapshot. No compiler daemon or private objective database is needed. Unsupported language, resource exhaustion and infeasibility remain different outcomes; changing goal semantics requires a new authorized revision.

Current operating and state-format references:

- [docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md](../../readiness/OBJECTIVE_COMPILER_EXECUTION.md).

[Shared observability and operations requirements](../README.md#shared-observability-and-operations) specify safe events and alert classes; concrete deployment thresholds require the selected host profile.

## 12. Verification and qualification

Current focused test sources (source references, not pass receipts):

- [codex-rs/hepta-objective/src/compiler_tests.rs](../../../codex-rs/hepta-objective/src/compiler_tests.rs); named case: `compilation_is_permutation_invariant`.
- [codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs](../../../codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs); named case: `all_three_action_graphs_match_truth_table_and_have_minimal_conflicts`.

In `codex-rs`, run `just test -p codex-hepta-objective`. For repository evidence, `.github/workflows/hepta-objective-admission.yml` owns objective package test/lint/fmt checks; `.github/workflows/hepta-lane-d-semantic-conformance.yml` repeats Lane-D check/test/lint on Linux, macOS and Windows; `.github/workflows/hepta-objective-product-composition.yml` qualifies the cross-owner durable caller/runtime seam and emits the named-host measurement record. `.github/workflows/hepta-consolidated-source.yml` remains a broader repository/source-owner gate and must not be cited as the sole objective package-test receipt.

[Shared verification and qualification requirements](../README.md#shared-verification-and-qualification) retain the source/merge, failure, compilation and independent-evidence obligations.

## 13. Implementation sequence and work packages

Applicable work packages:

- `OBJ-0-OBJECTIVE-CONTRACTS`
- `OBJ-1-OBJECTIVE-COMPILER`

The bootstrap package is `OBJ-0-OBJECTIVE-CONTRACTS`. Development, activation and evidence predecessor graphs are distinct and all are enforced. Contract-first work may run in parallel only with non-overlapping write paths and frozen semantics. Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned packages may remain without invalidating documentation closure.

`IMPLEMENTATION_MAP.json.sourceBase` is the repository-wide closed-world mapping baseline shared by all module maps; it is not an assertion that that commit is the currently qualified source head. Current source identity is event-bound by the exact-head and synthetic-merge workflows named in the implementation map's `qualificationTarget`.

## 14. Activation, compatibility and retirement

A named product-caller **candidate** now exists through the registered objective -> intelligence -> learning-ledger -> Agentd boundaries. It remains a candidate until exact-head and merge-candidate workflows pass; composition evidence is not activation. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and external evidence gates pass.

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

## 17. Source implementation receipt

The bootstrap source-location obligation for `objective.compiler` is implemented by work package `OBJ-0-OBJECTIVE-CONTRACTS` in:

- `codex-rs/hepta-objective`

The source candidate is checked directly by `.github/workflows/hepta-objective-admission.yml` and `.github/workflows/hepta-lane-d-semantic-conformance.yml`; the cross-owner caller is checked by `.github/workflows/hepta-objective-product-composition.yml`. The consolidated source workflow supplies broader repository/source-owner evidence but is not the objective package-test owner. These receipts are source/composition evidence only. It grants no runtime, production-writer, model-provider, external-effect, independent-acceptance, selection, promotion, merge or release authority.
