# objective.compiler: implementation design

Parent: `docs/modules/objective.compiler/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: source candidate implemented and mapped; a named durable product-composition candidate is present; exact-head qualification, target-host qualification, independent acceptance and activation remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md` and `docs/contracts/OBJECTIVE_ERRORS.json`.

## 1. Source and work envelope

Root: `codex-rs/hepta-objective`. Packages: `OBJ-0-OBJECTIVE-CONTRACTS`, `OBJ-1-OBJECTIVE-COMPILER`. Exact operation-to-symbol and test mappings are in `docs/modules/objective.compiler/IMPLEMENTATION_MAP.json`.

This candidate changes no runtime/effect authority and the compiler remains stateless for domain facts. `intelligence.control` now contains the named candidate product caller `ObjectiveProductCallerV1`, which persists one atomic admission/compiled-objective/`RunStartSnapshotV1` publication in a host-authorized append-only file. That composition is not activation or release authority.

## 2. Native operations and contract details

The implemented product path is:

```text
decode_source_envelope_json_v1(bytes)
ObjectiveSourceEnvelopeV1::validate_structure()
canonical_objective_intent_digest_v1(envelope)
admit_objective_v1(envelope, profile, authenticated_context)
  -> AdmittedObjectiveV1
compile_admitted_objective_v1(admitted)
  -> compiler::compile(native_envelope)
     -> scalar_adapter::scalar_conflict
        -> check_feasibility_v1(grammar, atoms, deterministic budget)
ObjectiveProductCallerV1::admit_compile_publish(...)
  -> atomic admission + objective + RunStartSnapshotV1 publication
```

The explicit typed `check_feasibility_v1` API may also be called independently with registered enum/action/identity atoms and a caller wall-clock availability budget. That separate API does not widen the `ObjectiveSourceEnvelopeV1` wire language.

Admission validates source authentication, principal scope, schema, normalization, profile, source and intent digests before producing the opaque `AdmittedObjectiveV1`. The V1 JSON wire accepts only exactly representable `eq`/`lte`/`gte` comparators; unsupported source semantics fail at strict ingress or programmatic admission rather than being approximated. The admission receipt, compiler output and product publication carry no effect authority.

`abstain` is intrinsic and confirmation-free. A request cannot forbid it. The compiled action ceiling is 128 including abstain: at most 127 caller actions when abstain is implicit, or 128 when the caller supplies the valid intrinsic action explicitly.

## 3. State, identity and publication

The compiler owns no durable store. Its pure output binds request, principal, source, schema, selected profile, hard constraints, legal actions, success and terminal predicates, evidence requirements, resource/risk policy and semantic digest. The named `ObjectiveProductCallerV1` publishes the admission receipt, complete compiled objective and `RunStartSnapshotV1` atomically. Equal run retries do not append; request/revision reuse with changed admitted semantics conflicts. The store holds an exclusive lock, syncs before memory publication, poisons after ambiguous writes and replays against an independently retained anchor.

A typed hard conflict produces `ObjectiveConflictReceiptV1`. `CompileDisposition::ExplicitAbstain` is a successful non-error outcome in which abstain is the sole legal action. Stable error meanings are generated from `docs/contracts/OBJECTIVE_ERRORS.json`; Markdown or Rust code may not locally redefine a code.

## 4. Deterministic algorithm and complexity

Decode and normalize bounded fields, authenticate source, map registered units/IDs, classify P0-P4 precedence and compile the admitted scalar objective path with stable ordering. The explicit typed feasibility API separately supports registered finite-enum, action implication and immutable-identity atoms. Infeasible hard atoms use deterministic deletion filtering and return an inclusion-minimal conflict set.

Normalization and canonical sorting are `O(n log n)`. A feasibility oracle has profile cost `C(n)`. Inclusion-minimal conflict extraction performs at most `n+1` oracle calls and `O(n C(n))` work. The semantic solver is deterministic; the explicit feasibility wrapper may additionally enforce a caller wall-clock availability budget, so `elapsed` and wall-clock exhaustion are host observations. The admitted compiler compatibility path uses the deterministic oracle-call ceiling without a wall-clock cutoff. Exhaustion preserves every original hard constraint and returns unavailable.

## 5. Capacity and performance profile

Pilot bounds are 256 KiB raw input, 256 constraints, 128 success predicates, 64 soft dimensions, 127 caller actions without explicit abstain, 128 compiled actions and 257 conflict-oracle calls. No network or synchronous central RPC occurs in the deterministic compiler path.

Latency claims require a named host, compiler, build profile, input class and exact source. A normal successful compile measurement cannot be reused as a conflict-extraction measurement.

## 6. Concrete verification cases

- `OBJ-DETAIL-01`: disjoint scalar intervals produce an inclusion-minimal conflict and remove irrelevant atoms.
- `OBJ-DETAIL-02`: equivalent reordered inputs produce identical semantic digests.
- `OBJ-DETAIL-03`: unsupported language or oracle exhaustion never weakens the legal set.
- `OBJ-DETAIL-04`: principal network prohibition dominates task text.
- `OBJ-DETAIL-05`: intrinsic abstain cannot be forbidden or confirmation-gated.
- `OBJ-DETAIL-06`: 127 caller actions plus implicit abstain compile to 128; 128 without abstain reject.
- `OBJ-DETAIL-07`: source, schema, profile, normalization or intent digest mismatch fails before native compile.

Native objective test files and symbols are registered in the implementation map. Product-composition fixtures in `codex-rs/hepta-intelligence/src/objective_product_tests.rs` prove atomic publication, exact retry, semantic-identity conflict and anchored recovery at the source boundary. Green fixtures are still not target-host qualification, independent acceptance or efficacy receipts.

## 7. Integration, rollback and capability ceiling

Compile before adaptive selection. NDU and Control consume the frozen objective but cannot mutate its hard constraints, observer requirements or legal effects. Rollback reuses a prior objective only when request/principal compatibility and current revocation checks pass; otherwise it starts a newly authorized run or abstains.

The candidate issues no runtime, model, provider, network-path, tool, secret, Matrix, fleet, acceptance, merge, promotion or release authority. The product caller receives only a host-authorized `File`; it does not open arbitrary paths. Source composition is present, while target-host qualification, independent review, activation and exact-head workflow success remain separately governed.

## 8. Current native implementation

- **Implemented entrypoints:** `admit_objective_v1`, `compile_admitted_objective_v1` and the compatibility `admit_and_compile_objective_v1` in [codex-rs/hepta-objective/src/objective_admission.rs](../../../codex-rs/hepta-objective/src/objective_admission.rs); `check_feasibility_v1` in [codex-rs/hepta-objective/src/feasibility.rs](../../../codex-rs/hepta-objective/src/feasibility.rs). The raw legacy compiler is qualification-only behind `legacy-prevalidated-objective`.
- **Product caller:** `ObjectiveProductCallerV1` and `DurableObjectivePublicationStoreV1` in [codex-rs/hepta-intelligence/src/objective_product.rs](../../../codex-rs/hepta-intelligence/src/objective_product.rs) authenticate/admit/compile and atomically persist the admission receipt, complete objective and run-start snapshot.
- **State and recovery:** The compiler is stateless. The named caller uses a bounded checksummed append-only file, exclusive writer lock, sync-before-publish, idempotent exact replay, semantic conflict fencing and optional acknowledged-anchor recovery; incomplete unacknowledged tail repair never replaces corrupt acknowledged history.
- **Source tests:** [codex-rs/hepta-objective/src/objective_admission_tests.rs](../../../codex-rs/hepta-objective/src/objective_admission_tests.rs), [codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs](../../../codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs), [codex-rs/hepta-intelligence/src/objective_product_tests.rs](../../../codex-rs/hepta-intelligence/src/objective_product_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md](../../../docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md), [docs/modules/objective.compiler/SEMANTIC_SUPPORT.md](../../../docs/modules/objective.compiler/SEMANTIC_SUPPORT.md), [docs/modules/objective.compiler/IMPLEMENTATION_MAP.json](../../../docs/modules/objective.compiler/IMPLEMENTATION_MAP.json).
- **Remaining work:** exact-head and synthetic-merge workflow closure, named-host ordinary/conflict latency and resource measurements, current revocation/downstream runtime reconciliation, independent acceptance and activation.
