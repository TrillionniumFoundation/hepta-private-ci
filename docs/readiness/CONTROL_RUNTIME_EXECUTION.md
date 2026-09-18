# Control runtime execution specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness  
**Module:** `control.runtime`  
**Source target:** `codex-rs/hepta-control-plane`  
**Primary owner:** `runtime-control`  
**Deputy:** `security-authority`  
**Authority delta:** none

## 1. Scope and non-claims

`control.runtime` constructs one bounded global planning snapshot, preserves essential resource floors, consumes one independently produced NDU evaluation through a typed owner port, and emits an immutable plan receipt plus optional execution-grant requests. It neither evaluates utility on behalf of `utility.ndu` nor issues capabilities on behalf of `kernel.authority`.

The repository implementation is a deterministic, authority-free reference suitable for source qualification. It does not establish a production caller, production writer, independently accepted deployment, hardware control, operator acceptance, activation, promotion or release. Every output produced by this module carries `AuthorityPosture::DENY_ALL`.

The global planner is distinct from:

- `ControlState`, which owns only revision- and authority-epoch-fenced desired control state;
- `OrganHostV1`, which hosts one-hop, compiled-in, read-only organ handlers;
- the cart simulator and fixed-priority timing reference, which exercise local embodied-control semantics;
- `utility.ndu`, which owns aggregation, feasibility, Pareto and scalarization semantics;
- `kernel.authority`, which alone may issue an operation- and final-payload-bound grant.

## 2. End-to-end control flow

The canonical planning flow is two-stage across an owner boundary:

```text
owner summaries + SnapshotRequestV1
  -> collect_snapshot
  -> GlobalStateSnapshotV1

GlobalStateSnapshotV1 + bounded plan candidates + resource reservations
  -> prepare_plan
  -> PreparedPlanInputV1

PreparedPlanInputV1 candidate set
  -> utility.ndu evaluates through its registered profile
  -> NduPlanEvaluationInputV1
  -> bind_ndu_plan_evaluation_v1
  -> NduPlanEvaluationV1

GlobalStateSnapshotV1 + PreparedPlanInputV1 + NduPlanEvaluationV1
  -> finalize_plan
  -> FeasiblePlanReceiptV1

current snapshot + prepared input + feasible receipt
  -> request_execution_grants
  -> GrantRequestSetV1
  -> independent kernel.authority decision
```

`prepare_plan` never selects by utility. `finalize_plan` never recomputes NDU. `request_execution_grants` never converts a request into a grant. This separation prevents the global planner from owning utility facts or self-authorizing its recommendation.

## 3. Coherent owner snapshot

Each `OwnerSummaryV1` binds:

- owner identity and owner-local revision;
- immutable objective digest;
- body generation;
- configuration digest;
- observation and expiry times in one declared monotonic domain;
- readiness posture;
- source-frontier digest;
- support digest.

`SnapshotRequestV1` binds the required owner set, objective, body generation, configuration, current revocation frontier, a snapshot-policy digest, collection time, maximum owner age and snapshot expiry. The resulting snapshot additionally binds the required-owner-set digest and the exact maximum-age policy.

`collect_snapshot` stable-sorts owners, rejects duplicates, rejects future observations, rejects mixed objective/body/configuration values and records three explicit masks:

- `missing_owner_ids`;
- `stale_owner_ids`;
- `unavailable_owner_ids`.

The resulting `GlobalStateSnapshotV1` may be stored as an observation even when one mask is non-empty, but it is not eligible for planning. Missing or stale values are never converted to zero cost, zero risk, zero uncertainty or ready state.

Snapshot expiry is the minimum of the requested expiry and every admitted owner-summary expiry. The snapshot digest covers all identities, revisions, times, states, frontiers and masks. A consumer recomputes the digest before use.

## 4. Candidate preparation and essential floors

A `PlanCandidateV1` binds:

- semantic candidate identity;
- operation identity;
- plan digest;
- required owners;
- final payload digests;
- explicit per-axis resource costs.

Candidate count is bounded to 128. Required owners are bounded to 32 and payload digests to 64 per candidate. Candidate IDs, owner IDs and resource axes are duplicate-free after canonical sorting. Plan and final-payload digests must be non-zero.

`ResourceReservationV1` separates total endowment from an essential floor. The floor reserves capacity for safety, rollback, evidence, recovery and operator control before an adaptive candidate can consume the resource:

```text
available_for_plan(axis) = endowment(axis) - essential_floor(axis)
```

Both terms are non-negative fixed-point values, and the floor cannot exceed the endowment. Every candidate must explicitly report each registered resource axis; missing axes are unavailable rather than zero. Unknown axes reject rather than widening the budget.

The evaluation-policy digest and resource-profile digest are frozen in the planning request before candidate filtering. At least one explicit resource reservation is required in the pilot; an empty collection cannot silently mean an unbounded or zero-resource profile.

The resource-profile digest is no longer a caller-chosen label. `canonical_resource_profile_digest` stable-sorts every `ResourceReservationV1` and commits the axis, total endowment and essential floor. `prepare_plan` recomputes that digest after validation and fails with `ResourceProfileMismatch` before resource filtering if the supplied digest differs. Reordering an equal profile is stable; changing a floor or endowment changes the digest.

`prepare_plan` filters resource-infeasible candidates before NDU evaluation and records their IDs in `resource_rejected_candidate_ids`. The intrinsic `abstain` candidate must remain feasible after this filter. The digest of the source candidate set and the digest of the feasible candidate set are both retained, so resource filtering cannot be hidden.

## 5. Typed NDU owner port

Control runtime consumes NDU only through `NduPlanEvaluationV1`. The adapter input contains:

- objective and body generation;
- NDU evaluation-policy digest;
- opaque NDU evaluation digest;
- complete evaluated and rejected candidate ID sets;
- Pareto candidate IDs;
- optional advisory candidate ID;
- uncertainty digest;
- one bounded disposition.

The adapter canonicalizes all sets, rejects duplicates, requires evaluated and rejected sets to be disjoint, requires every Pareto member to have been evaluated, validates disposition/advisory consistency and computes a control-side binding digest. This binding digest does not replace the NDU owner’s evaluation digest; it proves the exact projection that `control.runtime` consumed.

Disposition invariants are:

| Disposition | Required advisory state |
|---|---|
| `InfeasibleExplicitAbstain` | Pareto set exactly `[abstain]`, advisory `abstain` |
| `UniqueParetoRecommendation` | one Pareto member, advisory equals it |
| `ScalarizedRecommendation` | advisory is present in the Pareto set |
| `ParetoSetRequiresSlowPath` | no advisory, non-empty Pareto set |
| `ScalarizationTieRequiresSlowPath` | no advisory, non-empty Pareto set |

The union of NDU evaluated and NDU rejected candidates must equal the exact feasible candidate set in `PreparedPlanInputV1`. An omitted candidate, an injected candidate or an advisory outside that set rejects finalization.

## 6. Plan finalization and search disclosure

`finalize_plan` recomputes the complete feasible-candidate-set digest from candidate identity, operation, plan, owner, final-payload and resource fields, verifies it against the sealed prepared envelope, and revalidates:

- snapshot digest, freshness and masks;
- prepared-plan digest and deny-all authority posture;
- objective, body generation, configuration and revocation frontier;
- NDU binding digest and deny-all posture;
- exact candidate-set coverage;
- NDU disposition/advisory consistency;
- prepared-plan deadline.

A selected plan is described only relative to the bounded supplied candidate set. The receipt never claims a global optimum. `SearchDisclosureV1` distinguishes:

- bounded candidate set with explicit abstain;
- unique Pareto result on that bounded set;
- scalarized result on that bounded set;
- unresolved Pareto frontier requiring a slow path.

`FeasiblePlanReceiptV1` binds both candidate-set digests, resource rejections, NDU policy/evaluation/binding digests, uncertainty, chosen candidate and plan digests, expiry, snapshot and revocation frontier. Its authority posture is deny-all.

## 7. Grant requests and final authority boundary

`request_execution_grants` accepts only a current snapshot, the exact sealed prepared input and the exact final plan receipt. Before reading any selected operation or payload, it recomputes the snapshot, candidate-set, prepared-plan and receipt digests, checks all readiness masks, policy bindings and expiry, and rejects any mutation. It recomputes both digests, verifies objective/body/configuration/frontier identity, checks expiry and locates the chosen candidate inside the feasible set.

Each `GrantRequestV1` binds:

- operation and candidate IDs;
- chosen plan digest;
- one final payload digest;
- objective and snapshot digests;
- current revocation-frontier digest;
- expiry.

The resulting `GrantRequestSetV1` is a deterministic request batch with a semantic digest and `AuthorityPosture::DENY_ALL`. A grant request is not an authority token. `kernel.authority` must independently check principal scope, current revocations, final payload, effect boundary, deadlines and any required human confirmation immediately before dispatch.

A candidate with no effect payload, including abstain, produces an empty request set. The planner never fabricates a no-op capability.

## 8. Decision journal, restart and non-resurrection

`PlannerJournalV1` is a bounded owner-local durability reference for snapshot, decision, selection and revocation records. It is not an activated production store.

Each entry contains sequence, kind, idempotency identity, payload digest, predecessor-entry digest and entry digest. The journal provides:

- canonical append order;
- at most 4096 records per bounded file;
- idempotent replay for equal identity and semantics;
- conflict for equal identity with different semantics;
- exact byte export and reopen;
- sequence, predecessor and entry-digest verification;
- truncation and unknown-kind rejection;
- selected-plan projection;
- revocation edges that prevent reselection and restart resurrection.

A selected plan must already have a decision record. A revoked decision cannot be reselected merely because an older process or backup contains the predecessor record. `append` and `reopen` now apply the same Decision -> Selection -> Revocation semantic transition checks; a valid hash chain with an impossible selection or revocation is rejected.

`PlannerJournalStoreV1` is the owner-local durable-store candidate. It wraps the bounded journal in a schema/version/digest envelope, writes through create-new temporary files, calls `sync_all`, atomically replaces the active file, syncs the directory on Unix and advances a separately synced committed frontier. A crash after replacing the active file but before advancing the frontier can restore only a backup matching the old committed frontier. Once a revocation frontier is committed, an older backup cannot cross that frontier and resurrect the selection. A raw `HCPJNL01` reference journal is migrated deterministically on first store open. Product composition still has to select the deployed state directory, retention/rotation policy and the owning writer callsite; this source implementation does not self-activate.

## 9. Failure and degradation semantics

Failures are classified as:

- invalid or empty digest;
- count or resource bound violation;
- duplicate owner, candidate or resource axis;
- mixed objective, body generation or configuration;
- future, stale, missing or unavailable owner state;
- expired snapshot or prepared plan;
- unknown required owner;
- missing or unknown resource axis;
- infeasible intrinsic abstain;
- NDU binding, candidate-set or disposition mismatch;
- prepared-plan or payload mismatch;
- journal integrity, truncation, identity conflict or revocation.

A failure before finalization leaves no plan receipt. A failure after durable decision publication but before acknowledgement is recovered by the original operation identity and equal digest. Unknown external effects remain indeterminate and are reconciled by the existing effect owner; the planner cannot infer success from queue admission or handler return.

Central outage never enters a qualified local reflex or emergency-stop loop. Local controllers continue only within previously qualified envelopes. The global planner may become unavailable without disabling an independent safety stop.

## 10. Capacity and performance profile

Pilot bounds are:

| Dimension | Ceiling |
|---|---:|
| owner summaries | 32 |
| plan candidates | 128 |
| required owners per candidate | 32 |
| final payloads per candidate | 64 |
| resource dimensions | 32 |
| journal records per bounded file | 4096 |

All loops and allocations are bounded by these dimensions. Stable maps and sorting provide deterministic output. Planning is not permitted in a local real-time safety loop and performs no fleet-wide synchronous RPC.

Target metrics include snapshot age, stale/missing owner counts, candidate and resource rejection counts, NDU disposition, Pareto size, uncertainty digest, preparation/finalization latency, journal reopen time and grant-request count. Latency targets become claims only when bound to a named host, compiler, fixture, build profile and exact source.

The dedicated `.github/workflows/hepta-control-runtime-closure.yml` records that identity for both the exact source head and a deterministic synthetic merge. Its source-head lane runs the release-mode `control_runtime_probe` at the declared pilot ceilings of 32 owners, 128 candidates, 32 required owners per candidate, 32 resource axes and 4096 NDU contributions. The artifact records source/tree identity, runner OS/architecture, CPU, Rust/Cargo versions, p50/p95/p99/max latency and Linux process high-water RSS when available. Those measurements are candidate evidence, not a cross-host universal SLO.

## 11. Verification cases

- `RCP-01`: a stale required owner cannot be treated as current or zero cost.
- `RCP-02`: safety/rollback/evidence floors survive overload and remove the over-budget candidate before NDU.
- `RCP-03`: changed body generation, configuration, snapshot or revocation frontier invalidates a prepared plan.
- `RCP-04`: central planning outage does not disable an independently qualified local fallback or stop.
- `RCP-05`: missing resource axes reject instead of becoming zero.
- `RCP-06`: the NDU evaluated/rejected union must equal the exact prepared candidate set.
- `RCP-07`: NDU binding or uncertainty tampering rejects finalization.
- `RCP-08`: grant requests remain deny-all and bind final payload digests.
- `RCP-09`: journal restart reproduces the selected pointer exactly.
- `RCP-10`: truncated or tampered journal bytes fail closed.
- `RCP-11`: a revoked plan cannot be reselected after reopen.
- `RCP-12`: no receipt claims an optimum outside the bounded candidate set.
- `RCP-13`: operation, payload, resource or required-owner mutation after finalization rejects before grant-request construction.
- `RCP-14`: grant-request construction revalidates snapshot masks and digest.
- `RCP-15`: the NDU evaluation policy and resource profile are frozen before evaluation and bound through the final receipt.
- `RCP-16`: the canonical resource-profile digest changes with endowment/floor semantics and rejects label/content drift.
- `RCP-17`: journal reopen rejects a semantically impossible selection/revocation even when its hash chain is internally consistent.
- `RCP-18`: the durable journal store recovers only the committed frontier and cannot resurrect a committed revocation from an older backup.
- `RCP-19`: `plan_global_v1` collects every required authenticated owner, executes the real NDU owner port, seals the receipt and emits only deny-all grant requests; missing owner ports and mixed clock bindings reject.
- `RCP-20`: `claim_execution_grant_v1` requires an independently signed `kernel.authority` final-use grant binding the whole request set, operation scope and exact final payload; the non-cloneable token is revalidated immediately before the effect closure and its nonce is single-use.

Native mappings and tests are recorded in `docs/modules/control.runtime/IMPLEMENTATION_MAP.json`.

## 12. Implementation sequence and completion state

The source sequence is snapshot types and validation, canonical resource-profile binding, resource-floor preparation, authenticated owner-port composition, NDU owner-port evaluation, plan finalization, grant-request construction, independent kernel-authority claim bridging, semantic journal replay, fsync/frontier durability, named-host measurement, semantic conformance and exact-head plus deterministic-merge CI.

Repository source completion requires every mapped native test, package check, strict lint, clean worktree, exact-head workflow and synthetic merge check to pass. The narrow Agentd cognitive-context caller is a named read-only product composition and now routes through the same `plan_global_v1` orchestrator. The general multi-owner global planner, durable store and independent authority bridge are source-implemented but still require selected concrete producer/effect adapters and a production writer callsite. Independent qualification, operator acceptance, activation and release remain separate governed states and cannot be advanced by this document.

## Appendix A. Contract mapping

Produced owner-local types:

- `GlobalStateSnapshotV1`
- `PreparedPlanInputV1`
- `NduPlanEvaluationV1`
- `FeasiblePlanReceiptV1`
- `GrantRequestSetV1`
- `PlannerJournalEntryV1`

Canonical domain reads remain:

- `DomainRead::global_state_snapshotV1`
- `DomainRead::optimization_decisionV1`

Consumed canonical readiness protocols include:

- `ObjectiveConstraintSetV1`
- `UtilityContributionV1`
- `NduIterationReceiptV1`
- `NduConvergenceCertificateV1`
- `EmergencyStopReceiptV1`
- `SensorCalibrationManifestV1`

Registration of an owner-local Rust type does not by itself admit a new external wire protocol. Production protocol admission and consumer compilation remain explicit integration work.

## Native measured-context composition

`evaluate_prepared_plan_with_ndu` now computes the owner NDU evaluation before
sealing a plan. Its frozen policy digest includes the complete utility profile,
aggregation/tolerance policy and optional scalarization profile; callers cannot
substitute a chosen candidate or change directions after preparation.

`plan_observed_context` supplies the bounded product adapter for a completed
canonical cognitive read. The trusted host supplies its actual owner/generation,
snapshot/read digests, verified record count and exact serialized context bytes.
The objective is narrowly defined: deliver verified records within the requested
context-byte budget. It uses at most four records and 24 KiB, evaluates read and
abstain candidates, and returns the real NDU evaluation and sealed plan. Empty
records, ties and insufficient budget do not authorize context delivery. This is
an observed digital task, not an estimate of model quality or memory capacity.

The single-observation owner summary has its own initial revision and an explicit
request-local generation fence. It does not impersonate a database revision or
global revocation frontier. Existing host authorization and generation checks
remain required before and after the read. Context bytes exclude the planning
metadata to avoid a self-referential digest; the host separately bounds the final
response envelope. Neither helper grants effects or proves long-term improvement.

## Final closure composition

`plan_global_v1` is the common global orchestration path. It receives typed authenticated owner ports and a separately owned NDU port, requires the snapshot collection time and planning time to share one monotonic-domain value, samples only the declared required owners, verifies returned owner identity, calls the existing snapshot/resource/NDU/finalization code and returns the sealed receipt plus `GrantRequestSetV1`. The current Agentd context product caller reaches this path through `plan_observed_context`; its process-owned `Instant` origin replaces Unix wall-clock time for the planning lifetime.

The physical authority boundary remains independent. `claim_execution_grant_v1` maps one immutable grant request to the existing `kernel.authority` `FinalUseAuthority`: the signed binding covers the complete request-set digest, a domain-separated operation/candidate/plan/objective/snapshot/revocation/expiry scope digest and the exact final-payload digest. Control runtime cannot construct `VerifiedUseToken`; only the authority owner can. The token is non-cloneable/non-serializable and `with_verified_use` revalidates current revocation/expiry immediately before the caller's effect closure.

No source or CI artifact in this section grants effect, deployment, acceptance, promotion or release authority.
