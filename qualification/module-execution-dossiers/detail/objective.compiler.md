# objective.compiler: implementation design

Parent: `docs/modules/objective.compiler/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: source candidate implemented with a named Agentd product composition and destination-owned durable run-start journal; exact-head/synthetic-merge qualification, target-host evidence, activation and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md` and `docs/contracts/OBJECTIVE_ERRORS.json`.

## 1. Source and work envelope

Root: `codex-rs/hepta-objective`. Packages: `OBJ-0-OBJECTIVE-CONTRACTS`, `OBJ-1-OBJECTIVE-COMPILER`. Exact operation-to-symbol and test mappings are in `docs/modules/objective.compiler/IMPLEMENTATION_MAP.json`.

This candidate changes no effect authority and keeps `objective.compiler` stateless for domain facts. The named source-level product caller is Agentd. It authenticates structured-objective ingress through current owner-controlled AuthBus trust, binds the verification receipt digest into admission, and asks the destination-owned learning-ledger `DurableRunStartJournal` to persist the immutable objective and `RunStartSnapshotV1` before runtime handoff.

## 2. Native operations and contract details

The implemented path is:

```text
decode_source_envelope_json_v1(bytes)
ObjectiveSourceEnvelopeV1::validate_structure()
canonical_objective_intent_digest_v1(envelope)
admit_objective_v1(envelope, profile, authenticated_context)
compile_admitted_objective_v1(admitted)
  -> compiler::compile(native_envelope)
     -> scalar_adapter::scalar_conflict(...)
        -> check_feasibility_v1(grammar, atoms, deterministic_budget)
```

Admission validates source authentication, principal scope, schema, normalization, profile, source and intent digests before mapping every losslessly representable field. Unknown or unrepresentable semantics fail closed. The opaque `AdmittedObjectiveV1` type prevents ordinary downstream code from entering the compiler with a caller-constructed legacy envelope; the old raw compiler surface is available only behind the explicit `qualification-legacy-compile` Cargo feature. The admission receipt and compiler output carry no effect authority.

`abstain` is intrinsic and confirmation-free. A request cannot forbid it. The compiled action ceiling is 128 including abstain: at most 127 caller actions when abstain is implicit, or 128 when the caller supplies the valid intrinsic action explicitly.

## 3. State, identity and publication

The compiler owns no durable store. Its pure output binds request, principal, source, schema, selected profile, hard constraints, legal actions, success and terminal predicates, evidence requirements, resource/risk policy and semantic digest. A product caller must publish the immutable objective and `RunStartSnapshotV1` atomically and reconcile by exact semantic identity.

A typed hard conflict produces `ObjectiveConflictReceiptV1`. `CompileDisposition::ExplicitAbstain` is a successful non-error outcome in which abstain is the sole legal action. Stable error meanings are generated from `docs/contracts/OBJECTIVE_ERRORS.json`; Markdown or Rust code may not locally redefine a code.

## 4. Deterministic algorithm and complexity

Decode and normalize bounded fields, authenticate source, map registered units/IDs, classify P0-P4 precedence, intersect scalar or finite-enum domains, close bounded positive action implications and stable-sort all sets. Infeasible hard atoms use deterministic deletion filtering and return an inclusion-minimal conflict set.

Normalization and canonical sorting are `O(n log n)`. A feasibility oracle has profile cost `C(n)`. Inclusion-minimal conflict extraction performs at most `n+1` oracle calls and `O(n C(n))` work. These paths have separate CPU, wall-clock and metric budgets. Exhaustion preserves every original hard constraint and returns unavailable.

## 5. Capacity and performance profile

Pilot bounds are 256 KiB generic raw input; Source V1 admits at most 246 explicit constraints because admission deterministically generates 6 resource ceilings plus 4 risk/rollback constraints before the native 256-constraint ceiling. `successPredicates + terminalConditions + evidenceRequirements` share one native ceiling of 128. Legal source actions are at most 127 when intrinsic `abstain` is implicit, or 128 only when the profile maps an explicit valid `abstain`; compiled actions remain at most 128. Soft dimensions are at most 64 and conflict extraction is at most 257 oracle calls. The Agentd product frame deliberately applies a smaller source/body byte ceiling. No network or synchronous central RPC occurs in the deterministic compiler path itself.

Latency claims require a named host, compiler, build profile, input class and exact source. A normal successful compile measurement cannot be reused as a conflict-extraction measurement.

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

- **Implemented entrypoints:** `admit_and_compile_objective_v1` in [codex-rs/hepta-objective/src/objective_admission.rs](../../../codex-rs/hepta-objective/src/objective_admission.rs); `check_feasibility_v1` in [codex-rs/hepta-objective/src/feasibility.rs](../../../codex-rs/hepta-objective/src/feasibility.rs). Profile-bound source admission, deterministic compile and feasibility oracle implemented.
- **State and recovery:** Stateless outputs bind source/principal/profile/schema/unit/time/intent plus the preverified authentication receipt digest; unknown mappings fail closed. Agentd composes the product ingress and the sealed learning-ledger run-start journal owns durable objective/snapshot publication, idempotent exact-run replay, predecessor fencing and crash-tail recovery. The native compiler still has no durable objective database.
- **Source tests:** [codex-rs/hepta-objective/src/objective_admission_tests.rs](../../../codex-rs/hepta-objective/src/objective_admission_tests.rs), [codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs](../../../codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md](../../../docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md), [docs/modules/objective.compiler/IMPLEMENTATION_MAP.json](../../../docs/modules/objective.compiler/IMPLEMENTATION_MAP.json).
- **Remaining work:** Current candidate CI must prove the exact head and deterministic synthetic merge. The repository supplies separate release-mode ordinary-admission and maximum-conflict measurement fixtures plus an exact-SHA recorder, but the selected deployment owner must still run them on the named target host/profile and retain p95/p99/resource evidence. Independent semantic acceptance, deployment activation, canary/promotion and release remain external.
