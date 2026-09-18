# Control runtime execution specification

**Overlay:** `HEPTA-V8-PRECODING-READINESS` v8.2.0-readiness  
**Module:** `control.runtime`  
**Source target:** `codex-rs/hepta-control-plane`  
**Primary owner:** `runtime-control`  
**Deputy:** `security-authority`  
**Authority delta:** none

## 1. Scope and non-claims

`control.runtime` constructs bounded coherent snapshots, preserves essential resource floors, consumes the independently owned NDU implementation, seals bounded-set decisions and emits immutable execution-grant requests. It does not evaluate utility on behalf of `utility.ndu`, authenticate producers on behalf of their owners, issue capabilities on behalf of `kernel.authority`, or execute effects.

The production-facing source path now additionally provides canonical resource-profile binding, authenticated-owner admission seams, strict journal semantic replay and an end-to-end global composition function. These source capabilities do not establish a production writer, named global product caller, independently accepted deployment, operator acceptance, activation, promotion or release. Planner and grant-request outputs remain `AuthorityPosture::DENY_ALL`.

The bounded Agentd cognitive-context path is a real read-only caller. It is deliberately classified separately from a promotion-eligible global product caller.

## 2. End-to-end control flow

The hardened global source flow is:

```text
owner-produced summary + owner proof
  -> caller-owned cryptographic verifier
  -> authenticate_owner_summary_v1
  -> AuthenticatedOwnerSummaryV1[]

AuthenticatedOwnerSummaryV1[] + SnapshotRequestV1
  -> collect_snapshot
  -> GlobalStateSnapshotV1

ResourceReservationV1[]
  -> canonical_resource_profile_digest
  -> resource_profile_digest

GlobalStateSnapshotV1 + PlanningRequestV1
  -> prepare_plan_hardened
  -> PreparedPlanInputV1

PreparedPlanInputV1 + NduPlanningInputV1
  -> utility.ndu::evaluate_candidates_with_policy
  -> evaluate_prepared_plan_with_ndu
  -> EvaluatedPlanV1 / FeasiblePlanReceiptV1

current snapshot + prepared input + receipt
  -> request_execution_grants
  -> GrantRequestSetV1 (DENY_ALL)

GrantRequestSetV1
  -> handoff_grant_requests_v1
  -> independent kernel.authority adapter
  -> owner-specific authority result
```

`compose_global_plan_v1` sequences the middle planning stages over already-authenticated owners. It cannot manufacture `AuthenticatedOwnerSummaryV1`, cannot bypass NDU and cannot turn a grant request into a capability.

## 3. Coherent owner snapshot

Each `OwnerSummaryV1` binds owner identity and revision, objective digest, body generation, configuration digest, observation/expiry times in one declared planner clock domain, readiness, source-frontier digest and support digest.

`SnapshotRequestV1` binds the required owner set, objective, generation, configuration, revocation frontier, snapshot policy, collection time, maximum owner age and expiry. `collect_snapshot` canonicalizes owners, rejects duplicates/future observations/mixed identities and records missing, stale and unavailable masks. Any non-empty hard mask blocks planning.

A composed global caller admits owner observations as `AuthenticatedOwnerSummaryV1`. The compatibility seam `authenticate_owner_summary_v1` still accepts a caller-supplied verifier, while the concrete production-facing path uses `OwnerSummaryVerifierV1`: the host pins an Ed25519 public key for one producer identity, and `SignedOwnerSummaryV1` signs canonical bytes covering every `OwnerSummaryV1` field. Producer identity mismatch, weak/invalid trust or signature drift fail closed. Signing keys remain with the producer; Control contains only pinned verification trust.

## 4. Candidate preparation and canonical resource profile

A `PlanCandidateV1` binds candidate identity, operation identity, plan digest, required owners, final payload digests and explicit per-axis resource costs. Candidate count is bounded to 128, required owners to 32, final payloads to 64, and resource axes to 32.

For every `ResourceReservationV1`:

```text
available_for_plan(axis) = endowment(axis) - essential_floor(axis)
```

Endowment and floor must be non-negative and floor cannot exceed endowment. Every candidate reports every registered resource axis; missing and unknown axes reject.

The production-facing path computes:

```text
resource_profile_digest = H(
  "hepta.control.resource-profile.v1",
  sorted(axis, endowment.raw, essential_floor.raw)
)
```

`prepare_plan_hardened` recomputes this digest from the exact reservations and rejects any mismatch before filtering candidates. Therefore two different endowment/floor profiles cannot reuse an opaque profile identity even when they happen to produce the same feasible candidate set.

Low-level `prepare_plan` remains available for compatibility and fixtures. Composed callers use `prepare_plan_hardened`.

## 5. Typed NDU owner execution

`evaluate_prepared_plan_with_ndu` executes the actual `utility.ndu` kernel. The frozen policy digest covers utility profile, NDU evaluation policy and optional scalarization. Contributions must cover every feasible candidate and every required observed owner exactly enough for the NDU owner contract; omitted candidates and foreign owners reject.

Control binds the resulting NDU evaluation into `NduPlanEvaluationV1`, validates exact evaluated/rejected candidate coverage and disposition consistency, then seals `FeasiblePlanReceiptV1`. Control does not recompute the NDU choice and does not accept a caller-supplied selected candidate as a substitute for NDU execution.

## 6. Plan finalization and search disclosure

`finalize_plan` revalidates snapshot integrity/freshness/masks, prepared-plan digest and deny-all posture, candidate-set digest, objective/body/configuration/revocation identity, NDU binding, exact candidate coverage, disposition and deadline.

A result is always scoped to the supplied bounded candidate set. `SearchDisclosureV1` distinguishes bounded abstain, unique Pareto result, scalarized result and unresolved Pareto frontier. No receipt claims unconstrained global optimality.

## 7. Grant requests and final authority boundary

`request_execution_grants` accepts only a current snapshot, the exact prepared input and the exact final receipt. It recomputes sealed digests and revalidates readiness, identity and expiry before reading the selected operation/payload.

Each `GrantRequestV1` binds operation, candidate, plan, final payload, objective, snapshot, current revocation frontier and expiry. The enclosing `GrantRequestSetV1` remains `DENY_ALL`.

`handoff_grant_requests_v1` remains the generic independent-owner seam. The concrete adapter `with_authorized_grant_request_v1` maps one immutable `GrantRequestV1` to `codex_hepta_contracts::FinalUseBinding`, including a digest over operation, candidate, plan, final payload, objective, snapshot, revocation frontier and planner expiry. It then consumes an independently signed `SignedFinalUseGrant` through the existing `FinalUseAuthority::claim` and `FinalUseAuthority::with_verified_use` path. That authority owner performs Ed25519 verification, durable single-use nonce claiming and final revocation/time revalidation. Control never holds the signing key and never constructs `VerifiedUseToken` directly.

## 8. Decision journal, strict restart replay and non-resurrection

`PlannerJournalV1` is a bounded owner-local reference format. It verifies header, record count, sequence, predecessor digest, entry digest, non-empty identities and duplicate serialized identities.

`StrictPlannerJournalV1::reopen` adds semantic replay after byte/hash verification:

- snapshot identity must equal its snapshot payload digest;
- decision identity must equal its decision receipt digest;
- selection requires a preceding decision for the same payload;
- revocation requires a preceding decision;
- a decision already revoked cannot be selected later.

This detects hash-valid but semantically impossible histories created through the generic reference `append` API.

`PlannerJournalStoreV1` is the owner-local durable Unix profile. It requires a private owner directory and process lock, uses no-follow/private file opens, validates strict semantic replay before commit, writes and fsyncs a temporary generation, atomically renames it, then fsyncs the directory. Exactly one verified predecessor is retained for explicit rollback. `planner-journal.raw.v1` is admitted only through strict replay and migrated deterministically. Missing/corrupt state never becomes an empty journal. Non-Unix platforms reject this durability profile rather than claiming equivalent semantics. A named production host still has to compose the store and qualify its actual filesystem/power-loss behavior.

## 9. Clock-domain requirements

Planner freshness uses one monotonic domain per process generation or host generation. Wall-clock Unix time must not be substituted for planner expiry merely because both are represented as integers.

The real Agentd context caller now derives planner microseconds from a process-local `std::time::Instant` origin. Unix `SystemTime` remains confined to memory-store interfaces whose contracts explicitly require Unix seconds. Restart creates a new planner clock origin together with the process generation fence; timestamps are not compared across generations.

## 10. Failure and degradation semantics

Failures include invalid/empty digest, capacity violation, duplicate owner/candidate/resource axis, mixed objective/body/configuration, future/stale/missing/unavailable owner state, expired snapshot/plan, unknown owner, invalid/missing/unknown resource axis, canonical resource-profile mismatch, infeasible abstain, NDU candidate/binding/disposition mismatch, prepared/payload drift, rejected owner authentication and journal byte/semantic corruption.

A failure before finalization produces no final receipt. A grant request is never evidence of execution success. Unknown external effects remain owned by the effect adapter and reconciler.

Central planner outage never disables an independently qualified local reflex, watchdog or emergency stop.

## 11. Capacity and performance profile

| Dimension | Ceiling |
|---|---:|
| owner summaries | 32 |
| plan candidates | 128 |
| required owners per candidate | 32 |
| final payloads per candidate | 64 |
| resource dimensions | 32 |
| journal records per bounded file | 4096 |

All loops/sorts/allocations are bounded by these dimensions. Global planning is excluded from local real-time safety loops and performs no fleet-wide synchronous hot-path RPC.

Named-host latency, saturation, restart/reopen timing and fault-injection values become claims only after exact-source measurements on a named host/build profile.

## 12. Verification cases

- `RCP-01`: stale or missing required owner cannot be treated as current or zero cost.
- `RCP-02`: essential floors survive overload and remove an over-budget candidate before NDU.
- `RCP-03`: changed body/configuration/snapshot/revocation frontier invalidates a prepared plan.
- `RCP-04`: central planning outage does not disable independent local fallback/stop.
- `RCP-05`: missing resource axes reject instead of becoming zero.
- `RCP-06`: NDU evaluated/rejected union equals the exact prepared candidate set.
- `RCP-07`: NDU binding or uncertainty tampering rejects finalization.
- `RCP-08`: grant requests remain deny-all and bind final payload digests.
- `RCP-09`: valid journal restart reproduces the selected pointer.
- `RCP-10`: truncated/tampered journal bytes fail closed.
- `RCP-11`: revoked plan cannot be reselected after reopen.
- `RCP-12`: no receipt claims an optimum outside the bounded candidate set.
- `RCP-13`: operation, payload, resource or required-owner mutation after finalization rejects before grant-request construction.
- `RCP-14`: grant-request construction revalidates snapshot masks and digest.
- `RCP-15`: NDU evaluation policy and resource profile are frozen before evaluation and bound through the final receipt.
- `RCP-16`: canonical resource digest is order independent but changes with endowment/floor semantics.
- `RCP-17`: hardened preparation rejects opaque/stale resource-profile binding.
- `RCP-18`: strict reopen rejects a hash-valid selection before its decision.
- `RCP-19`: strict reopen rejects a hash-valid selection after revocation.
- `RCP-20`: an owner summary cannot enter global composition when the authenticator rejects it.
- `RCP-21`: authenticated owner + real NDU + sealed decision + grant-request handoff compose while Control remains deny-all.
- `RCP-22`: bounded Agentd context planning uses a monotonic planner clock and canonical serialized-byte resource profile.
- `RCP-23`: pinned Ed25519 producer trust admits only the exact signed owner summary.
- `RCP-24`: planner grant authority requires an independently signed final-use grant and consumes its nonce exactly once.
- `RCP-25`: payload or scope drift changes the final-use binding and cannot reuse prior authority.
- `RCP-26`: durable journal commit reopens under an exclusive process lock.
- `RCP-27`: predecessor restore is explicit and strictly replayed.
- `RCP-28`: hash-valid semantic forgery is rejected before durable commit.
- `RCP-29`: legacy raw journal bytes migrate only after strict semantic replay.

Native mappings and tests are recorded in `docs/modules/control.runtime/IMPLEMENTATION_MAP.json`.

## 13. Implementation sequence and completion state

Repository source closure now consists of coherent snapshot validation, canonical resource-profile binding, actual NDU execution, sealed finalization, grant-request construction, pinned-key Ed25519 owner verification, a concrete adapter to the independently owned final-use authority, strict journal semantic replay, a locked/fsync/atomic owner-local journal store and bounded Agentd product composition.

Repository source completion for the current closure head still requires exact-head and synthetic-merge CI to pass. Promotion-eligible global product composition separately requires one named host to compose the implemented owner trust, planner store and final-use authority adapter, followed by named-host load/latency/restart/fault-injection qualification and independent acceptance.

## Appendix A. Contract mapping

Produced owner-local types include `GlobalStateSnapshotV1`, `PreparedPlanInputV1`, `NduPlanEvaluationV1`, `FeasiblePlanReceiptV1`, `GrantRequestSetV1`, `PlannerJournalEntryV1`, `AuthenticatedOwnerSummaryV1`, `SignedOwnerSummaryV1`, `GrantAuthorityContextV1` and `PlannerJournalStoreV1`.

Canonical domain reads remain `DomainRead::global_state_snapshotV1` and `DomainRead::optimization_decisionV1`. Owner-local Rust types do not automatically create an external wire protocol; cross-process protocol admission remains explicit.

## Native measured-context composition

`plan_observed_context` is the bounded real caller used by Agentd after a canonical cognitive read. The host supplies actual source/read digests, owner/generation, verified record count and exact serialized context bytes. The objective is narrowly “deliver verified records within the response-byte budget”; read-context is compared with abstain using actual NDU execution.

The byte endowment is now hashed through `canonical_resource_profile_digest` and admitted by `prepare_plan_hardened`; it is no longer represented by an unrelated opaque digest. Planner freshness uses the Agentd process-local monotonic clock. Empty context, ties and budget infeasibility do not authorize delivery.

This measured-context caller proves bounded read-only composition only. It does not prove global adaptive topology/resource control, model quality, memory capacity, physical authority or production release.
