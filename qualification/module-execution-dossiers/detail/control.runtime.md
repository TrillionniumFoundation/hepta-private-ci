# control.runtime: implementation design

Parent: `docs/modules/control.runtime/TECHNICAL.md`. Lane: `LANE-D-OBJECTIVE-VALUE`.
Status: hardened source candidate implemented; one bounded read-only Agentd caller is composed, while promotion-eligible global product composition, production durability, independent acceptance, activation and release remain separate. Common requirements: `../EXECUTION_SEMANTICS.md`, `../TECHNICAL.md` and `docs/readiness/CONTROL_RUNTIME_EXECUTION.md`.

## 1. Source and work envelope

Root: `codex-rs/hepta-control-plane`. Owner-local package: `RCP-1-RUNTIME-CONTROL-PLANE`; NDU integration package: `RCP-2-NDU-HIERARCHY-INTEGRATION` in `docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json`. Exact symbol and test mappings are in `docs/modules/control.runtime/IMPLEMENTATION_MAP.json`.

The planner is distinct from the desired-state FSM, organ host, local cart controller and timing reference. It has no effect or capability-issuance authority.

## 2. Native operations and contract details

Implemented operations are:

```text
collect_snapshot(SnapshotRequestV1, OwnerSummaryV1[]) -> GlobalStateSnapshotV1
canonical_resource_profile_digest(ResourceReservationV1[]) -> Digest32
prepare_plan_hardened(snapshot, PlanningRequestV1) -> PreparedPlanInputV1
evaluate_prepared_plan_with_ndu(snapshot, prepared, NduPlanningInputV1, now) -> EvaluatedPlanV1
finalize_plan(snapshot, prepared, ndu_evaluation, now) -> FeasiblePlanReceiptV1
request_execution_grants(snapshot, prepared, receipt, now) -> GrantRequestSetV1
authenticate_owner_summary_v1(summary, proof, verifier) -> AuthenticatedOwnerSummaryV1
compose_global_plan_v1(GlobalPlanCompositionInputV1) -> GlobalPlanCompositionV1
handoff_grant_requests_v1(requests, independent_authority) -> caller-owned results
plan_observed_context(ObservedContextV1) -> ObservedContextPlanV1
PlannerJournalV1::{append, record_decision, select_plan, revoke, reopen}
StrictPlannerJournalV1::reopen(bytes) -> semantic replay checked journal
```

The production-facing preparation path derives `resource_profile_digest` from the exact canonical resource reservations. Low-level `prepare_plan` remains available for source fixtures and compatibility, but composed callers use `prepare_plan_hardened`.

Planning remains two-stage. Control owns snapshot/resource feasibility; `utility.ndu` computes the actual utility/Pareto evaluation; finalization consumes the digest-bound NDU projection. Every planner envelope and grant-request set remains `AuthorityPosture::DENY_ALL`.

## 3. Snapshot, state and transaction design

`GlobalStateSnapshotV1` binds objective, body generation, configuration, revocation frontier, owner revisions, observation/expiry times, readiness, source frontiers and support. Missing, stale and unavailable required owner state blocks planning.

`PreparedPlanInputV1` retains source and feasible candidate-set digests plus resource rejections. `prepare_plan_hardened` additionally requires the caller's `resource_profile_digest` to equal the canonical digest of every sorted `(axis, endowment, essential_floor)` reservation. Reusing one opaque profile identity with changed budgets therefore fails before candidate filtering.

`NduPlanEvaluationV1` binds the NDU owner's opaque evaluation digest plus the exact evaluated/rejected/Pareto/advisory projection. `FeasiblePlanReceiptV1` binds snapshot, configuration, revocation frontier, candidate sets, resource profile, rejections, NDU policy/evaluation/binding digests, disposition, uncertainty, selection and expiry.

`PlannerJournalV1` remains the bounded byte/hash-chain reference. `StrictPlannerJournalV1::reopen` first verifies the V1 byte chain and then semantically replays it: snapshot/decision identities must match their payloads, a selection requires a preceding decision, a revoked decision cannot be selected later, and revocation cannot target an unknown decision. This closes hash-valid state-machine forgery inside the reference format; it does not turn the reference bytes into a production store.

## 4. Authenticated composition and authority boundary

`AuthenticatedOwnerSummaryV1` cannot be constructed directly outside the composition module. `authenticate_owner_summary_v1` requires a non-empty proof digest and a caller-supplied verifier to accept the exact summary/proof pair. The concrete cryptographic verifier remains owned by the producer/host integration; Control does not invent trust.

`compose_global_plan_v1` sequences:

1. already-authenticated owner summaries;
2. coherent `collect_snapshot`;
3. canonical resource-profile verification through `prepare_plan_hardened`;
4. actual `utility.ndu` evaluation through `evaluate_prepared_plan_with_ndu`;
5. sealed final receipt;
6. deny-all `GrantRequestSetV1` construction.

`handoff_grant_requests_v1` is an explicit independent-authority seam. It forwards each immutable `GrantRequestV1` to a caller-owned authority function and does not interpret, cache, mint or execute the returned authority result. A concrete `kernel.authority` product adapter is still an integration gate.

## 5. Current bounded product caller

`codex-rs/hepta-agentd/src/cognitive_context.rs` is a real bounded read-only caller of `plan_observed_context`. It supplies verified record count, exact serialized context bytes, source/read digests, owner identity and process generation. The helper compares `read-context` with `abstain` using actual NDU evaluation and the hardened canonical byte-budget resource profile.

Planner timestamps in this Agentd path now use a process-generation-local `Instant` origin rather than Unix wall clock. Unix time remains used only by store APIs whose contracts explicitly require Unix seconds. This removes NTP/admin clock adjustment from the planner's request-local freshness domain.

This caller proves a narrow read-only composition, not a promotion-eligible global planning caller and not fleet/effect activation.

## 6. Deterministic algorithm and scheduling

1. Canonicalize and validate owner summaries.
2. Reject mixed objective/body/configuration and future timestamps.
3. Compute missing, stale and unavailable masks and exact snapshot expiry.
4. Canonicalize candidates, owners, payload digests and resource axes.
5. Canonically digest exact resource endowments/floors and reject binding mismatch.
6. Reserve every essential floor before adaptive allocation.
7. Reject candidates exceeding remaining capacity before NDU evaluation.
8. Require intrinsic abstain in the feasible set.
9. Execute the independently owned NDU kernel and bind complete candidate coverage.
10. Reject omitted/injected candidates, policy drift, binding drift or inconsistent disposition.
11. Publish a bounded-set plan receipt or unresolved slow-path result.
12. Revalidate current snapshot, prepared input, plan receipt, payload and expiry before grant-request construction.
13. Forward grant requests only through an independently owned authority seam.

No global planner call is permitted in a qualified reflex, actuator watchdog or emergency-stop loop.

## 7. Capacity and performance profile

Pilot ceilings remain 32 owners, 128 candidates, 32 required owners per candidate, 64 final payloads per candidate, 32 resource axes and 4096 journal entries per bounded file. All collections and sorting are bounded.

Named-host p95/p99 latency, saturation, restart/reopen timing and fault-injection results remain evidence gates. Source limits are not host-performance claims.

## 8. Concrete verification cases

- `RCP-01`: stale or missing required owner blocks preparation.
- `RCP-02`: essential floors filter an over-budget candidate before NDU while preserving abstain.
- `RCP-03`: changed snapshot, body, configuration or revocation frontier invalidates the prepared plan.
- `RCP-04`: local fallback/stop remains independent during central outage.
- `RCP-05`: missing resource axes reject instead of becoming zero.
- `RCP-06`: evaluated and rejected NDU IDs partition the exact feasible set.
- `RCP-07`: tampered NDU binding or uncertainty rejects finalization.
- `RCP-08`: grant requests bind final payloads and remain deny-all.
- `RCP-09`: journal reopen preserves a valid selection.
- `RCP-10`: truncation/tampering fails closed and revocation prevents reselection.
- `RCP-11`: resource-profile digest is canonical and order independent.
- `RCP-12`: opaque/stale resource-profile binding rejects before preparation.
- `RCP-13`: a hash-valid selection before its decision is rejected by strict reopen.
- `RCP-14`: a hash-valid selection after revocation is rejected by strict reopen.
- `RCP-15`: owner summaries cannot enter global composition without authenticator acceptance.
- `RCP-16`: authenticated owners + real NDU + sealed plan + grant handoff compose without authority leakage.
- `RCP-17`: the bounded Agentd caller uses a monotonic planner clock and canonical byte-budget resource profile.

Native tests are recorded in the implementation map. Test identities are not execution receipts.

## 9. Current native implementation

**Implemented entrypoints:** `collect_snapshot` in [codex-rs/hepta-control-plane/src/planner.rs](../../../codex-rs/hepta-control-plane/src/planner.rs); `prepare_plan_hardened` in [codex-rs/hepta-control-plane/src/planner_hardened.rs](../../../codex-rs/hepta-control-plane/src/planner_hardened.rs); `evaluate_prepared_plan_with_ndu` in [codex-rs/hepta-control-plane/src/planner_ndu.rs](../../../codex-rs/hepta-control-plane/src/planner_ndu.rs); `compose_global_plan_v1` in [codex-rs/hepta-control-plane/src/planner_composition.rs](../../../codex-rs/hepta-control-plane/src/planner_composition.rs); `plan_observed_context` in [codex-rs/hepta-control-plane/src/planner_context.rs](../../../codex-rs/hepta-control-plane/src/planner_context.rs); `StrictPlannerJournalV1` in [codex-rs/hepta-control-plane/src/planner_journal_strict.rs](../../../codex-rs/hepta-control-plane/src/planner_journal_strict.rs); `OrganHostV1` in [codex-rs/hepta-control-plane/src/organ_runtime.rs](../../../codex-rs/hepta-control-plane/src/organ_runtime.rs).

- **Narrow composition:** Agentd context delivery is an actual read-only caller. It is not the promotion-eligible global planner caller tracked by the maturity gate.
- **Durability:** strict semantic replay is implemented over the bounded reference journal. Production storage still requires an owner-approved store, schema migration, physical durability/fsync profile, retention and backup/restore qualification.
- **Authority:** grant requests are immutable deny-all proposals. Concrete `kernel.authority` binding remains independently owned.
- **External protocol:** owner-local Rust types and composition surfaces are not automatically admitted external wire protocols.
- **Qualification:** exact-head and synthetic-merge CI for this closure candidate must pass before repository-controlled closure is claimed.

## 10. Remaining gates

Repository code now contains the hardened global-composition seam, but the following remain intentionally unclaimed:

- concrete cryptographic owner-summary verifier and named production owner set;
- concrete `kernel.authority` adapter using the registered final-use contract;
- owner-approved production journal/store with migration, fsync, retention and restore evidence;
- canonical external wire-protocol admission where cross-process use is required;
- named-host load/latency/restart/fault-injection evidence;
- independent semantic/security review, operator acceptance, activation, promotion and release.

This candidate grants no model, provider, tool, network, filesystem, secret, fleet, physical effect, acceptance, promotion or release authority.
