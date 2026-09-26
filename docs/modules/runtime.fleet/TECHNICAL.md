# runtime.fleet technical development guide

**Module:** `runtime.fleet`  
**Lane:** `LANE-B-RUNTIME`  
**Owner / deputy:** `fleet-runtime` / `runtime-control`  
**Named product owner:** `hepta-supervisord`  
**Canonical current state:** [`CURRENT_STATE.json`](CURRENT_STATE.json)  
**Detailed implementation:** [`DURABLE_OWNER.md`](DURABLE_OWNER.md)  
**Operations and recovery:** [`OPERATIONS.md`](OPERATIONS.md)

This document describes the current source implementation and its claim boundary. Source composition is not deployment qualification, independent operator acceptance, promotion or release. The standalone `hepta-fleet-leased` entry point remains intentionally inert; no second Fleet writer is authorized.

## 1. Mission, authority and non-goals

`runtime.fleet` allocates bounded resources through explicit, versioned, authority-bound leases and preserves one supervisor-owned source of truth. It may not:

- write Agent-owned stores;
- treat caller-supplied capacity as physical observation;
- infer authority from model output, queue acceptance or process existence;
- start a parallel Fleet service or writer;
- self-approve deployment, promotion or release;
- turn a local allocation calculation into a grant without authority, host freshness and a durable owner transaction.

The module owns the `fleet_allocation_grant` domain. `kernel.authority`, the Fleet registry, signed revocation evidence and selected-host operating-system observations remain independently governed inputs.

## 2. Source layout and product composition

Primary source roots:

- `codex-rs/hepta-fleet`
- `codex-rs/hepta-supervisor/src/fleet_runtime_product.rs`
- `codex-rs/hepta-supervisor/src/fleet_start_admission.rs`
- `codex-rs/hepta-supervisor/src/daemon.rs`
- `codex-rs/hepta-supervisor/src/unix.rs`

Key components:

| Concern | Owner entry point |
|---|---|
| Agent registry and lifecycle | `FleetRegistry` in `registry.rs` |
| Cross-process registry serialization | `RegistryMutationGuard` in `registry_coordination.rs` |
| Canonical resources | `ResourceVectorV1` in `resource.rs` |
| Logical-to-physical mapping | `map_logical_to_physical_v1` in `resource_mapping.rs` |
| Active lease state machine | `LeaseLedger` in `lease_ledger_v3.rs` / `lease_ledger_v2.rs` |
| Generic authority consumption | `FleetAuthorityPort` in `authority_port.rs` |
| Durable owner | `DurableFleetOwner` in `durable_owner.rs` |
| Snapshot implementation | `durable_owner_core.rs` |
| Capacity/pressure observation | `LinuxProcfsCapacityObserverV1` in `capacity_observer.rs` |
| Durable revocation evidence | `FleetRevocationSnapshotV1` in `revocation_snapshot.rs` |
| Final-use verification | `verify_final_use_with_revocation` in `final_use.rs` |
| Named maintenance caller | `run_supervisord_product` |
| Physical process admission | `FleetStartAdmission` plus the Unix `ProcessDriver` wrapper |

`hepta-supervisord` is the only named product process. It owns registry lifecycle, durable Fleet maintenance and the final process-effect boundary. Agent and Matrix spawn/adopt paths verify current Fleet admission immediately before the operating-system process effect, including automatic recovery paths.

## 3. Canonical resource contract

`ResourceVectorV1` is the registered in-process canonical model for six axes:

| Axis | Unit | Rounding |
|---|---|---|
| `cpu_millis` | milli-CPU | exact integer |
| `memory_bytes` | bytes | exact integer |
| `accelerator_millis` | milli-accelerator | exact integer |
| `concurrent_turns` | count | exact integer |
| `tool_processes` | count | exact integer |
| `turn_queue_slots` | count | exact integer |

Every vector binds schema version, supported-axis mask, axis IDs, units and amounts into its semantic digest. Addition, subtraction, MiB conversion and policy mapping use checked arithmetic. A requirement fits only when every required axis is supported and within capacity.

Legacy `ResourceBudget`, `LocalResourceVectorV1` and allocation shares are compatibility inputs. They are converted immediately to canonical vectors. A reviewed `ResourceMappingPolicyV1` maps logical counts to physical CPU, memory and accelerator amounts and emits a receipt binding the policy digest, logical digest and physical digest.

## 4. Deterministic local allocation

`calculate_local_allocation_v1` remains an authority-free calculation over caller-supplied candidates and capacities. It:

1. validates bounds, identifiers and duplicate identities;
2. reserves caller-supplied minimums;
3. distributes remaining capacity by deterministic discrete weighted max-min fairness;
4. uses stable request identity for ties;
5. returns a deny-all claim boundary.

Its result is not a Fleet view, scheduling decision, grant, start authority or effect receipt. Publication as a real allocation requires canonical resource mapping, a fresh trusted capacity observation, a live authority lease and a durable owner commit.

## 5. Registry, workspace isolation and lifecycle publication

The existing Fleet registry persists manifests, lifecycle generations and release state. Registration and lifecycle publication share a Fleet-wide mutation lock. Registration performs workspace-overlap validation, durable workspace reservation and final rename while holding that lock; concurrent parent/child registrations therefore cannot both commit.

Post-rename or post-hard-link synchronization failure is `IndeterminateCommit`, not a normal rejection. The caller must reopen and reconcile by Agent/generation identity. Startup cleans only physical `.staging-*` directories while holding the mutation lock. Symlinks, malformed histories, non-contiguous generations and workspace overlap fail closed.

## 6. Lease state, active/history separation and compaction

The lease ledger separates:

- `active_grants`: live, capacity-consuming leases;
- `history`: revoked, expired or generation-replaced terminal records;
- `expiry_index`: expiry-to-allocation lookup;
- `committed_by_host`: exact active resource totals.

`MAX_ACTIVE_GRANTS = 16,384` is a simultaneous-live ceiling, not a lifetime ceiling. Revocation, expiry and host-generation replacement remove active state, release capacity exactly once and append a terminal record. Terminal history is retained up to its bounded window and then folded into a chained compaction digest. More than 16,384 sequential issue/terminal cycles are covered by regression tests.

An identity still present in active state or retained history cannot be reused with different semantics. Operation receipts add a second, bounded idempotency key. Business requirements for indefinite replay detection require an external audit archive; bounded in-process digests do not provide searchable indefinite identity retention.

## 7. Owner time and host observations

All time-sensitive mutations use an injected `FleetClock`; callers do not provide “current time.” Host freshness, expiry, renewal and final-use checks read the owner clock.

On Linux the selected-host observer derives evidence from:

- `std::thread::available_parallelism()`;
- `/proc/meminfo` `MemAvailable`;
- `/proc/pressure/memory` `some avg10`.

The normal product profile refreshes every 20 seconds with a 60-second TTL. Above the configured pressure ceiling, no synthetic zero capacity is published: the previous observation expires naturally and new issue/renew operations fail closed. A same-generation shrink below live commitments is rejected atomically. A host-generation change fences and retires predecessor grants.

## 8. Durable owner and atomic mutation boundary

Authoritative Fleet state is under:

```text
FLEET_ROOT/state/fleet-allocation-v1/
```

Each immutable generation contains:

- `fleet_hosts`;
- `fleet_capacity_observations`;
- active grants, terminal history, expiry index and compaction digest;
- `fleet_resource_totals`;
- signed revocation update and acknowledgements;
- the workspace-reservation index digest;
- bounded operation receipts;
- issue-time authority witnesses;
- predecessor and content digests.

Every mutation holds `owner.lock`, reloads and validates the latest generation, applies one typed operation to an in-memory candidate, checks cross-dataset invariants, writes and `fsync`s a private temporary file, publishes the immutable generation, and `fsync`s the directory.

`issue_with_authority` performs, in one owner transaction:

1. retained operation-ID deduplication/conflict detection;
2. exact live generic-authority verification;
3. host identity, generation and freshness verification;
4. canonical resource validation and capacity locking;
5. grant insertion and exact resource-total update;
6. persistence of the non-authorizing authority witness and lease receipt;
7. immutable generation publication.

A queue result or authority check alone is not allocation success.

## 9. Non-rollback latest frontier

Immutable generations are supplemented by `latest-frontier-v1.json`, an independently checksummed and directory-synced non-rollback frontier. Opening the owner verifies that the latest retained state is the pinned generation or a verifiable descendant.

Automatic repair is limited to the crash window where a complete descendant generation is visible but the frontier update was not yet durable. The following fail closed:

- latest generation deletion;
- a nonzero state with a missing frontier;
- same-generation digest drift;
- a frontier ahead of retained state;
- a chain that cannot prove descent from the pinned frontier.

This prevents silent acceptance of an older valid snapshot after tail deletion. It does not replace host-level backup integrity, filesystem protection or independent audit retention.

## 10. Failure and recovery semantics

Failures before publication are ordinary rejections. If a generation link or frontier rename may already be visible but directory synchronization fails, the result is `IndeterminateCommit { operation_id, generation, detail }`.

Recovery procedure:

1. stop blind retry;
2. reopen the same Fleet state root;
3. validate the non-rollback frontier and retained chain;
4. query the exact operation ID;
5. accept only a receipt with the intended operation digest;
6. retry with the same operation ID and unchanged payload only when absent;
7. quarantine any same-ID/different-digest conflict.

Time-dependent command adapters resolve a retained operation ID before observing a new clock or capacity sample, preventing retry drift.

## 11. Revocation persistence and final-use admission

Fleet state persists signed revocation updates and exact signed node acknowledgements; trust roots are never stored in Fleet state. At startup the product requires an immutable bounded `FleetStartTrustProfileV1` containing the local node, distributor keys and closed node key sets.

Final-use verification requires:

- a durable revocation snapshot;
- a fresh authenticated current update;
- the local node to be enrolled and exactly acknowledged;
- `Ready` node state;
- one current active grant for the Agent principal;
- current allocation, lease and host-generation fences;
- current semantic digest;
- an unchanged revocation-snapshot digest across grant verification.

`CatchingUp`, `Quarantined` and `FeedStale` deny use. The Unix process driver invokes this verification immediately before Agent spawn, Agent adoption, Matrix spawn and Matrix adoption. Automatic restart, upgrade, rollback and recovery traverse the same driver boundary and cannot bypass admission.

The trust profile is source configuration, not a secret grant. It must be a regular non-symlink JSON file and is immutable for one daemon generation.

## 12. Product startup and CLI contract

The named product requires:

```sh
hepta-supervisord \
  --fleet-root /absolute/fleet-root \
  --fleet-start-trust-profile /absolute/fleet-start-trust-v1.json
```

Optional production-grant and H7 verifier key/id/epoch triplets remain all-or-nothing. The Fleet start trust profile is mandatory because starting a process without current revocation and allocation verification would be an authority bypass.

Host identity may be derived from `/etc/machine-id` and boot generation from `/proc/sys/kernel/random/boot_id`, or supplied only as a complete immutable triple:

```text
HEPTA_FLEET_HOST_ID
HEPTA_FLEET_FAILURE_DOMAIN_ID
HEPTA_FLEET_HOST_GENERATION
```

## 13. Observability and operator interface

`hepta-fleet-status` is read-only and requires existing state. It exposes:

- active, expired-uncollected and revoked-uncompacted grant counts;
- reserved and observed capacity by host/axis;
- stale hosts;
- issue/renew/revoke result counters;
- revocation lag;
- registry conflicts;
- indeterminate commits;
- staging debris;
- compaction backlog.

Thresholds, operator actions, recovery commands and forbidden operations are normative in `OPERATIONS.md`. Process-local counters are diagnostic; durable receipts and state generations are authoritative.

## 14. Verification and qualification

Repository-controlled qualification includes:

- `cargo fmt --all -- --check`;
- all `codex-hepta-fleet` targets;
- supervisor library tests;
- `hepta-supervisord` binary compilation;
- strict clippy for Fleet and supervisor;
- exact-source and deterministic synthetic-merge receipts;
- worktree cleanliness and command records.

Regression coverage includes grant churn beyond 16,384 lifetime operations, simultaneous active-limit rejection, exact expiry, capacity release, generation fencing, concurrent overlapping registration, post-publication crash boundaries, durable reopen, revocation restore, final-use fences and non-rollback frontier recovery/tamper cases.

A protected self-hosted workflow targets `[self-hosted, linux, x64, hepta-fleet-target]`. It must be bound to the final candidate SHA and an approved host profile. GitHub-hosted source tests cannot establish physical host behavior.

## 15. Capacity and performance bounds

Current source ceilings include:

- up to 256 enrolled hosts/revocation nodes where specified;
- up to 4,096 local allocation candidates;
- up to 16,384 simultaneous active grants;
- up to 32,768 retained terminal grant records;
- up to 16,384 retained operation receipts;
- eight retained immutable state generations plus the non-rollback frontier.

These are enforced source bounds, not selected-host performance claims. Sustained latency, filesystem durability, pressure behavior and multi-node partition recovery require target qualification.

## 16. Compatibility, migration and retirement

The public `DurableFleetOwner` wraps the established snapshot implementation and adds the non-rollback frontier without introducing another writer. The frontier is created with generation zero. A missing frontier beside a nonzero generation is rejected; operators must not manually synthesize it.

Compatibility adapters are temporary and may not widen authority. Retirement requires all named callers migrated, no old-path use, equivalent failure semantics, a rehearsed rollback and independent acceptance. Historical evidence remains interpretable after retirement.

## 17. Completion and claim boundary

Repository-controlled source boundary closure requires:

- durable grants and resource totals;
- active/history/expiry/compaction;
- serialized registry mutations;
- owner clock;
- canonical resources and mapping receipts;
- authority-bound atomic issue;
- durable revocation evidence;
- non-rollback frontier;
- named supervisor maintenance;
- final process-effect admission;
- tests, workflows and current documentation.

Those source elements are present on the candidate branch. The following remain separate gates and are **not** claimed complete:

- final exact-head and synthetic-merge green receipts;
- protected selected-host qualification;
- authenticated multi-node partition/revocation qualification;
- external long-term audit retention beyond bounded in-process windows;
- independent operator acceptance;
- deployment activation, promotion and release.

No document or source receipt grants deployment or release authority.
