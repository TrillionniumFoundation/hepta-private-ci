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
canonical_resource_profile_digest(ResourceReservationV1[]) -> Digest32
prepare_plan(snapshot, PlanningRequestV1) -> PreparedPlanInputV1
bind_ndu_plan_evaluation_v1(NduPlanEvaluationInputV1) -> NduPlanEvaluationV1
evaluate_prepared_plan_with_ndu(snapshot, prepared, NduPlanningInputV1, now) -> EvaluatedPlanV1
finalize_plan(snapshot, prepared, ndu_evaluation, now) -> FeasiblePlanReceiptV1
request_execution_grants(snapshot, prepared, receipt, now) -> GrantRequestSetV1
plan_observed_context(ObservedContextV1) -> ObservedContextPlanV1
evaluate_global_plan_v1(authenticator, GlobalPlanningInputV1) -> GlobalPlanningOutputV1
PlannerJournalV1::{append, record_decision, select_plan, revoke, reopen}
PlannerJournalStoreV1::{open, open_with_minimum_head, record_*, select_plan, revoke}
```

Planning is deliberately two-stage. `prepare_plan` owns snapshot, owner and resource-floor feasibility only. The planner core does not duplicate NDU semantics; `evaluate_prepared_plan_with_ndu` is the explicit composition port that calls the `utility.ndu` owner implementation, then binds its result before `finalize_plan`. `evaluate_global_plan_v1` composes authenticated multi-owner admission through that same path and stops at deny-all grant requests.

Every prepared input, evaluation binding, plan receipt and grant-request set is `AuthorityPosture::DENY_ALL`. A grant request is not a capability.

## 3. Snapshot, state and transaction design

`GlobalStateSnapshotV1` binds exact objective, body generation, configuration, revocation frontier, owner revisions, observation/expiry times, readiness, source frontiers and support. Missing, stale and unavailable owner masks are explicit. Any non-empty required mask blocks planning; absence is never treated as zero cost or ready state.

`PreparedPlanInputV1` retains both the source candidate-set digest and the resource-feasible candidate-set digest. It records candidates rejected by essential resource floors. `canonical_resource_profile_digest` canonicalizes axis/endowment/essential-floor tuples, and `prepare_plan` rejects any caller-supplied profile digest that does not equal those exact reservations. Missing resource axes reject instead of becoming zero. Intrinsic abstain must remain feasible.

`NduPlanEvaluationV1` binds the NDU owner’s opaque evaluation digest plus the exact evaluated, rejected, Pareto and advisory candidate projection consumed by Control. Its binding digest is independently recomputed at finalization.

`FeasiblePlanReceiptV1` binds snapshot, configuration, current revocation frontier, both candidate sets, resource rejections, NDU policy/evaluation/binding digests, disposition, uncertainty, selected plan and expiry. It claims only a result over the bounded supplied set.

`PlannerJournalV1` provides a bounded append-only reference for snapshot/decision/selection/revocation records. Reopen validates sequence, predecessor hashes, semantic identities, entry hashes, prior-decision existence and revocation ordering. `PlannerJournalStoreV1` adds a Unix single-writer lock, private-file checks, bounded versioned envelope, write+fsync+atomic-rename+directory-fsync publication, deterministic V0 migration and an optional trusted minimum head that rejects older restored backups. A revoked decision cannot be reselected or resurrected through restart. The trusted head must live outside the journal backup domain.

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
- `RCP-11`: a revoked plan cannot be reselected after reopen.
- `RCP-12`: no receipt claims an optimum outside the bounded candidate set.
- `RCP-13`: operation, payload, resource or required-owner mutation rejects before grant construction.
- `RCP-14`: grant construction revalidates snapshot masks and digest.
- `RCP-15`: NDU policy and resource profile are frozen before evaluation.
- `RCP-16`: changing reservations without recomputing their canonical profile digest rejects preparation.
- `RCP-17`: hash-valid journal bytes with invalid selection ordering fail semantic replay.
- `RCP-18`: durable reopen migrates V0 deterministically and rejects an older backup against the trusted head.
- `RCP-19`: authenticated multi-owner composition rejects a failed owner and binds authentication-evidence drift.
- `RCP-20`: the Agentd context caller supplies planner timestamps from one process-local monotonic clock domain.

Native tests are registered in the implementation map. Product-callsite, production-store and named-host evidence are not inferred from unit tests.

## 7. Integration, rollback and capability ceiling

Control consumes objective and NDU facts through typed, digest-bound inputs while their owners remain authoritative. It cannot write objective, preference, utility, independent evaluation or terminal effect outcomes. `kernel.authority` independently decides every concrete grant immediately before an effect boundary.

Rollback revalidates current owners, frontiers, body/configuration generation and compatible prior policy. It never reuses stale grants. Journal restoration cannot resurrect a revoked selection.

This candidate grants no model, provider, tool, network, filesystem, secret, Matrix, fleet, physical effect, acceptance, merge, promotion or release authority. Exact-head qualification, product composition, independent review, deployment and activation remain governed separately.

## 8. Current native implementation

The native source now contains three intentionally different composition levels:

- **Planner kernel:** `collect_snapshot`, `canonical_resource_profile_digest`, `prepare_plan`, `bind_ndu_plan_evaluation_v1`, `finalize_plan` and `request_execution_grants` live in [planner.rs](../../../codex-rs/hepta-control-plane/src/planner.rs). Their sealed outputs remain `AuthorityPosture::DENY_ALL`.
- **Owner composition:** [planner_ndu.rs](../../../codex-rs/hepta-control-plane/src/planner_ndu.rs) invokes the real `utility.ndu` implementation rather than accepting a self-reported choice. [planner_global.rs](../../../codex-rs/hepta-control-plane/src/planner_global.rs) admits every owner through `OwnerSummaryAuthenticatorV1`, folds authentication evidence into snapshot support, composes the real NDU evaluation and emits only deny-all `GrantRequestSetV1`. No named global product host calls this coordinator yet.
- **Narrow product composition:** [planner_context.rs](../../../codex-rs/hepta-control-plane/src/planner_context.rs) is called by [hepta-agentd/src/cognitive_context.rs](../../../codex-rs/hepta-agentd/src/cognitive_context.rs) for the bounded read-context-versus-abstain decision. The caller now uses a process-local `Instant` epoch for planner observation/deadline time while retaining Unix wall time only for storage-domain timestamps.
- **Durability candidate:** `PlannerJournalV1` performs bounded semantic replay. [planner_store.rs](../../../codex-rs/hepta-control-plane/src/planner_store.rs) adds a Unix single-writer fsync-backed owner store with atomic replace, deterministic legacy migration and caller-supplied trusted-head anti-rollback. This is source-complete durability machinery, not an activated production state directory or an external-effect ledger.
- **Existing organ/runtime surfaces:** `OrganHostV1`, native handoff and the deterministic cart/timing fixtures remain separate from the global optimizer and retain their existing capability ceilings.
- **Source tests:** [planner_tests.rs](../../../codex-rs/hepta-control-plane/src/planner_tests.rs), [planner_ndu_tests.rs](../../../codex-rs/hepta-control-plane/src/planner_ndu_tests.rs), [planner_global_tests.rs](../../../codex-rs/hepta-control-plane/src/planner_global_tests.rs), [planner_journal_tests.rs](../../../codex-rs/hepta-control-plane/src/planner_journal_tests.rs), [planner_store_tests.rs](../../../codex-rs/hepta-control-plane/src/planner_store_tests.rs), [planner_context_tests.rs](../../../codex-rs/hepta-control-plane/src/planner_context_tests.rs) and the ignored named-host profile in [planner_profile_tests.rs](../../../codex-rs/hepta-control-plane/src/planner_profile_tests.rs). Test identities are not pass receipts for an unexecuted candidate.
- **Remaining product work:** select a named authenticated multi-owner host, provision the durable state root and trusted anti-rollback head outside its backup domain, register/admit any cross-process wire profile, submit each final `GrantRequestV1` to independent `kernel.authority` immediately before an effect boundary, reconcile terminal outcomes in the effect owner, and obtain exact-head/synthetic-merge/named-host evidence plus independent acceptance and activation. The Agentd context caller proves only the narrow read-only planning path.
