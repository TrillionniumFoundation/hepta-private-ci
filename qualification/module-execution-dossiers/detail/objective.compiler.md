# objective.compiler: implementation design

Parent: `docs/modules/objective.compiler/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: source candidate implemented and mapped; a bounded product-composition candidate is implemented, while exact-head qualification, independent acceptance, activation and release remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md`, `docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md` and `docs/contracts/OBJECTIVE_ERRORS.json`.

## 1. Source and work envelope

Root: `codex-rs/hepta-objective`. Packages: `OBJ-0-OBJECTIVE-CONTRACTS`, `OBJ-1-OBJECTIVE-COMPILER`. Exact operation-to-symbol and test mappings are in `docs/modules/objective.compiler/IMPLEMENTATION_MAP.json`.

This candidate changes no authority, effect or writer ownership. The module remains stateless for domain facts. A named product-host candidate now exists in `runtime.agentd`, but it remains candidate-only until exact-head composition qualification and external activation gates pass; immutable objective and run snapshots remain persisted by the `learning.ledger` owner.

## 2. Native operations and contract details

The implemented path is:

```text
decode_source_envelope_json_v1(bytes)
ObjectiveSourceEnvelopeV1::validate_structure()
canonical_objective_intent_digest_v1(envelope)
admit_and_compile_objective_v1(envelope, profile, authenticated_context)
adapt_source(envelope, profile, authenticated_context, admitted_source_digest)
compile(native_envelope)
scalar_conflict(native_envelope)
check_feasibility_v1(grammar, atoms, budget)
```

Admission validates source authentication, principal scope, schema, normalization, profile, source and intent digests before mapping represented fields. Each Source V1 field is either mapped exactly or rejected explicitly; syntactically decoded `ne`, strict inequalities and V1 `in/not_in` do not imply native support. The exact support matrix is `docs/modules/objective.compiler/SEMANTIC_SUPPORT.{md,json}`. Unknown or unrepresentable semantics fail closed. The admission receipt and compiler output carry no effect authority.

`abstain` is intrinsic and confirmation-free. A request cannot forbid it. The compiled action ceiling is 128 including abstain: at most 127 caller actions when abstain is implicit, or 128 when the caller supplies the valid intrinsic action explicitly.

## 3. State, identity and publication

The compiler owns no durable store. Its pure output binds request, principal, authenticated source class, source, schema, selected profile, hard constraints, legal actions, success and terminal predicates, evidence requirements, resource/risk policy and semantic digest. `validate_compiled_objective_v1` recomputes canonical ordering and hard/semantic digests before publication. `prepare_intelligence_run_v1` binds `RunStartSnapshotV1` and writes admission receipt + compile receipt/objective + run snapshot as one `RunStartPublicationV1` frame through the sealed `learning.ledger` durable owner port. The named product-host candidate `runtime.agentd::prepare_and_start_intelligence_run_v1` composes that durable append with runtime admission and preserves the opaque `ProductionObjectiveStartReceiptV1` when runtime admission fails after fsync. The lower-level `start_published_intelligence_run_v1` also accepts only that opaque receipt; the internal deny-all host envelope cannot be used as a public runtime start surface. Agentd also rechecks authority epoch, runtime generation and fence digest before admitting the ephemeral run.

A typed hard conflict produces `ObjectiveConflictReceiptV1`. `CompileDisposition::ExplicitAbstain` is a successful non-error outcome in which abstain is the sole legal action. Stable error meanings are generated from `docs/contracts/OBJECTIVE_ERRORS.json`; Markdown or Rust code may not locally redefine a code.

## 4. Deterministic algorithm and complexity

Decode and normalize bounded fields, authenticate source, map registered units/IDs, classify P0-P4 precedence, intersect scalar or finite-enum domains, close bounded positive action implications and stable-sort all sets. Infeasible hard atoms use deterministic deletion filtering and return an inclusion-minimal conflict set.

Normalization and canonical sorting are `O(n log n)`. A feasibility oracle has profile cost `C(n)`. Inclusion-minimal conflict extraction performs at most `n+1` oracle calls and `O(n C(n))` work. The admitted compiler's scalar compatibility oracle uses `Duration::MAX` so semantic compilation is not host-scheduling dependent. The standalone feasibility API may use a finite wall-clock budget; `Exhausted` and `elapsed` are availability/measurement outputs, not canonical semantic bytes. Exhaustion preserves every original hard constraint and returns unavailable.

## 5. Capacity and performance profile

Pilot bounds are 256 KiB raw input, 256 constraints, 128 success predicates, 64 soft dimensions, 127 caller actions without explicit abstain, 128 compiled actions and 257 conflict-oracle calls. No network or synchronous central RPC occurs in the deterministic compiler path.

Latency claims require a named host, compiler, build profile, input class and exact source. The product-composition workflow records host/compiler identity plus two release-profile receipts on its named Ubuntu runner: a 32-sample authenticated-admission + compile + durable-fsync p50/p95/p99 receipt and a separate 16-sample 256-atom inclusion-minimal-conflict receipt that asserts 257 oracle calls per sample. These are qualification telemetry only and do not satisfy a selected production-host SLA.

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
- **State and recovery:** Stateless outputs bind the immutable source/principal/profile/schema/unit/time/intent tuple; unknown mappings fail closed. `prepare_intelligence_run_v1` supplies the bounded compiler caller and atomically appends `RunStartPublicationV1` to the owner `learning.ledger`; `runtime.agentd::prepare_and_start_intelligence_run_v1` is the named product-host candidate that then admits the frozen runtime snapshot. Anchored reopen replays the same objective/snapshot frame, and a post-fsync runtime failure returns the durable publication receipt for deterministic retry. The native compiler still has no durable objective database.
- **Source tests:** [codex-rs/hepta-objective/src/objective_admission_tests.rs](../../../codex-rs/hepta-objective/src/objective_admission_tests.rs), [codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs](../../../codex-rs/hepta-objective/src/feasibility_exhaustive_tests.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md](../../../docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md), [docs/modules/objective.compiler/IMPLEMENTATION_MAP.json](../../../docs/modules/objective.compiler/IMPLEMENTATION_MAP.json), [docs/modules/objective.compiler/SEMANTIC_SUPPORT.md](../../../docs/modules/objective.compiler/SEMANTIC_SUPPORT.md).
- **Remaining work:** Exact-head/source+synthetic-merge qualification of the new cross-owner caller, independent semantic/security review, selected production-host latency/resource measurements, operator acceptance, activation and release remain external or evidence-gated. Conflict-oracle performance remains a separate measurement path from ordinary/durable publication.
