# runtime.fleet: implementation design

Parent: `docs/modules/runtime.fleet/TECHNICAL.md`. Lane: `LANE-B-RUNTIME`.
Status: durable agent registry, canonical resource model, deterministic host placement, fsynced allocation generations and supervisor-owned runtime grant consumption are implemented in source; independent authority/target acceptance remains listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

Pilot <= 256 enrolled hosts and <= 4096 requests per planning batch. V1 has four canonical axes: concurrent turns (count), memory (MiB), tool processes (count) and turn-queue slots (count). Concurrent-turn and memory endowment are observed locally; tool-process and queue ceilings are explicit policy values. Report total live allocation <= the current observed/policy endowment for every axis.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- FLEET-01: aggregate requests above capacity conserve resources and preserve essential floors.
- FLEET-02: host partition/expired lease never yields two owners of the same hard allocation.
- FLEET-03: permuting request order produces an identical plan digest.
- FLEET-04: a portable evolution package cannot enroll peers or inherit credentials.

Repository regressions bind these designs to `allocation_tests.rs`/`placement.rs` (FLEET-01/FLEET-03), `lease_ledger_tests.rs` plus `runtime_allocator.rs` restart/expiry tests (FLEET-02), and the runtime allocator's observer-identity rejection (FLEET-04). Test source is still not an execution receipt; exact-head CI supplies the candidate result.

## 7. Integration, rollback and capability ceiling

NDU consumes measured resource summaries; it cannot redefine a hard capacity to make an allocation feasible. Rollback drains allocations with current fences and does not restore expired leases. Federation remains scoped to independently enrolled targets.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `FleetRegistry` in [codex-rs/hepta-fleet/src/registry.rs](../../../codex-rs/hepta-fleet/src/registry.rs); `admit_host` / `renew_or_revoke` in [codex-rs/hepta-fleet/src/lease_ledger.rs](../../../codex-rs/hepta-fleet/src/lease_ledger.rs); `calculate_fleet_placement_v1` in [codex-rs/hepta-fleet/src/placement.rs](../../../codex-rs/hepta-fleet/src/placement.rs); and supervisor-composed `reserve_agent_start` / `maintain` in [codex-rs/hepta-fleet/src/runtime_allocator.rs](../../../codex-rs/hepta-fleet/src/runtime_allocator.rs).
- **Resource semantics:** [codex-rs/hepta-fleet/src/resource.rs](../../../codex-rs/hepta-fleet/src/resource.rs) is the single V1 vector used by the calculator, placement, lease ledger, durable grant and Agent `ResourceBudget` conversion. The retired CPU-millis/memory-bytes/accelerator shadow vocabulary is no longer used by the fleet lease owner.
- **State and recovery:** [codex-rs/hepta-fleet/src/allocation_store.rs](../../../codex-rs/hepta-fleet/src/allocation_store.rs) persists immutable allocation generations under the existing fleet state root. Each generation binds predecessor revision, writer epoch, ledger and content digest; publish is fsync-before-link and non-overwriting. A new supervisor epoch fences predecessor-epoch live leases before replacement grants.
- **Capacity and placement:** [codex-rs/hepta-fleet/src/capacity.rs](../../../codex-rs/hepta-fleet/src/capacity.rs) supplies a bounded local OS observer; [codex-rs/hepta-fleet/src/placement.rs](../../../codex-rs/hepta-fleet/src/placement.rs) selects eligible hosts before invoking weighted max-min allocation. Observer identity is exact: an observer cannot substitute a newly discovered peer.
- **Product caller and reconciliation:** [codex-rs/hepta-supervisor/src/daemon.rs](../../../codex-rs/hepta-supervisor/src/daemon.rs) is the non-test caller. Normal `Start` commits the exact resource grant before spawn. The supervisor tick supplies the actual active-principal set; fleet renewal/revocation follows that holder observation and a maintenance failure fails closed for affected runtimes.
- **Produced read:** [codex-rs/hepta-fleet/src/grant_contract.rs](../../../codex-rs/hepta-fleet/src/grant_contract.rs) projects active current-epoch grants as `FleetAllocationGrantReadV1` bound to the fsynced allocation state revision and digest.
- **Source tests:** [codex-rs/hepta-fleet/src/allocation_tests.rs](../../../codex-rs/hepta-fleet/src/allocation_tests.rs), [codex-rs/hepta-fleet/src/lease_ledger_tests.rs](../../../codex-rs/hepta-fleet/src/lease_ledger_tests.rs), [codex-rs/hepta-fleet/src/allocation_store.rs](../../../codex-rs/hepta-fleet/src/allocation_store.rs), [codex-rs/hepta-fleet/src/placement.rs](../../../codex-rs/hepta-fleet/src/placement.rs), and [codex-rs/hepta-fleet/src/runtime_allocator.rs](../../../codex-rs/hepta-fleet/src/runtime_allocator.rs). These are source identities; exact-head CI is the execution receipt.
- **Implementation and operating references:** [docs/modules/runtime.fleet/IMPLEMENTATION_MAP.json](../../../docs/modules/runtime.fleet/IMPLEMENTATION_MAP.json), [docs/readiness/LANE_B_RUNTIME_COMPOSITION.md](../../../docs/readiness/LANE_B_RUNTIME_COMPOSITION.md).
- **Remaining external boundary:** the current supervisor control fence is bound into the exact durable grant but is not relabeled as an independently issued `kernel.authority` witness. Independent authority acceptance and real target-host partition/expiry/hardware qualification remain externally governed evidence gates.
