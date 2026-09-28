# runtime.fleet technical development guide

**Module:** `runtime.fleet`  
**Lane:** `LANE-B-RUNTIME`  
**Owner / deputy:** `fleet-runtime` / `runtime-control`  
**Named product owner:** `hepta-supervisord`  
**Canonical current state:** [`CURRENT_STATE.json`](CURRENT_STATE.json)  
**Detailed implementation:** [`DURABLE_OWNER.md`](DURABLE_OWNER.md)  
**Operations and recovery:** [`OPERATIONS.md`](OPERATIONS.md)  
**Execution-binding delivery and evidence boundary:** [`EXECUTION_BINDING.md`](EXECUTION_BINDING.md)

This document describes the current source implementation and its claim boundary. Source composition is not deployment qualification, independent operator acceptance, promotion or release. The standalone `hepta-fleet-leased` entry point remains intentionally inert; no second Fleet writer is authorized. The 2026-09-28 execution-binding revision does not claim complete product lifecycle closure: automatic selected-host containment/quiescence reconciliation and final candidate Cargo/merge execution evidence remain required.

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
- `codex-rs/hepta-supervisor/src/fleet_execution_admission.rs`
- `codex-rs/hepta-supervisor/src/daemon.rs`
- `codex-rs/hepta-supervisor/src/unix.rs`

Key components:

| Concern | Owner entry point |
|---|---|
| Agent registry and lifecycle | `FleetRegistry` in `registry.rs` |
| Bounded non-mutating registration read | `AgentManifest::read_registered` in `manifest_readonly.rs` |
| Cross-process registry serialization | `RegistryMutationGuard` in `registry_coordination.rs` |
| Canonical resources | `ResourceVectorV1` in `resource.rs` |
| Logical-to-physical mapping | `map_logical_to_physical_v1` in `resource_mapping.rs` |
| Active lease state machine | `LeaseLedger` in `lease_ledger_v3.rs` / `lease_ledger_v2.rs` |
| Generic authority consumption | `FleetAuthorityPort` in `authority_port.rs` |
| Durable owner | `DurableFleetOwner` in `durable_owner.rs` |
| Snapshot implementation | `durable_owner_core.rs` |
| Monotonic boot incarnation | `resolve_host_incarnation` in `durable_owner_incarnation.rs` |
| Execution intent and physical retention | `prepare_execution` / `reconcile_execution_group` in `durable_owner_execution.rs` |
| Existing-state read-only fence | `lock_fleet_snapshot` in `durable_owner_readonly.rs` |
| Capacity/pressure observation | `LinuxProcfsCapacityObserverV1` in `capacity_observer.rs` |
| Durable revocation evidence | `FleetRevocationSnapshotV1` in `revocation_snapshot.rs` |
| Final-use verification | `verify_final_use_with_revocation` in `final_use.rs` |
| Named maintenance caller | `run_supervisord_product` |
| Physical process admission | `FleetStartAdmission`, `ProcessBinding`, and the Unix `ProcessDriver` wrapper |

`hepta-supervisord` is the only named product process. It owns registry lifecycle, durable Fleet maintenance and the process-effect boundary. Agent and Matrix spawn/adopt source paths traverse current Fleet admission, including automatic recovery paths. New process effects first persist intent; adoption requires matching existing intent. These source calls are not proof that the entire product or containment lifecycle has executed successfully.

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

The process requirement comes from the registered manifest, not by copying the grant being checked. The native physical profile uses an operator-pinned mapping. Without that mapping, logical requirements remain logical and are not silently reduced to memory or invented CPU amounts. Every retained execution on one allocation contributes to an aggregate demand check; two process effects may not independently spend the same full grant. The host reservation counts the allocation once while checking that the sum of its execution requirements fits it.

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

`AgentManifest::read_registered` reads one bounded, physical manifest without opening the registry writer, scanning unrelated Agents or cleaning staging roots. It validates the manifest and exact principal. The process wrapper checks the available workspace/fleet/home/run/matrix paths against this registration and passes the same borrowed process specification to the raw driver.

## 6. Lease state, active/history separation and compaction

The lease ledger separates:

- `active_grants`: live authorization leases;
- `history`: revoked, expired or generation-replaced terminal records;
- `expiry_index`: expiry-to-allocation lookup;
- `committed_by_host`: exact active-authorization resource totals.

`MAX_ACTIVE_GRANTS = 16,384` is a simultaneous-live ceiling, not a lifetime ceiling. Revocation, expiry and host-generation replacement remove active authorization and append a terminal record. This releases the ledger's authorization commitment, not necessarily the physical reservation. Durable `fleet_resource_totals` is rebuilt from the union of active grants and retained execution holds. A physical pin survives expiry, revocation, owner reopen and parent exit until all held scopes for that allocation are proven quiescent by the selected-host owner. Terminal history is retained up to its bounded window and then folded into a chained compaction digest. Regression sources cover more than 16,384 sequential issue/terminal cycles.

An identity still present in active state or retained history cannot be reused with different semantics. Operation receipts add a second, bounded idempotency key. Business requirements for indefinite replay detection require an external audit archive; bounded in-process digests do not provide searchable indefinite identity retention.

Duplicate effect IDs and duplicate retained execution identities on one allocation reject preparation. Aggregate execution demands are checked both on prepare and when rebuilding reservations from recovered state. Failed or unavailable quiescence observation never releases only a subset of an allocation's holds.

## 7. Owner time and host observations

All time-sensitive mutations use an injected `FleetClock`; callers do not provide “current time.” Host freshness, expiry, renewal and final-use checks read the owner clock.

On Linux the selected-host observer derives evidence from:

- `std::thread::available_parallelism()`;
- `/proc/meminfo` `MemAvailable`;
- `/proc/pressure/memory` `some avg10`.

The normal product profile refreshes every 20 seconds with a 60-second TTL. Above the configured pressure ceiling, no synthetic zero capacity is published. A same-generation shrink below commitments is rejected atomically. Ordinary pressure/shrink does not itself terminate lifecycle supervision; integrity and incarnation failures are not reclassified as ordinary pressure. The native new-process path independently samples current capacity before preparing intent, so it does not wait for a previous observation to expire before rejecting insufficient physical capacity. This does not change grant-issuance APIs into a globally persisted pressure gate.

Boot identity is an opaque digest. The durable owner allocates a monotonic host incarnation separately, preserving it across same-boot owner restarts and advancing it for a new boot regardless of hash ordering. A host-generation change fences predecessor authorization; physical holds are not deleted merely because a generation changed.

## 8. Durable owner and atomic mutation boundary

Authoritative Fleet state is under:

```text
FLEET_ROOT/state/fleet-allocation-v1/
```

Each immutable generation contains:

- `fleet_hosts` and monotonic `fleet_host_incarnations`;
- `fleet_capacity_observations`;
- active grants, terminal history, expiry index and compaction digest;
- `fleet_resource_totals` and retained `fleet_execution_holds`;
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

A queue result or authority check alone is not allocation success. A prepared execution intent is likewise not proof that a process started, stopped or completed.

## 9. Non-rollback latest frontier

Immutable generations are supplemented by `latest-frontier-v1.json`, an independently checksummed and directory-synced non-rollback frontier. Opening the owner verifies that the latest retained state is the pinned generation or a verifiable descendant.

Automatic repair is limited to the crash window where a complete descendant generation is visible but the frontier update was not yet durable. The following fail closed:

- latest generation deletion;
- a nonzero state with a missing frontier;
- same-generation digest drift;
- a frontier ahead of retained state;
- a chain that cannot prove descent from the pinned frontier.

This prevents silent acceptance of an older valid snapshot after tail deletion. It does not replace host-level backup integrity, filesystem protection or independent audit retention. Read-only status does not perform frontier repair; an unsealed descendant is reported instead of being silently fixed.

## 10. Failure and recovery semantics

Failures before publication are ordinary rejections. If a generation link or frontier rename may already be visible but directory synchronization fails, the result is `IndeterminateCommit { operation_id, generation, detail }`.

Recovery procedure:

1. stop blind retry;
2. reopen the same Fleet state root through the existing writer's recovery path;
3. validate the non-rollback frontier and retained chain;
4. query the exact operation ID;
5. accept only a receipt with the intended operation digest;
6. retry with the same operation ID and unchanged payload only when noncommit is established within retained history or the external archive;
7. quarantine any same-ID/different-digest conflict.

Time-dependent command adapters resolve a retained operation ID before observing a new clock or capacity sample, preventing retry drift. An execution intent whose later effect is ambiguous stays pinned. A missing parent PID, a successful signal or a lost result is not a complete execution-scope quiescence receipt.

## 11. Revocation persistence and final-use admission

Fleet state persists signed revocation updates and exact signed node acknowledgements; trust roots are never stored in Fleet state. At startup the product requires an immutable bounded `FleetStartTrustProfileV1` containing the local node, distributor keys and closed node key sets.

Final-use verification requires:

- a durable revocation snapshot;
- a fresh authenticated current update;
- the local node to be enrolled and exactly acknowledged;
- `Ready` node state;
- one current, unrevoked, unexpired grant for the Agent principal;
- current allocation, lease and host-generation fences;
- current semantic digest;
- an unchanged revocation-snapshot digest across grant verification.

`CatchingUp`, `Quarantined` and `FeedStale` deny use. The Unix process driver composes verification at Agent spawn, Agent adoption, Matrix spawn and Matrix adoption. Product automatic restart, upgrade, rollback and recovery use this wrapper; unscoped legacy library compatibility is not evidence of product admission.

`ProcessBinding` obtains host identity from the selected host and committed incarnation, obtains required resources from the registration, and binds the process context plus mapping digest. Dispatch identity preserves Unix program/argument byte arrays, ordering and path values rather than lossy strings. A shared validated owner fence stays alive across the synchronous raw spawn/adopt call. Adoption must find one matching retained intent and still pass the raw driver's PID/control-socket identity checks.

The wrapper periodically revalidates authority while a process is polled. Denial requests stop, then escalates to kill after the source-defined grace period. Neither event releases physical pins. The complete selected-host containment/quiescence adapter is still a required product composition gate. Command/path framing does not prove executable-file immutability or install kernel CPU/memory limits.

The trust profile is source configuration, not a secret grant. It must be a regular non-symlink JSON file and is immutable for one daemon generation.

## 12. Product startup and CLI contract

The named product requires:

```sh
hepta-supervisord \
  --fleet-root /absolute/fleet-root \
  --fleet-start-trust-profile /absolute/fleet-start-trust-v1.json
```

Optional production-grant and H7 verifier key/id/epoch triplets remain all-or-nothing. The Fleet start trust profile is mandatory because starting a process without current revocation and allocation verification would be an authority bypass.

Host identity may be derived from `/etc/machine-id`, with opaque boot identity read from `/proc/sys/kernel/random/boot_id` and monotonic generation assigned by the owner. Overrides must be a complete immutable triple and satisfy the durable incarnation fence:

```text
HEPTA_FLEET_HOST_ID
HEPTA_FLEET_FAILURE_DOMAIN_ID
HEPTA_FLEET_HOST_GENERATION
```

For native physical grants, configure `HEPTA_FLEET_RESOURCE_MAPPING_PROFILE` to a reviewed `ResourceMappingPolicyV1` JSON file. It must be absolute, physical, operator-owned, outside Fleet state, not group/world writable and at most one MiB. The mapping is captured for one driver lifetime. Agentd and Matrixd are distinct execution scopes; the allocation must cover the sum of their mapped requirements. The profile is not inferred from a grant and does not itself issue authority.

## 13. Observability and operator interface

`hepta-fleet-status` is read-only and requires existing state. Its diagnostic model includes active, expired-uncollected and revoked-uncompacted grants, reserved and observed capacity, stale hosts, revocation lag, staging debris and compaction backlog. The operational vocabulary also includes issue/renew/revoke counters, registry conflicts and indeterminate commits.

A standalone snapshot reader cannot recover another process's volatile counters. Those fields must be explicitly unavailable/null rather than a fabricated business zero. CLI argument, schema, frontier and file errors are failures, not healthy empty Fleet results. Unsupported `preflight`, `dry-run`, mutation or Prometheus modes are rejected rather than silently executing status. Thresholds, implemented commands and forbidden operations are normative in `OPERATIONS.md`; durable receipts and generations are authoritative.

## 14. Verification and qualification

Repository-controlled qualification includes:

- `cargo fmt --all -- --check`;
- all `codex-hepta-fleet` and `codex-hepta-supervisor` targets;
- `hepta-supervisord` binary compilation;
- strict all-feature Clippy for Fleet and supervisor;
- exact-source and deterministic synthetic-merge receipts;
- worktree cleanliness and command records;
- Git-object regression tests for the qualification mechanism itself.

`runtime_fleet_qualify.py` requires immutable full source/base SHAs. Synthetic qualification verifies both ordered parents and the actual `git merge-tree` content, not merely a merge-shaped commit. It validates the clean candidate before, between and after commands, archives the complete tracked tree and binds logs/archive/receipt digests. Fresh attempt directories live outside source. Candidate, command and infrastructure failures remain failures; no source repair or success-flag rewrite is performed.

Regression sources cover grant churn beyond 16,384 lifetime operations, simultaneous active-limit rejection, exact expiry, generation fencing, overlapping registration, publication crash boundaries, durable reopen, revocation restore, non-rollback recovery, real-child physical hold retention, changed execution IDs, aggregate overspend, unavailable quiescence and read-only CLI behavior. The real-child owner tests are not a full Agentd/Matrixd containment test.

A protected self-hosted workflow targets `[self-hosted, linux, x64, hepta-fleet-target]`. It must be bound to the final candidate SHA and an approved host profile. Source tests and local formatting cannot establish protected-host product execution. Refer to `EXECUTION_BINDING.md` and the scoped local evidence record for what was actually run.

## 15. Capacity and performance bounds

Current source ceilings include:

- up to 256 enrolled hosts/revocation nodes where specified;
- up to 4,096 local allocation candidates;
- up to 16,384 simultaneous active grants;
- up to 32,768 retained terminal grant records and execution holds where specified;
- up to 16,384 retained operation receipts;
- eight retained immutable state generations plus the non-rollback frontier.

These are enforced source bounds, not selected-host performance claims. One-Agent bounded manifest reads and removal of a redundant admission metrics reload reduce avoidable work. Synchronous final-use/owner I/O, maintenance scheduling, sustained latency, filesystem durability, pressure behavior and long-backlog recovery still require target measurement and optimization without discarding durability evidence.

## 16. Compatibility, migration and retirement

The public `DurableFleetOwner` wraps the established snapshot implementation and adds the non-rollback frontier without introducing another writer. The frontier is created with generation zero. A missing frontier beside a nonzero generation is rejected; operators must not manually synthesize it.

Compatibility adapters are temporary and may not widen authority. Retirement requires all named callers migrated, no old-path use, equivalent failure semantics, a rehearsed rollback and independent acceptance. Historical evidence remains interpretable after retirement. Existing running processes without durable matching execution intent are not silently adopted into the new product path. Migration must reconcile their actual containment and authority rather than fabricate a hold.

## 17. Completion and claim boundary

Repository-controlled source work covers durable grants, active/history/expiry/compaction, registry serialization, owner time, canonical resources, mapping receipts, authority-bound issue, revocation evidence, the non-rollback frontier, named maintenance, independently bound execution intent and process-effect wrappers.

Neither complete repository/product closure nor deployment readiness is asserted. Remaining gates include:

- complete selected-host containment enforcement and automatic quiescence-to-release composition;
- final exact-head and synthetic-merge green receipts with full Cargo/Clippy results;
- real product crash, restart, adoption, expiry/revocation, descendant cleanup and re-admission execution;
- mapping/aggregate budget qualification for concurrent Agentd and Matrixd scopes;
- protected selected-host qualification and sustained-runtime measurements;
- authenticated multi-node partition/revocation qualification where required by deployment;
- external long-term audit retention beyond bounded in-process windows;
- independent operator acceptance;
- deployment activation, promotion and release.

`CURRENT_STATE.json` separates source composition from execution proof and keeps unclosed gates explicit. Its source implementation commit is a code anchor, not a self-referential assertion that a later documentation commit passed qualification. Final receipts identify the actual tested source and merge trees. No document or source receipt grants deployment or release authority.
