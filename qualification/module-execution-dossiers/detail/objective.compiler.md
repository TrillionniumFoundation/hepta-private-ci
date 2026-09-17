# objective.compiler: implementation design

Parent: `docs/modules/objective.compiler/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: native source candidate implemented and mapped; canonical output, exact-head qualification and product composition remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md` and `docs/contracts/OBJECTIVE_ERRORS.json`.

## 1. Source and work envelope

Root: `codex-rs/hepta-objective`. Packages: `OBJ-0-OBJECTIVE-CONTRACTS`, `OBJ-1-OBJECTIVE-COMPILER`. Exact operation-to-symbol and test mappings are in `docs/modules/objective.compiler/IMPLEMENTATION_MAP.json`.

This candidate changes no authority, effect or writer ownership. The module remains stateless for domain facts. The owning product caller, which is not established by this source candidate, must persist the canonical immutable objective and run snapshot atomically.

## 2. Native operations and contract details

The implemented call graph is:

```text
decode_source_envelope_json_v1(bytes)
-> ObjectiveSourceEnvelopeV1::validate_structure()
-> canonical_objective_intent_digest_v1(envelope)
-> admit_and_compile_objective_v1(envelope, profile, authenticated_context)
   -> adapt/map V1-executable semantics into ObjectiveSourceEnvelope
   -> compile(native_envelope)
      -> native_feasibility::check_native_feasibility_v1(native_envelope)
         -> check_feasibility_v1(grammar, atoms, budget)
      -> freeze objective or emit conflict
```

Admission validates source authentication, principal scope, schema, normalization, profile, source and intent digests before mapping executable V1 fields. Unknown or unrepresentable semantics fail closed. The admission receipt and compiler output carry no effect authority.

The general feasibility engine supports scalar, bounded enum, positive action-implication and immutable-identity atoms. The V1 source grammar does not expose all of those payloads. Its hard constraint carries one scalar `boundQ32`; current source admission therefore executes `eq`, `lte` and `gte` only. `ne`, strict `<`/`>`, `in`, `not_in` and terminal hard constraints reject rather than being approximated. Direct feasibility-engine capability is not evidence that `ObjectiveSourceEnvelopeV1` can express the same semantics.

`abstain` is intrinsic and confirmation-free. A request cannot forbid it. The bounded source path permits zero caller legal actions, which compiles to `CompileDisposition::ExplicitAbstain`. The compiled action ceiling is 128 including intrinsic abstain; source callers reserve that slot and therefore admit at most 127 caller legal actions.

## 3. State, identity, native output and publication

The compiler owns no durable store. Native output binds request, principal, source, schema, selected profile, hard constraints, legal actions, success/terminal/evidence semantics, resource/risk policy and semantic digest.

The current Rust output is `ObjectiveFunction` plus native compile/conflict receipts. Terminal/evidence categories are flattened into native success predicates and resource/risk policy into generated constraints. This is not yet the canonical `ObjectiveFunctionV1` / `ObjectiveCompileReceiptV1` wire representation declared by the control-plane contract. A versioned canonical output adapter remains required before product publication.

A product caller must publish the canonical `ObjectiveFunctionV1`, `RunStartSnapshotV1` and associated receipts atomically and reconcile by exact semantic identity. That product caller and owner-store composition are not established by this source candidate.

A typed hard conflict produces the native conflict receipt corresponding to the target `ObjectiveConflictReceiptV1`. `CompileDisposition::ExplicitAbstain` is a successful non-error outcome in which abstain is the sole legal action. Stable error meanings are owned by `docs/contracts/OBJECTIVE_ERRORS.json`; Markdown or Rust code may not locally redefine a code.

## 4. Deterministic algorithm and complexity

Decode bounded fields, authenticate source, map registered units/IDs, project executable native hard constraints into `RegisteredGrammarV1`/`ConstraintAtomV1`, invoke `check_feasibility_v1`, stable-sort all sets and freeze only on a feasible receipt. Infeasible hard atoms use deterministic deletion filtering and return an inclusion-minimal conflict set.

The registered feasibility engine can intersect scalar or finite-enum domains and close bounded positive action implications when the corresponding typed atoms are supplied. The V1 admission projection currently emits scalar hard-constraint atoms only.

Normalization and canonical sorting are `O(n log n)`. A feasibility oracle has profile cost `C(n)`. Inclusion-minimal conflict extraction performs at most `n+1` oracle calls and `O(n C(n))` work. These paths have separate CPU, wall-clock and metric budgets. Exhaustion preserves every original hard constraint and returns unavailable.

## 5. Capacity and performance profile

Admission-safe bounds are:

- raw source JSON: 256 KiB;
- source hard constraints: 246, reserving six resource and four risk/rollback/compensation/abstention generated slots for the native ceiling of 256;
- success predicates + terminal conditions + evidence requirements: 128 aggregate;
- soft dimensions: 64;
- caller legal actions with intrinsic abstain reserved: 127;
- compiled actions: 128;
- conflict-oracle calls: 257.

No network or synchronous central RPC occurs in the deterministic compiler path. Latency claims require a named host, compiler, build profile, input class and exact source. A normal successful compile measurement cannot be reused as a conflict-extraction measurement.

The admission profile's current 256 KiB guard is implemented through `profile_encoded_size()`, a conservative parallel estimator. It is not yet byte-for-byte measurement of a canonical serialized profile. If that number is treated as a protocol-hard canonical encoding boundary, replacing the estimator with actual canonical encoded-byte measurement remains source work.

## 6. Concrete verification cases

- `OBJ-DETAIL-01`: disjoint scalar intervals produce an inclusion-minimal conflict and remove irrelevant atoms.
- `OBJ-DETAIL-02`: equivalent reordered inputs produce identical semantic digests.
- `OBJ-DETAIL-03`: unsupported language or oracle exhaustion never weakens the legal set.
- `OBJ-DETAIL-04`: principal network prohibition dominates task text.
- `OBJ-DETAIL-05`: intrinsic abstain cannot be forbidden or confirmation-gated.
- `OBJ-DETAIL-06`: 127 caller actions plus implicit abstain compile to 128; zero caller actions produce `ExplicitAbstain`.
- `OBJ-DETAIL-07`: source, schema, profile, normalization or intent digest mismatch fails before native compile.
- `OBJ-DETAIL-08`: 247 source hard constraints reject before mapping because generated native slots are reserved.
- `OBJ-DETAIL-09`: success/terminal/evidence arrays reject when their aggregate exceeds 128.
- `OBJ-DETAIL-10`: locale rejection, stale source and invalid/expired deadlines are non-retryable for the same semantic input; transient future-source and feasibility-budget cases remain retryable.

Native test files and symbols are registered in the implementation map. A green fixture proves only the tested source boundary; it is not a production-caller, canonical-output, independent-acceptance or efficacy receipt.

## 7. Integration, rollback and capability ceiling

Compile before adaptive selection. NDU and Control consume a frozen objective but cannot mutate its hard constraints, observer requirements or legal effects. Rollback reuses a prior objective only when request/principal compatibility and current revocation checks pass; otherwise it starts a newly authorized run or abstains.

The candidate issues no runtime, model, provider, network, filesystem, tool, secret, Matrix, fleet, acceptance, merge, promotion or release authority. Product composition, canonical wire publication, independent review and exact-head/synthetic-merge workflow success remain separately governed.

## 8. Current native implementation

- **Implemented entrypoints:** `admit_and_compile_objective_v1` in [codex-rs/hepta-objective/src/objective_admission.rs](../../../codex-rs/hepta-objective/src/objective_admission.rs); `compile` in [codex-rs/hepta-objective/src/compiler.rs](../../../codex-rs/hepta-objective/src/compiler.rs); `check_feasibility_v1` in [codex-rs/hepta-objective/src/feasibility.rs](../../../codex-rs/hepta-objective/src/feasibility.rs). The compiler delegates mandatory hard-feasibility resolution through [native_feasibility.rs](../../../codex-rs/hepta-objective/src/native_feasibility.rs).
- **State and recovery:** stateless outputs bind the immutable source/principal/profile/schema/unit/time/intent tuple; unknown mappings fail closed. The owner caller must persist canonical objective and run snapshot publication; the native compiler has no durable objective database.
- **Source tests:** [codex-rs/hepta-objective/src/objective_admission_tests.rs](../../../codex-rs/hepta-objective/src/objective_admission_tests.rs), [codex-rs/hepta-objective/src/compiler_tests.rs](../../../codex-rs/hepta-objective/src/compiler_tests.rs), [codex-rs/hepta-objective/src/source_envelope_v1_tests.rs](../../../codex-rs/hepta-objective/src/source_envelope_v1_tests.rs), [codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs](../../../codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md](../../../docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md), [docs/modules/objective.compiler/IMPLEMENTATION_MAP.json](../../../docs/modules/objective.compiler/IMPLEMENTATION_MAP.json).
- **Remaining repository-controlled work:** materialize/validate canonical `ObjectiveFunctionV1` + `ObjectiveCompileReceiptV1` output; bind an authenticated production consumer and atomic `ObjectiveFunctionV1 + RunStartSnapshotV1` owner-store publication; replace profile byte estimation if the 256 KiB profile bound is protocol-hard; close exact-head and deterministic synthetic-merge qualification.
- **External evidence gates:** target-host measurements, independent semantic review, operator acceptance, activation, canary, promotion and release.
