# objective.compiler: implementation design

Parent: `docs/modules/objective.compiler/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-objective`.
Packages: `OBJ-0-OBJECTIVE-CONTRACTS`, `OBJ-1-OBJECTIVE-COMPILER`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`compile(ObjectiveSourceEnvelopeV1, baseline_profile) -> ObjectiveCompileReceiptV1 | ObjectiveConflictReceiptV1`; `check_feasibility(typed_constraints, oracle_budget) -> Feasible | Infeasible | Unsupported | Exhausted`. The deterministic grammar is the interval/finite-set/action-implication subset in EXECUTION_SEMANTICS. Model-assisted intent extraction emits an untrusted candidate IR that must pass this same compiler.

## 3. State records and transaction design

The compiler owns no durable fact store. The caller persists immutable ObjectiveFunctionV1 and RunStartSnapshotV1 with request/principal, success/terminal predicates, hard constraints, legal/forbidden actions, evidence sources, resource/risk limits, revision and digest. A semantic goal/scope/acceptance change produces a new run revision, never a mutable field update inside the current run.

## 4. Deterministic algorithm and scheduling

Bound and decode source fields; normalize units/time/IDs; classify precedence; reject unknown operators; intersect scalar/enum constraints and solve bounded action implications; on infeasibility run deterministic deletion filtering with at most n+1 oracle calls; return an inclusion-minimal conflict set. O(n log n) applies to normalization/sorting only; the whole algorithm also pays O(n C(n)) conflict-oracle work. Exhaustion preserves all constraints and returns unavailable/ask.

## 5. Capacity and performance profile

Canonical pilot <=256 KiB envelope, <=256 constraints, <=128 success predicates and <=128 action classes; conflict-oracle calls <=257. Freeze CPU/wall-clock budgets before evaluation; no network on deterministic compile path. Record oracle count, elapsed work and unsupported dimensions.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- OBJ-DETAIL-01: [0,1] intersect [2,3] is infeasible and an irrelevant atom is removed from the conflict core.
- OBJ-DETAIL-02: reorder equivalent constraints -> identical canonical IR and conflict ordering.
- OBJ-DETAIL-03: unknown nonlinear predicate or oracle exhaustion never weakens the legal action set.
- OBJ-DETAIL-04: task text requesting network cannot override an explicit principal prohibition.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Compile before adaptive selection. Utility and neural modules consume the frozen objective but cannot replace it with an easier target. C1 includes a genuine source-envelope-to-host mapping. Rollback retains the original principal and semantics or starts a newly authorized run.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.
