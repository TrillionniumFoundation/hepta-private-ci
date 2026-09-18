# objective.compiler: implementation design

Parent: `docs/modules/objective.compiler/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: source candidate implemented and mapped; Agentd product-source composition is implemented but not activated; exact-head qualification, target-host qualification and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md` and `docs/contracts/OBJECTIVE_ERRORS.json`.

## 1. Source and work envelope

Root: `codex-rs/hepta-objective`. Packages: `OBJ-0-OBJECTIVE-CONTRACTS`, `OBJ-1-OBJECTIVE-COMPILER`. Exact operation-to-symbol and test mappings are in `docs/modules/objective.compiler/IMPLEMENTATION_MAP.json`.

This candidate changes no authority, effect or objective-writer ownership. The compiler remains stateless for domain facts. The named caller source is `codex-rs/hepta-agentd/src/objective_runtime.rs::admit_publish_and_start_objective_run_v1`. Its caller-owned `ObjectiveRunFileStore` persists one immutable objective + admission + `RunStartSnapshotV1` publication before admitting the run to `AgentRunCoordinator`; identical replay is idempotent and same-run semantic drift conflicts. This establishes source composition only, not deployed-host activation or external effect authority.

## 2. Native operations and contract details

The implemented path is:

```text
decode_source_envelope_json_v1(bytes)
ObjectiveSourceEnvelopeV1::validate_structure()
canonical_objective_intent_digest_v1(envelope)
admit_and_compile_objective_v1(envelope, profile, authenticated_context)
check_feasibility_v1(grammar, atoms, budget)
compile(native_envelope)
```

Admission validates source authentication, principal scope, schema, normalization, profile, source and intent digests before mapping every represented field. Unknown or unrepresentable semantics fail closed. The admission receipt and compiler output carry no effect authority.

`abstain` is intrinsic and confirmation-free. A request cannot forbid it. The compiled action ceiling is 128 including abstain: at most 127 caller actions when abstain is implicit, or 128 when the caller supplies the valid intrinsic action explicitly.

## 3. State, identity and publication

The compiler owns no durable store. Its pure output binds request, principal, source, schema, selected profile, hard constraints, legal actions, success and terminal predicates, evidence requirements, resource/risk policy and semantic digest. Agentd now implements the caller publication boundary: one caller-owned immutable record contains the compiled objective semantics, admission receipt and `RunStartSnapshotV1`; the file is synced and atomically renamed before a non-abstain runtime run is admitted. Existing identical publication is an idempotent replay; a reused run identity with different objective/runtime bindings is a conflict. `ExplicitAbstain` is published without creating dispatchable run state.

A typed hard conflict produces `ObjectiveConflictReceiptV1`. `CompileDisposition::ExplicitAbstain` is a successful non-error outcome in which abstain is the sole legal action. Stable error meanings are generated from `docs/contracts/OBJECTIVE_ERRORS.json`; Markdown or Rust code may not locally redefine a code.

## 4. Deterministic algorithm and complexity

Decode and normalize bounded fields, authenticate source, map registered units/IDs, classify P0-P4 precedence, intersect scalar or finite-enum domains, close bounded positive action implications and stable-sort all sets. Infeasible hard atoms use deterministic deletion filtering and return an inclusion-minimal conflict set.

Normalization and canonical sorting are `O(n log n)`. A feasibility oracle has profile cost `C(n)`. Inclusion-minimal conflict extraction performs at most `n+1` oracle calls and `O(n C(n))` work. These paths have separate CPU, wall-clock and metric budgets. Exhaustion preserves every original hard constraint and returns unavailable.

## 5. Capacity and performance profile

Pilot bounds are 256 KiB raw input, 256 constraints, 128 success predicates, 64 soft dimensions, 127 caller actions without explicit abstain, 128 compiled actions and 257 conflict-oracle calls. No network or synchronous central RPC occurs in the deterministic compiler path.

Latency claims require a named host, compiler, build profile, input class and exact source. A normal successful compile measurement cannot be reused as a conflict-extraction measurement. The repository now supplies `scripts/hepta-objective-target-measure.py` and [docs/readiness/OBJECTIVE_TARGET_HOST_MEASUREMENT.md](../../../docs/readiness/OBJECTIVE_TARGET_HOST_MEASUREMENT.md): release-mode ignored fixtures emit separate p50/p95/p99 distributions for authenticated admission+compile and the 256-atom/257-oracle conflict path. The harness is source-complete; actual target-host observations remain external evidence.

## 6. Concrete verification cases

- `OBJ-DETAIL-01`: disjoint scalar intervals produce an inclusion-minimal conflict and remove irrelevant atoms.
- `OBJ-DETAIL-02`: equivalent reordered inputs produce identical semantic digests.
- `OBJ-DETAIL-03`: unsupported language or oracle exhaustion never weakens the legal set.
- `OBJ-DETAIL-04`: principal network prohibition dominates task text.
- `OBJ-DETAIL-05`: intrinsic abstain cannot be forbidden or confirmation-gated.
- `OBJ-DETAIL-06`: 127 caller actions plus implicit abstain compile to 128; 128 without abstain reject.
- `OBJ-DETAIL-07`: source, schema, profile, normalization or intent digest mismatch fails before native compile.

Native test files and symbols are registered in the implementation map. A green fixture proves only the tested source boundary; it is not a production-caller or efficacy receipt.

## 7. Integration, rollback and capability ceiling

Compile before adaptive selection. NDU and Control consume the frozen objective but cannot mutate its hard constraints, observer requirements or legal effects. Rollback reuses a prior objective only when request/principal compatibility and current revocation checks pass; otherwise it starts a newly authorized run or abstains.

The candidate issues no runtime, model, provider, network, filesystem, tool, secret, Matrix, fleet, acceptance, merge, promotion or release authority. Product composition, independent review and exact-head workflow success remain separately governed.

## 8. Current native implementation

- **Implemented entrypoints:** `admit_and_compile_objective_v1` in [codex-rs/hepta-objective/src/objective_admission.rs](../../../codex-rs/hepta-objective/src/objective_admission.rs); `check_feasibility_v1` in [codex-rs/hepta-objective/src/feasibility.rs](../../../codex-rs/hepta-objective/src/feasibility.rs); caller composition `admit_publish_and_start_objective_run_v1` in [codex-rs/hepta-agentd/src/objective_runtime.rs](../../../codex-rs/hepta-agentd/src/objective_runtime.rs). Profile-bound source admission, private deterministic compiler core, feasibility oracle and caller-side immutable publication are implemented.
- **API boundary:** raw `crate::compiler::compile` is crate-private. The only public bypass is the explicitly feature-gated qualification compatibility function `compile_prevalidated_legacy_objective`; product callers use authenticated admission.
- **State and recovery:** compiler outputs bind the immutable source/principal/profile/schema/unit/time/intent tuple; unknown mappings fail closed. Agentd's narrow publication store syncs and atomically renames a complete objective/admission/run-start record before runtime admission, supports exact idempotent replay and rejects same-run semantic drift. It is not an objective-owned database or deployment receipt.
- **Source tests:** [codex-rs/hepta-objective/src/objective_admission_tests.rs](../../../codex-rs/hepta-objective/src/objective_admission_tests.rs), [codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs](../../../codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs), [codex-rs/hepta-agentd/src/objective_runtime_tests.rs](../../../codex-rs/hepta-agentd/src/objective_runtime_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md](../../../docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md), [docs/modules/objective.compiler/IMPLEMENTATION_MAP.json](../../../docs/modules/objective.compiler/IMPLEMENTATION_MAP.json).
- **Remaining work:** obtain successful current-candidate Objective/Lane-D workflow receipts, qualify caller crash/restart/backpressure on the named deployment host, authenticate the deployed ingress identity, and measure ordinary compile versus conflict-oracle latency/resource budgets separately. Independent acceptance, activation and release remain external.
