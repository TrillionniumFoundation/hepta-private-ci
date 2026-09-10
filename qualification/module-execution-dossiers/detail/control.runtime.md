# control.runtime: implementation design

Parent: `docs/modules/control.runtime/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: source candidate global planner and owner-local decision journal implemented; product composition and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md` and `docs/readiness/CONTROL_RUNTIME_EXECUTION.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-control-plane`. Owner-local package: `RCP-1-RUNTIME-CONTROL-PLANE`; NDU integration package: `RCP-2-NDU-HIERARCHY-INTEGRATION` in `docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json`. Exact symbol and test mappings are in `docs/modules/control.runtime/IMPLEMENTATION_MAP.json`.

The planner is distinct from the existing desired-state FSM, organ host, local cart controller and timing reference. It has no effect or capability issuance authority.

## 2. Native operations and contract details

Implemented operations are:

```text
collect_snapshot(SnapshotRequestV1, OwnerSummaryV1[]) -> GlobalStateSnapshotV1
prepare_plan(snapshot, PlanningRequestV1) -> PreparedPlanInputV1
bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1) -> NduPlanEvaluationV1
finalize_plan(snapshot, prepared, ndu_evaluation, now) -> FeasiblePlanReceiptV1
request_execution_grants(snapshot, prepared, receipt, now) -> GrantRequestSetV1
PlannerJournalV1::{append, record_decision, select_plan, revoke, reopen}
```

Planning is deliberately two-stage. `prepare_plan` owns snapshot, owner and resource-floor feasibility only. `utility.ndu` independently computes its evaluation. `finalize_plan` consumes a digest-bound projection and validates complete candidate coverage. Control runtime does not import or duplicate NDU’s utility/Pareto kernel.

Every prepared input, evaluation binding, plan receipt and grant-request set is `AuthorityPosture::DENY_ALL`. A grant request is not a capability.

## 3. Snapshot, state and transaction design

`GlobalStateSnapshotV1` binds exact objective, body generation, configuration, revocation frontier, owner revisions, observation/expiry times, readiness, source frontiers and support. Missing, stale and unavailable owner masks are explicit. Any non-empty required mask blocks planning; absence is never treated as zero cost or ready state.

`PreparedPlanInputV1` retains both the source candidate-set digest and the resource-feasible candidate-set digest. It records candidates rejected by essential resource floors. Missing resource axes reject instead of becoming zero. Intrinsic abstain must remain feasible.

`NduPlanEvaluationV1` binds the NDU owner’s opaque evaluation digest plus the exact evaluated, rejected, Pareto and advisory candidate projection consumed by Control. Its binding digest is independently recomputed at finalization.

`FeasiblePlanReceiptV1` binds snapshot, configuration, current revocation frontier, both candidate sets, resource rejections, NDU policy/evaluation/binding digests, disposition, uncertainty, selected plan and expiry. It claims only a result over the bounded supplied set.

`PlannerJournalV1` provides a bounded append-only reference for snapshot/decision/selection/revocation records. It validates sequence, predecessor hashes, semantic identities and entry hashes on reopen. A revoked decision cannot be reselected or resurrected through restart.

## 4. Deterministic algorithm and scheduling

1. Canonicalize and validate owner summaries.
2. Reject mixed objective/body/configuration and future timestamps.
3. Compute missing, stale and unavailable masks and exact snapshot expiry.
4. Canonicalize candidates, owners, payload digests and resource axes.
5. Reserve each essential floor from its endowment.
6. Reject candidates exceeding remaining capacity before NDU evaluation.
7. Require abstain in the feasible set.
8. Bind the independently produced NDU evaluation and complete candidate partition.
9. Reject omitted/injected candidates, binding drift or inconsistent disposition.
10. Publish a bounded-set plan receipt or unresolved slow-path result.
11. Revalidate current snapshot, prepared input, plan receipt, payload and expiry before emitting grant requests.

No global planner call is permitted in a qualified reflex, actuator watchdog or emergency-stop loop. A central outage leaves those local controls independent.

## 5. Capacity and performance profile

Pilot ceilings are 32 owners, 128 candidates, 32 required owners per candidate, 64 final payloads per candidate, 32 resource axes and 4096 journal entries per bounded file. Every collection, sort, retry and allocation is bounded.

Metrics include source ages, missing/stale/unavailable masks, resource rejection counts, feasible candidate count, Pareto size, NDU disposition, uncertainty digest, preparation/finalization latency, journal reopen time and grant-request count. p95/p99 values are claims only after named-host measurements.

## 6. Concrete verification cases

- `RCP-01`: stale or missing required owner blocks preparation.
- `RCP-02`: essential floors filter an over-budget candidate before NDU while preserving abstain.
- `RCP-03`: changed snapshot, body, configuration or revocation frontier invalidates the prepared plan.
- `RCP-04`: local fallback/stop remains independent during central outage.
- `RCP-05`: missing resource axes reject instead of becoming zero.
- `RCP-06`: evaluated and rejected NDU IDs must partition the exact feasible set.
- `RCP-07`: tampered NDU binding or uncertainty rejects finalization.
- `RCP-08`: grant requests bind final payloads and remain deny-all.
- `RCP-09`: journal reopen preserves selection.
- `RCP-10`: journal truncation/tampering fails closed and revocation prevents reselection.

Native tests are registered in the implementation map. Product-callsite, production-store and named-host evidence are not inferred from unit tests.

## 7. Integration, rollback and capability ceiling

Control consumes objective and NDU facts through typed, digest-bound inputs while their owners remain authoritative. It cannot write objective, preference, utility, independent evaluation or terminal effect outcomes. `kernel.authority` independently decides every concrete grant immediately before an effect boundary.

Rollback revalidates current owners, frontiers, body/configuration generation and compatible prior policy. It never reuses stale grants. Journal restoration cannot resurrect a revoked selection.

This candidate grants no model, provider, tool, network, filesystem, secret, Matrix, fleet, physical effect, acceptance, merge, promotion or release authority. Exact-head qualification, product composition, independent review, deployment and activation remain governed separately.
