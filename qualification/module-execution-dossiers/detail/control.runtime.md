# control.runtime: implementation design

Parent: `docs/modules/control.runtime/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: source candidate global planner, canonical resource binding, semantic/durable decision journal and independent authority bridge implemented; the read-only Agentd context caller is composed, while general global producer/effect composition and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md` and `docs/readiness/CONTROL_RUNTIME_EXECUTION.md`.

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
canonical_resource_profile_digest(ResourceReservationV1[]) -> Digest32
evaluate_prepared_plan_with_ndu(snapshot, prepared, NduPlanningInputV1, now) -> EvaluatedPlanV1
plan_global_v1(authenticated_owner_ports, ndu_port, request) -> GlobalPlanningReceiptV1
claim_execution_grant_v1(authority, request_set, index, subject, destination, signed_grant) -> ClaimedExecutionGrantV1
PlannerJournalV1::{append, record_decision, select_plan, revoke, reopen}
PlannerJournalStoreV1::{open, commit, reopen, restore_backup}
```

Planning is deliberately two-stage. `prepare_plan` owns snapshot, owner and resource-floor feasibility only. `utility.ndu` independently computes its evaluation. `finalize_plan` consumes a digest-bound projection and validates complete candidate coverage. Control runtime does not import or duplicate NDU’s utility/Pareto kernel.

Every prepared input, evaluation binding, plan receipt and grant-request set is `AuthorityPosture::DENY_ALL`. A grant request is not a capability.

## 3. Snapshot, state and transaction design

`GlobalStateSnapshotV1` binds exact objective, body generation, configuration, revocation frontier, owner revisions, observation/expiry times, readiness, source frontiers and support. Missing, stale and unavailable owner masks are explicit. Any non-empty required mask blocks planning; absence is never treated as zero cost or ready state.

`PreparedPlanInputV1` retains both the source candidate-set digest and the resource-feasible candidate-set digest. It records candidates rejected by essential resource floors. Missing resource axes reject instead of becoming zero. Intrinsic abstain must remain feasible. The caller-supplied resource-profile digest must equal `canonical_resource_profile_digest` over the stable-sorted axis/endowment/essential-floor reservations; a semantic budget change cannot reuse a prior label.

`NduPlanEvaluationV1` binds the NDU owner’s opaque evaluation digest plus the exact evaluated, rejected, Pareto and advisory candidate projection consumed by Control. Its binding digest is independently recomputed at finalization.

`FeasiblePlanReceiptV1` binds snapshot, configuration, current revocation frontier, both candidate sets, resource rejections, NDU policy/evaluation/binding digests, disposition, uncertainty, selected plan and expiry. It claims only a result over the bounded supplied set.

`PlannerJournalV1` provides a bounded append-only reference for snapshot/decision/selection/revocation records. It validates sequence, predecessor hashes, semantic identities, entry hashes and Decision -> Selection -> Revocation state transitions on append and reopen. `PlannerJournalStoreV1` adds a schema/digest envelope, synced atomic replacement, committed frontier, bounded backup and raw-v1 migration. A crash may recover only the bytes matching the committed frontier; an older backup cannot resurrect a committed revocation.

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

Metrics include source ages, missing/stale/unavailable masks, resource rejection counts, feasible candidate count, Pareto size, NDU disposition, uncertainty digest, preparation/finalization latency, journal reopen time and grant-request count. The dedicated control-runtime workflow executes a release-mode full-ceiling probe at 32 owners, 128 candidates, 32 required owners per candidate, 32 resource axes and 4096 NDU contributions and records source/tree, host/compiler identity, p50/p95/p99/max and high-water RSS. Those values become evidence only for that exact recorded host/candidate.

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
- `RCP-16`: canonical resource-profile binding rejects endowment/floor drift.
- `RCP-17`: semantically forged journals fail reopen even with an internally valid hash chain.
- `RCP-18`: committed-frontier recovery cannot restore an older pre-revocation backup.
- `RCP-19`: multi-owner `plan_global_v1` executes the real NDU owner port and emits only deny-all grant requests while missing owners/mixed clocks fail closed.
- `RCP-20`: independent `kernel.authority` signed final-use claims bind the request set, operation scope and final payload, use single-use nonces and revalidate immediately before the effect closure.

Native tests are registered in the implementation map. Product-callsite, production-store and named-host evidence are not inferred from unit tests.

## 7. Integration, rollback and capability ceiling

Control consumes objective and NDU facts through typed, digest-bound inputs while their owners remain authoritative. It cannot write objective, preference, utility, independent evaluation or terminal effect outcomes. `kernel.authority` independently decides every concrete grant immediately before an effect boundary.

Rollback revalidates current owners, frontiers, body/configuration generation and compatible prior policy. It never reuses stale grants. Journal restoration cannot resurrect a revoked selection.

This candidate grants no model, provider, tool, network, filesystem, secret, Matrix, fleet, physical effect, acceptance, merge, promotion or release authority. Exact-head qualification, product composition, independent review, deployment and activation remain governed separately.

## 8. Current native implementation

`examples/cart_closed_loop.rs` runs the existing typed cart sensor/controller/actuator loop and emits a bounded CSV trace. It uses the same Q24 simulator rather than another plant implementation. Simulation ticks are not elapsed real time; no hardware, HIL or physical-safety qualification is implied.

- **Implemented entrypoints:** `collect_snapshot`, `prepare_plan`, `canonical_resource_profile_digest`, `finalize_plan` and `request_execution_grants` in [codex-rs/hepta-control-plane/src/planner.rs](../../../codex-rs/hepta-control-plane/src/planner.rs); `evaluate_prepared_plan_with_ndu` in [planner_ndu.rs](../../../codex-rs/hepta-control-plane/src/planner_ndu.rs); `plan_global_v1` in [planner_global.rs](../../../codex-rs/hepta-control-plane/src/planner_global.rs); `plan_observed_context` in [planner_context.rs](../../../codex-rs/hepta-control-plane/src/planner_context.rs); `claim_execution_grant_v1` in [planner_authority.rs](../../../codex-rs/hepta-control-plane/src/planner_authority.rs); `PlannerJournalStoreV1` in [planner_store.rs](../../../codex-rs/hepta-control-plane/src/planner_store.rs); plus `OrganHostV1`, native graph admission and the synthetic cart reference.
- **State and recovery:** GlobalStateSnapshotV1 binds owner readiness/frontiers and expiry; missing/stale owners block planning. PlannerJournalV1 provides bounded hash-chain replay. OrganHostV1 runs trusted compiled-in read-only handlers and is not a sandbox or effect executor. Failed owner-callback restoration now quarantines predecessor dispatch and retains rollback errors; this is not a durable writer migration service. Native handoff matches host-owned protocol/profile/version/schema before graph construction. SyntheticCartIoV1 owns only an in-memory deterministic Q24 plant; read_sensor checks age/calibration and dispatch checks actuator identity, observation binding and DENY_ALL before a simulator step. Recreating the adapter resets this simulated plant; it is not physical-device recovery.
- **Source tests:** [codex-rs/hepta-control-plane/src/planner_tests.rs](../../../codex-rs/hepta-control-plane/src/planner_tests.rs), [codex-rs/hepta-control-plane/src/planner_journal_tests.rs](../../../codex-rs/hepta-control-plane/src/planner_journal_tests.rs), [codex-rs/hepta-control-plane/src/organ_runtime_tests.rs](../../../codex-rs/hepta-control-plane/src/organ_runtime_tests.rs), [codex-rs/hepta-control-plane/src/organ_wire_tests.rs](../../../codex-rs/hepta-control-plane/src/organ_wire_tests.rs), [codex-rs/hepta-control-plane/src/embodiment/io.rs](../../../codex-rs/hepta-control-plane/src/embodiment/io.rs). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [docs/readiness/CONTROL_RUNTIME_EXECUTION.md](../../../docs/readiness/CONTROL_RUNTIME_EXECUTION.md), [codex-rs/hepta-control-plane/src/ORGAN_RUNTIME.md](../../../codex-rs/hepta-control-plane/src/ORGAN_RUNTIME.md), [codex-rs/hepta-control-plane/src/ORGAN_WIRE.md](../../../codex-rs/hepta-control-plane/src/ORGAN_WIRE.md), [docs/readiness/EMBODIED_TYPED_IO.md](../../../docs/readiness/EMBODIED_TYPED_IO.md).
- **Remaining work:** The narrow Agentd context caller is now registered and routes through the common global orchestrator using a process-owned monotonic clock. Repository source also includes authenticated owner-port composition, an fsync/frontier journal store candidate and an independent signed kernel-authority bridge. Remaining product work is to select concrete authenticated runtime.fleet/kernel.evidence producer adapters, attach the journal store to that global product writer, attach claimed authority tokens to the selected physical effect adapter, and qualify terminal reconciliation on the deployed target. HIL/device safety, operator acceptance, activation, promotion and release remain separate qualification/governance facts.

## 9. Final source-closure boundaries

The product-visible cognitive-context adapter is intentionally narrow: it proves that a real Agentd caller can enter the same `plan_global_v1` path as a multi-owner composition without creating a second planner. General global composition is represented by typed `AuthenticatedOwnerPortV1` and `NduPlanningPortV1` boundaries; the source test exercises two required owners and the real NDU evaluator. This does not assert that the selected production fleet/evidence adapters have been deployed.

`claim_execution_grant_v1` is the explicit handoff to the pre-existing `kernel.authority` final-use owner. Control never signs or manufactures `VerifiedUseToken`. The authority owner validates signature, current epoch/revocation state, single-use nonce and the exact request/scope/payload binding; the token is consumed by `with_verified_use` at the final effect closure.

The source candidate is therefore materially beyond the prior planner-only state, but `productionImplementation` remains false until the named global product writer and physical effect caller are selected and exact-candidate qualification/independent acceptance complete.
