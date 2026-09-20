# runtime.fleet: implementation design

Parent: `docs/modules/runtime.fleet/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable agent registry, canonical resource model, durable allocation store, deterministic host placement, final-use-authorized grant commit, runtime consumption and holder reconciliation are implemented in source; target-host qualification and independent acceptance remain external. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Durable owner:** `FleetRegistry::allocation_store` opens `FleetAllocationStore` beneath the existing supervisor-owned Fleet state root. Generations publish create-only after file sync; stale writers reject; malformed published state fails closed; holder/revocation/lease state reopens across restart.
- **Canonical resources:** `FleetResourceVectorV1` is shared by allocator, lease ledger, Agent resource-budget conversion and runtime consumption. The V1 axes are concurrent turns, MiB memory, tool processes and turn-queue slots.
- **Placement and allocation:** `plan_placement_v1` accepts requests without a caller-selected host, filters fresh eligible hosts, reserves unresolved holder capacity, deterministically selects hosts and applies the existing weighted max-min allocator. Input permutation preserves the plan digest.
- **Authority and commit:** `capacity_observation_binding` / `admit_host_with_authority` and `placement_authority_binding` / `commit_placement_with_authority` reuse `FinalUseAuthority` so exact subject, request, scope and final payload are revalidated immediately before the durable effect.
- **Runtime consumer:** `admit_runtime_use_v1` validates active lease, local host, Agent principal and manifest resource budget. The real `hepta-supervisor` calls this boundary before start/restart/upgrade/rollback and before adopting a process after supervisor restart when `HEPTA_FLEET_HOST_ID` is configured.
- **Holder reconciliation:** `FleetConsumptionObservationV1` records current-fence holder state. Revoked/expired allocations keep reserving capacity until a matching release observation is durable; stale pre-renewal release evidence cannot free a renewed lease.
- **Capacity producer:** `observe_local_host_capacity_v1` measures logical processors and physical memory on Linux/macOS and combines them with explicit soft-axis policy. The observation still requires signed final-use authority before Fleet publication.
- **Verification mapping:** FLEET-01 is covered by allocator conservation/minimum tests; FLEET-02 by unresolved-holder and lease-fence reconciliation tests; FLEET-03 by permutation/digest tests; FLEET-04 by exact-payload capacity authority rejection. These are source tests; target-host partition/restart/expiry qualification remains a separate evidence gate.
- **Remaining external gates:** exact-candidate CI, real enrolled-host measurements, target partition/restart/expiry qualification, independent acceptance, activation and release.
