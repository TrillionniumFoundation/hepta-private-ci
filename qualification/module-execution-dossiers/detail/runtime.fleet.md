# runtime.fleet: implementation design

Parent: `docs/modules/runtime.fleet/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable FleetRegistry plus crash-recoverable allocation owner, deterministic placement, final-use-authorized grant commit and Supervisor runtime consumer implemented in source; deployment qualification and independent acceptance remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-fleet`.
Packages: `FLEET-1-ALLOCATION-CONTRACT`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`admit_host(enrollment, measured_capacity, epoch) -> HostRegistration`; `allocate(requests, capacity_snapshot, policy) -> AllocationPlan`; `renew_or_revoke(allocation_id, fence, observation) -> LeaseDisposition`. Enrollment is explicit; discovering a reachable peer does not authorize it. Output allocations are bounded grants issued through the canonical authority boundary, not direct writes to agent stores.

## 3. State records and transaction design

`fleet_allocation_grant` binds host/failure domain, principal, resource vector with units, essential floor, reserved capacity, lease expiry, generation and predecessor. Host capacities are observations with freshness and uncertainty. The allocation owner persists a coherent capacity/allocation generation; local hosts enforce grants and report consumption.

## 4. Deterministic algorithm and scheduling

Reserve essential safety/evidence/rollback floors first. Allocate remaining capacity with deterministic weighted max-min fairness over registered priorities and stable-ID tie breaks. The pilot forbids overcommit on hard memory/energy/physical limits. A stale or partitioned host receives no new lease; existing hosts stop or fall back when their lease expires. Reconciliation resolves actual resource holders before reallocating uncertain capacity.

## 5. Capacity and performance profile

Pilot <= 256 enrolled hosts, <= 4096 requests per planning batch, <= 32 resource axes; bounded remote reads and no synchronous fleet optimization on local control ticks. Report total allocation <= available endowment for every axis.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- FLEET-01: aggregate requests above capacity conserve resources and preserve essential floors.
- FLEET-02: host partition/expired lease never yields two owners of the same hard allocation.
- FLEET-03: permuting request order produces an identical plan digest.
- FLEET-04: a portable evolution package cannot enroll peers or inherit credentials.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

NDU consumes measured resource summaries; it cannot redefine a hard capacity to make an allocation feasible. Rollback drains allocations with current fences and does not restore expired leases. Federation remains scoped to independently enrolled targets.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `FleetAllocationStore::admit_host`, `prepare_allocation`, `commit_prepared`, `renew_verified`, `revoke` and `reconcile_consumption` in [codex-rs/hepta-fleet/src/allocation_store.rs](../../../codex-rs/hepta-fleet/src/allocation_store.rs); deterministic host selection is in [codex-rs/hepta-fleet/src/placement.rs](../../../codex-rs/hepta-fleet/src/placement.rs). The local calculator and compatibility lease reducer no longer define a second resource model.
- **State and recovery:** Fleet allocation state is stored beneath the existing FleetRegistry control root as immutable revisioned snapshots under one writer lock. A generation is fsynced and atomically renamed before it can become current. Incomplete `.next` files are recovery debris only. Expired, revoked or indeterminate grants keep hard capacity reserved until a trusted runtime observer reports `Released`; host generation rollover is blocked while unresolved grants remain.
- **Authority and observation:** `commit_prepared` and lease renewal consume the repository's non-forgeable `VerifiedUseToken` through `FinalUseAuthority::with_verified_use`. `LocalCapacityObserverV1` reads local kernel memory/parallelism under explicit policy ceilings; arbitrary request capacity is not hardware discovery. Registered Agent identity and manifest resource budget are rechecked during placement admission.
- **Named runtime consumer:** [codex-rs/hepta-supervisor/src/fleet_allocation.rs](../../../codex-rs/hepta-supervisor/src/fleet_allocation.rs) opens the same durable owner. The unique physical spawn seam revalidates any current allocation before every Start/restart/upgrade/rollback spawn, records `Holding` after spawn, records `Released` after an observed process exit, and recovery records `Holding` or `Indeterminate` instead of redispatching unknown capacity.
- **Source tests:** [codex-rs/hepta-fleet/src/allocation_store_tests.rs](../../../codex-rs/hepta-fleet/src/allocation_store_tests.rs) implements FLEET-01..04 source qualification; [codex-rs/hepta-supervisor/src/supervisor_tests.rs](../../../codex-rs/hepta-supervisor/src/supervisor_tests.rs) exercises the named runtime consumer. These remain exact-source test identities until CI receipts are terminal.
- **Remaining work:** authenticate and deploy remote/enrolled-host capacity adapters, run partition/restart/expiry fault injection on identified target hosts, collect capacity/latency measurements, and obtain independent operational acceptance. Those external gates do not reopen the durable repository owner or source-composed Supervisor caller.
