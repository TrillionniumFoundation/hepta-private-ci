# control.runtime: implementation design

Parent: `docs/modules/control.runtime/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-control-plane`.
Packages: `RCP-1-RUNTIME-CONTROL-PLANE`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`collect_snapshot(owner_summaries, source_frontiers, expiry) -> GlobalStateSnapshot`; `plan(snapshot, objective, bounded_candidates, budgets) -> FeasiblePlanReceipt`; `request_execution_grants(plan) -> GrantRequestSet`. Planning does not execute effects or issue capabilities. Local motor/reflex control consumes a previously qualified envelope without synchronous global optimization.

## 3. State records and transaction design

`global_state_snapshot` is a coherent, revision-bound projection of readiness, resource, risk, organ and NDU summaries with freshness and missing-data masks. `optimization_decision` records complete candidates, feasibility rejections, chosen plan/frontier, algorithm, bounds, time/iteration limits, fallback and uncertainty. Owners remain authoritative for their facts and terminal outcomes.

## 4. Deterministic algorithm and scheduling

Freeze objective and body/artifact generations; validate fresh owner contributions; reserve essential floors; reject authority/writer/protocol/resource conflicts; enumerate at most the configured candidate count; Pareto-filter; apply registered deterministic scalarization or abstain. Record exact optimum only when exhaustively certified over that bounded candidate set; otherwise disclose the heuristic/search bound. Missing contributions increase uncertainty or make candidates unavailable.

## 5. Capacity and performance profile

Pilot <=128 plans, <=24 registered organ roles per initial composition, <=32 resource dimensions, explicit bounded planning period and deadline. No fleet-wide RPC in a local safety loop. Report data age, solver iterations, rejected constraints, endowment residual and p99 plan time.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- RCP-01: stale owner summary cannot be silently treated as current zero cost.
- RCP-02: essential safety/rollback/evidence floors survive overload.
- RCP-03: changed body/configuration generation invalidates a prepared plan.
- RCP-04: central outage leaves qualified local reflex/fallback operational; a selected plan alone cannot invoke an effect.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

NDU values supported feasible consequences; this controller neither owns the world model nor authorizes itself. Rollback revalidates current owners/fences and loads a compatible prior plan policy for later runs, never stale grants.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.
