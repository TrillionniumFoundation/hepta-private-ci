# objective.compiler: implementation design

Parent: `docs/modules/objective.compiler/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: source candidate implemented and mapped; exact-head qualification, canonical wire projection and product composition remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md`, `docs/contracts/OBJECTIVE_ERRORS.json` and `docs/contracts/OBJECTIVE_RETRY_POLICY.json`.

## 1. Source and work envelope

Root: `codex-rs/hepta-objective`. Packages: `OBJ-0-OBJECTIVE-CONTRACTS`, `OBJ-1-OBJECTIVE-COMPILER`. Exact operation-to-symbol and test mappings are in `docs/modules/objective.compiler/IMPLEMENTATION_MAP.json`.

This candidate changes no authority, effect or writer ownership. The module remains stateless for domain facts. The owning production caller, canonical `ObjectiveFunctionV1` wire adapter, owner store and durable `RunStartSnapshotV1` publication path are not established by this source candidate.

## 2. Native operations and contract details

The public V1 source path is:

```text
decode_source_envelope_json_v1(bytes)
ObjectiveSourceEnvelopeV1::validate_structure()
canonical_objective_intent_digest_v1(envelope)
admit_and_compile_objective_v1(envelope, profile, authenticated_context)
  -> validate authentication/profile/schema/time/digest bindings
  -> map complete V1 scalar hard-constraint set
  -> check_feasibility_v1(grammar, atoms, budget)
  -> native objective_admission compatibility mapping
  -> compile(native_envelope)
```

The public `admit_and_compile_objective_v1` symbol is implemented by `objective_admission_gate.rs`. It runs profile-bound general feasibility before native compilation. The older scalar feasibility call retained inside `compile` is a deterministic defense-in-depth compatibility recheck, not the sole feasibility gate.

Admission validates source authentication, principal scope, schema, normalization, selected profile, source and intent digests before publishing any conflict/compile result. Unknown or unrepresentable semantics fail closed. The admission receipt and compiler output carry no effect authority.

`check_feasibility_v1` itself supports scalar intervals, finite enums, positive action implications and immutable identity atoms. `ObjectiveSourceEnvelopeV1` does not carry enum-set or implication payloads; each V1 hard constraint carries one Q32 bound. Therefore the V1 source path exercises the complete **scalar subset** plus generated resource/risk constraints. Finite-enum intersection and positive action implications are solver capabilities, not complete V1 source-to-objective capabilities.

`ObjectiveConstraintComparatorV1` preserves `eq/ne/lt/lte/gt/gte/in/not_in` spellings so unrepresentable semantics reject instead of being silently rewritten. The V1 source adapter accepts `eq/lte/gte`; `ne`, strict inequalities, `in` and `not_in` return `UnsupportedComparator`. Terminal hard constraints remain unrepresentable by the native `Constraint` row and return `TerminalConstraintUnsupported`.

`abstain` is intrinsic and confirmation-free. At the bounded V1 source boundary caller legal actions are `0..=127`; zero caller actions compile to `ExplicitAbstain`, while 127 callers reserve one compiled slot for intrinsic abstain. The lower-level native compiler may accept an explicit intrinsic abstain inside its own 128-action ceiling.

## 3. State, identity and publication

The compiler owns no durable store. Native output digest-binds request, principal, source, schema, selected profile, hard constraints, legal actions, success/terminal/evidence semantics, resource/risk policy and soft preferences. V1 admission currently lowers terminal/evidence/resource/risk semantics into native `success_predicates` / `constraints`; this is not the exact canonical `ObjectiveFunctionV1` JSON projection.

A production caller must publish the canonical `ObjectiveFunctionV1` and matching `RunStartSnapshotV1` atomically enough that a run cannot observe one without the other, and reconcile by exact semantic identity. No such production owner-store path is established by this source candidate.

A typed hard conflict produces `ObjectiveConflictReceiptV1`. `CompileDisposition::ExplicitAbstain` is a successful non-error outcome in which abstain is the sole legal action. New read-only intelligence callers can use `run_read_only_vertical_outcome_v1` to preserve that non-error distinction; the older error-shaped façade remains only for compatibility.

Stable error meanings remain in `docs/contracts/OBJECTIVE_ERRORS.json`. `OBJ-E007` is not a blanket blind-retry instruction: variant-specific guidance lives in `docs/contracts/OBJECTIVE_RETRY_POLICY.json` and `ObjectiveRetryDirectiveV1`.

## 4. Deterministic algorithm and complexity

Decode and structurally bound fields, authenticate source, bind the selected profile, validate all represented mappings, map the complete V1 scalar hard set, run `check_feasibility_v1`, then compile the feasible native envelope and stable-sort native sets. Infeasible hard atoms use deterministic deletion filtering and return an inclusion-minimal conflict set.

The rich feasibility engine can intersect scalar or finite-enum domains and close bounded positive action implications, but V1 source admission currently emits scalar hard atoms only. Unsupported source operators are rejected before solver publication rather than guessed into another domain.

Normalization and canonical sorting are `O(n log n)`. A feasibility oracle has profile cost `C(n)`. Inclusion-minimal conflict extraction performs at most `n+1` oracle calls and `O(n C(n))` work. Exhaustion preserves every original hard constraint and returns unavailable; it never weakens the legal set.

## 5. Capacity and performance profile

Current V1 source/native aggregate bounds are:

- raw JSON: `<=256 KiB`;
- source hard constraints: `<=246`;
- generated resource constraints: exactly `6`;
- generated risk constraints: exactly `4`;
- native hard-constraint aggregate: `<=256`;
- `successPredicates + terminalConditions + evidenceRequirements`: `<=128` aggregate;
- caller legal actions: `0..=127` at bounded V1 admission;
- compiled actions: `<=128` including intrinsic abstain;
- soft dimensions: `<=64`;
- conflict-oracle calls: `<=257`.

No network or synchronous central RPC occurs in the deterministic compiler path. The in-crate semantic gate disables wall-clock cancellation and is call-count bounded; target-host latency/SLO measurement is a separate product-composition obligation.

The admission profile still uses owner-local manual byte accounting for its nominal 256 KiB profile bound. Until an exact canonical profile wire encoding exists and that encoding's actual byte length is enforced, this must not be reported as canonical encoded-byte enforcement.

## 6. Concrete verification cases

- `OBJ-DETAIL-01`: profile-bound contradictory scalar bounds produce an inclusion-minimal conflict and exclude irrelevant atoms.
- `OBJ-DETAIL-02`: equivalent reordered inputs produce identical semantic digests.
- `OBJ-DETAIL-03`: unsupported language or oracle exhaustion never weakens the legal set.
- `OBJ-DETAIL-04`: principal/network authority restrictions dominate lower task semantics.
- `OBJ-DETAIL-05`: intrinsic abstain cannot be forbidden or confirmation-gated.
- `OBJ-DETAIL-06`: zero caller actions compile through bounded admission to `ExplicitAbstain`; 127 callers reserve intrinsic abstain; 128 callers reject at the bounded source boundary.
- `OBJ-DETAIL-07`: source, schema, profile, normalization or intent digest mismatch fails before feasibility/compile publication.
- `OBJ-DETAIL-08`: 247 source constraints reject before six resource and four risk rows can overflow the native 256 ceiling.
- `OBJ-DETAIL-09`: individually bounded success/terminal/evidence arrays reject when their merged native aggregate exceeds 128.
- `OBJ-DETAIL-10`: locale/deadline/stale/future variants do not default to blind same-input retry.

Native test files and symbols are registered in the implementation map. A green fixture proves only the tested candidate/source boundary; it is not a production-caller, independent-acceptance or efficacy receipt.

## 7. Integration, rollback and capability ceiling

Compile before adaptive selection. NDU and Control consume a frozen objective representation but cannot mutate hard constraints, observer requirements or legal effects. Rollback/reuse of a prior durable objective is owned by the future production caller and requires exact request/principal compatibility plus current revocation checks; otherwise a new authorized run is required or the system abstains.

The current read-only intelligence vertical is an integration harness with zero effect authority. It does not substitute for canonical `ObjectiveFunctionV1 + RunStartSnapshotV1` publication, owner-store crash recovery or production reconciliation.

The candidate issues no runtime, model, provider, network, filesystem, tool, secret, Matrix, fleet, acceptance, merge, promotion or release authority. Product composition, independent review and exact-head/synthetic-merge workflow success remain separately governed.

## 8. Current native implementation

- **Implemented entrypoints:** `admit_and_compile_objective_v1` in [codex-rs/hepta-objective/src/objective_admission_gate.rs](../../../codex-rs/hepta-objective/src/objective_admission_gate.rs); `check_feasibility_v1` in [codex-rs/hepta-objective/src/feasibility.rs](../../../codex-rs/hepta-objective/src/feasibility.rs); `compile` in [codex-rs/hepta-objective/src/compiler.rs](../../../codex-rs/hepta-objective/src/compiler.rs). The public V1 admission gate runs general feasibility on the complete V1 scalar hard set before native compile.
- **Compatibility internals:** [codex-rs/hepta-objective/src/objective_admission.rs](../../../codex-rs/hepta-objective/src/objective_admission.rs) retains native lowering/admission checks; [codex-rs/hepta-objective/src/scalar_adapter.rs](../../../codex-rs/hepta-objective/src/scalar_adapter.rs) remains a compiler defense-in-depth scalar recheck.
- **State and recovery:** Stateless outputs bind the immutable source/principal/profile/schema/unit/time/intent tuple; unknown mappings fail closed. A production caller/owner store and atomic objective/run-snapshot publication are not established.
- **Source tests:** [codex-rs/hepta-objective/src/objective_admission_tests.rs](../../../codex-rs/hepta-objective/src/objective_admission_tests.rs), [codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs](../../../codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs), [codex-rs/hepta-objective/tests/admission_closure.rs](../../../codex-rs/hepta-objective/tests/admission_closure.rs), [codex-rs/hepta-objective/tests/retry_policy.rs](../../../codex-rs/hepta-objective/tests/retry_policy.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md](../../../docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md), [docs/modules/objective.compiler/IMPLEMENTATION_MAP.json](../../../docs/modules/objective.compiler/IMPLEMENTATION_MAP.json).
- **Repository-controlled blockers before a stronger claim:** the readiness source bounds are now aligned with the enforced V1 capacity; remaining work is to define a source grammar for enum-set/action-implication payloads before claiming those rich domains, implement the exact canonical `ObjectiveFunctionV1` projection, bind a named authenticated production caller/owner store, atomically persist/reconcile the objective plus run snapshot, replace manual profile byte estimation if 256 KiB is protocol-hard, and obtain exact-head and synthetic-merge evidence.
