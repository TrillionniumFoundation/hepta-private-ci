# runtime.fleet: implementation and execution dossier

Parent: `docs/modules/runtime.fleet/TECHNICAL.md`  
Current state: `docs/modules/runtime.fleet/CURRENT_STATE.json`  
Lane: `LANE-B-RUNTIME`  
Owner/deputy: `fleet-runtime` / `runtime-control`

## 1. Scope and claim boundary

This dossier records repository-controlled source implementation and qualification requirements for the `runtime.fleet` candidate. It does not grant deployment, independent acceptance, promotion or release. The existing `hepta-supervisord` process remains the single Fleet owner; no parallel writer is introduced.

## 2. Public owner operations

| Operation | Native entry point | Durable/effect boundary |
|---|---|---|
| register Agent | `FleetRegistry::register` | Fleet-wide lock, workspace reservation, staging rename, directory sync |
| transition lifecycle | `FleetRegistry::compare_and_transition` | Fleet-wide lock, immutable lifecycle generation, directory sync |
| observe capacity | `DurableFleetOwner::refresh_capacity` | stable operation ID, selected-host observer, immutable Fleet generation |
| calculate local shares | `calculate_local_allocation_v1` | authority-free deterministic calculation only |
| map resources | `map_logical_to_physical_v1` | versioned mapping policy and digest receipt |
| issue allocation | `DurableFleetOwner::issue_with_authority` | final authority revalidation and atomic durable publication |
| renew/revoke | `DurableFleetOwner::renew_or_revoke` | lease-generation/epoch/digest fences and exact capacity release |
| collect expiry | `reconcile_expired_idempotent` | operation-ID-first owner-time observation |
| persist revocation | `DurableFleetOwner::persist_revocation_snapshot` | signed update/ack snapshot in immutable generation |
| verify final use | `verify_final_use_with_revocation` | current grant plus fresh converged revocation cut |
| maintain product state | `run_supervisord_product` | existing supervisor owner |
| admit physical process | Unix `ProcessDriver` wrapper | immediate pre-spawn/pre-adopt Fleet admission |

## 3. State and transaction design

The durable owner stores logical datasets for hosts, observations, active grants, terminal history, expiry index, resource totals, revocation update/acknowledgements, workspace-reservation digest and operation receipts. A successful issue stores its authority witness in the same immutable generation as the grant.

All mutations serialize through `owner.lock`. A candidate is validated in memory, published as a checksummed immutable generation and followed by an independently checksummed `latest-frontier-v1.json`. State and frontier directory synchronization complete before success is returned.

The latest frontier is monotonic. A retained chain may advance it only when descent from the pinned state digest is proved. Tail deletion, missing nonzero frontier, same-generation drift or unverifiable gaps fail closed.

## 4. Allocation, capacity and resource semantics

The deterministic local allocator reserves minimums first and distributes remaining capacity by stable discrete weighted max-min fairness. It is explicitly non-authorizing.

`ResourceVectorV1` defines the canonical units and axis mask. Compatibility logical types convert immediately to canonical vectors. Physical mapping uses a reviewed `ResourceMappingPolicyV1`; the mapping receipt binds policy, logical and physical digests.

Selected-host capacity comes from operating-system observation. A same-generation shrink that cannot contain live grants is rejected atomically. Host-generation changes fence predecessor grants. Stale observations deny issue and renew.

## 5. Active/history split and bounded compaction

The previous lifetime exhaustion is closed by separating live grants from terminal history. `MAX_ACTIVE_GRANTS` limits simultaneous active grants. Revocation, expiry and host-generation replacement remove active entries, release capacity once and append a terminal record. Expiry lookup is indexed.

Terminal history and operation receipts have explicit bounded windows. Compacted entries feed chained digests. Indefinite searchable replay detection remains an external audit-retention obligation and is not claimed by the in-process store.

## 6. Authority and revocation

Allocation issue computes the binding from the grant rather than accepting a caller-provided scope. The generic authority lease is revalidated at the final owner mutation boundary. The returned witness is persisted for audit but does not authorize another operation.

Revocation persistence contains signed evidence only. Feed and node trust roots are supplied independently through `FleetStartTrustProfileV1`. Final use requires a fresh, converged cut and local node `Ready` state. Catch-up, quarantine and stale feed deny use.

## 7. Named product composition

`hepta-supervisord`:

- opens the existing registry and durable Fleet owner;
- refreshes capacity and pressure every 20 seconds with a 60-second observation TTL;
- reconciles expired grants;
- treats maintenance failure as product failure;
- requires an immutable Fleet start trust profile;
- scopes that admission profile over the daemon’s Unix process driver;
- checks Fleet admission before Agent spawn/adopt and Matrix spawn/adopt, including restart and recovery paths.

The control request cannot choose an arbitrary allocation. Admission derives exactly one active grant for the Agent principal and revalidates all retained grant and revocation fences immediately before the physical process effect.

## 8. Current native implementation

### Source-complete repository surfaces

- durable Agent registry and lifecycle publication;
- cross-process workspace registration serialization;
- owner clock;
- canonical resources and mapping receipts;
- deterministic local allocator;
- active/history/expiry/compaction lease ledger;
- durable Fleet owner and atomic authority-bound issue;
- signed revocation snapshot persistence and restore;
- monotonic latest-generation frontier;
- Linux capacity/pressure observer;
- named supervisor maintenance path;
- physical process start/adopt admission;
- read-only operational status and runbook;
- focused exact-source/synthetic-merge and protected target-host workflows.

### Repository-controlled tests

- sequential grant churn beyond 16,384 lifetime operations;
- simultaneous active-limit rejection;
- exact expiry, revocation and host-generation capacity release;
- stale observation and stale lease rejection;
- mutation completeness and digest changes;
- concurrent parent/child workspace registration;
- staging and post-publication crash boundaries;
- durable reopen and operation-ID-first retry;
- revocation snapshot restore and deny states;
- final-use grant/host/lease checks;
- latest-frontier crash-window repair, tail deletion rejection and missing-frontier rejection;
- procfs parsing, pressure limit and capacity shrink;
- product binary compilation and strict clippy.

### Remaining evidence gates

- final candidate exact-source and synthetic-merge green receipts;
- protected selected-host qualification bound to the exact candidate SHA;
- authenticated multi-node revocation fanout and partition qualification;
- deployed external audit retention beyond bounded windows;
- independent operator acceptance, activation, promotion and release.

## 9. Failure semantics

- pre-publication validation or I/O failure: rejected, no committed mutation;
- state/frontier publication may be visible but sync failed: `IndeterminateCommit`;
- same operation ID, same digest: idempotent receipt while retained;
- same operation ID, different digest: conflict and quarantine;
- stale host, stale lease, revoked grant, expired revocation feed or non-ready node: hard denial;
- missing or ambiguous Agent grant at physical effect boundary: hard denial;
- corrupt generation/frontier/reservation/resource-total invariant: owner open fails closed.

## 10. Capacity and performance profile

Source-enforced ceilings include 256 hosts/nodes where specified, 4,096 local candidates, 16,384 simultaneous active grants, 32,768 retained terminal records, 16,384 retained operation receipts and eight retained immutable state generations. These bounds prevent unbounded memory/history growth but are not selected-host latency or durability measurements.

## 11. Security controls

- no trust roots persisted in Fleet state;
- regular non-symlink trust profile and state files;
- owner-only lock/state permissions where supported;
- exact authority scope calculated from mutation semantics;
- current revocation cut required at final use;
- no caller-controlled current time;
- no request-supplied physical capacity;
- no second writer;
- no automatic replay of ambiguous publication;
- no process start/adoption bypass on restart.

## 12. Observability

The read-only status path reports active/expired/revoked grant counts, reservations and observations by host/axis, stale hosts, mutation outcomes, revocation lag, registry conflicts, indeterminate commits, staging debris and compaction backlog. Durable generations and operation receipts are the authoritative facts; process-local counters are diagnostic.

## 13. Rollback

Source rollback may restore a compatible binary, but durable Fleet state may never be rolled back by deleting the latest generation or lowering the frontier. A predecessor binary that does not understand the current schema/frontier must not become the owner. Restore requires an independently authenticated backup and approved migration that preserves generation/digest lineage.

## 14. Qualification commands

The focused workflow runs:

```text
cargo fmt --all -- --check
cargo test -p codex-hepta-fleet --all-targets
cargo test -p codex-hepta-supervisor --lib
cargo check -p codex-hepta-supervisor --bin hepta-supervisord
cargo clippy -p codex-hepta-fleet --all-targets --all-features -- -D warnings
cargo clippy -p codex-hepta-supervisor --all-targets --all-features -- -D warnings
```

It executes against the exact source and a deterministic synthetic merge. The target-host workflow is separate and externally gated.

## 15. Completion statement

The candidate closes repository-controlled source implementation and named product source composition. Product execution proof, selected-host/multi-node qualification, external long-term audit, independent acceptance and release remain false until their distinct evidence and authority gates complete.
