# runtime.fleet: implementation design

Parent: `docs/modules/runtime.fleet/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `codex-rs/hepta-fleet`.
Packages: `FLEET-1-ALLOCATION-CONTRACT`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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
