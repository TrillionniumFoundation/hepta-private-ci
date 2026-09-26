# runtime.fleet durable-owner execution dossier

## 1. Candidate and claim boundary

Module: `runtime.fleet`

Owner/deputy: `fleet-runtime` / `runtime-control`

Primary source root: `codex-rs/hepta-fleet`

Named maintenance product caller: `codex-rs/hepta-supervisor/src/fleet_runtime_product.rs`

This dossier records source implementation and partial product composition on the `runtime-fleet/durable-owner-v1` candidate. It does not claim selected-host qualification, concrete Agent/worker effect enforcement, independent acceptance, activation, promotion or release.

## 2. Implemented owner state

The existing supervisor fleet root owns two coordinated durable surfaces:

1. `FleetRegistry`
   - Agent manifests and canonical workspaces;
   - lifecycle generations;
   - release state;
   - fleet-wide mutation lock;
   - rebuildable `workspace-reservations-v1.json`.
2. `DurableFleetOwner`
   - immutable checksummed allocation generations under `state/fleet-allocation-v1`;
   - trusted host/capacity observations;
   - active grants and bounded terminal history;
   - per-host resource totals;
   - authority witnesses and operation receipts;
   - signed revocation update/acknowledgement snapshot.

No second service or writer is introduced. `hepta-fleet-leased` remains inert.

## 3. Operation mapping

| Operation | Owner entry point | Important callees | Current state |
|---|---|---|---|
| register Agent | `FleetRegistry::register` | `RegistryMutationGuard`, workspace reservation publication | source implemented |
| lifecycle transition | `FleetRegistry::compare_and_transition` | immutable lifecycle hard-link publication | source implemented |
| observe host capacity | `refresh_capacity_idempotent` | `LinuxProcfsCapacityObserverV1`, `DurableFleetOwner::refresh_capacity` | source implemented and supervisor maintenance-composed |
| calculate local shares | `calculate_local_allocation_v1` | deterministic weighted max-min core | source implemented, authority-free |
| map logical resources | `map_logical_to_physical_v1` | reviewed `ResourceMappingPolicyV1` | source implemented |
| issue grant | `DurableFleetOwner::issue_with_authority` | `FleetAuthorityPort::issue_with_witness`, `LeaseLedger::issue` | source implemented; no concrete effect caller |
| renew/revoke | `DurableFleetOwner::renew_or_revoke` | current lease generation/epoch/digest checks | source implemented |
| reconcile expiry | `reconcile_expired_idempotent` | `DurableFleetOwner::reconcile_expired` | source implemented and supervisor maintenance-composed |
| persist revocation state | `DurableFleetOwner::persist_revocation_snapshot` | signed update/ack snapshot | source implemented |
| final-use verification | `verify_final_use_with_revocation` | revocation restore, Ready-state check, grant/host fences | source implemented; no concrete effect caller |
| operator status | `hepta-fleet-status` | durable reopen and metrics | source implemented, strictly read-only |

## 4. Atomic issue invariant

One issue transaction under the owner lock must satisfy all of the following before publication:

- stable operation ID absent or exactly idempotent;
- canonical grant and resource vector validate;
- live generic authority lease verifies at the final owner boundary;
- host identity, failure domain, generation and observation freshness match;
- active plus requested resources fit the observed capacity;
- allocation identity is not active or retained as terminal history;
- grant, per-host totals, authority witness and operation receipt enter the same candidate generation;
- candidate state validates and obtains a content digest;
- the immutable generation is linked and the owner directory is synchronized.

A failure after the generation link exists is `IndeterminateCommit`. Recovery is by exact operation-ID lookup before retry.

## 5. Capacity and long-running availability

The former 16,384 lifetime limit is removed. `MAX_ACTIVE_GRANTS` limits simultaneous live grants. Revocation, expiry and host-generation replacement remove grants from the active set, release resources exactly once and append a terminal history record.

The ledger maintains:

- active-grant map;
- deadline-to-allocation expiry index;
- exact per-host resource totals;
- bounded terminal history;
- compacted-history count and chained digest.

Repeated issue/terminal cycles can therefore exceed 16,384 lifetime identities without exhausting the active-grant ceiling.

## 6. Resource semantics

`ResourceVectorV1` is the canonical resource representation. It binds schema version, supported-axis mask, axis IDs, units, exact rounding and values.

Axes are:

- CPU milli-units;
- memory bytes;
- accelerator milli-units;
- concurrent turns;
- tool processes;
- turn queue slots.

Logical compatibility inputs convert immediately to a canonical logical vector. A reviewed mapping policy converts logical counts to physical resources using checked integer arithmetic and emits policy/logical/physical digests. The deterministic local share calculator does not itself issue authority or grant physical resources.

## 7. Registry concurrency and crash semantics

Registration and lifecycle mutation share the fleet registry mutation lock. Workspace overlap is checked while holding that lock, and the canonical reservation index is atomically replaced, directory-synchronized, read back and revalidated.

Test fault boundaries include:

- concurrent parent/child workspace registration;
- failure after registration rename;
- failure after lifecycle hard link;
- stale physical staging cleanup during reopen.

Post-publication failure is reported as indeterminate with a recovery key. It is never converted into a normal rejection.

## 8. Supervisor product composition

`hepta-supervisord` performs the owner maintenance path:

- opens the existing registry and durable owner;
- derives Linux host identity and boot-fenced generation, or requires a complete immutable override;
- observes CPU, `MemAvailable` and memory pressure;
- refreshes capacity through a durable-ID-first command;
- reconciles expired grants when metrics show pending work;
- cancels/fails the product on unexpected maintenance failure;
- retains the existing signed production-grant startup behavior.

This is partial product composition. The spawn/use boundary currently does not require an allocation ID or consume a revocation-bound grant-use witness.

## 9. Revocation and final-use behavior

The durable snapshot contains signed update and acknowledgement evidence but not trust roots. Restore requires independently pinned feed and node verifiers.

Final-use verification fails closed when:

- no durable revocation snapshot exists;
- the feed is stale;
- the node is catching up or quarantined;
- the node is unknown;
- the lease generation, host identity/generation or semantic digest differs;
- the grant or host observation is expired;
- the revocation snapshot digest changes across grant verification.

A successful witness is point-in-time evidence and must be consumed immediately before the physical effect. The concrete consumer remains a repository-controlled gap.

## 10. Observability and operations

The read-only `hepta-fleet-status` command requires an existing owner directory and at least one regular immutable generation. It does not initialize missing state.

It reports:

- active grants;
- expired uncollected grants;
- revoked uncompacted history;
- reserved and observed resources by host/axis;
- stale hosts;
- issue/renew/revoke result counters;
- revocation lag;
- registry conflicts;
- indeterminate commits;
- staging debris;
- generation-compaction backlog.

Thresholds, recovery procedures and forbidden manual mutations are defined in `docs/modules/runtime.fleet/OPERATIONS.md`.

## 11. Repository-controlled qualification

The focused workflow is intended to execute on the exact PR head and deterministic synthetic merge:

```sh
cargo fmt --all -- --check
cargo test -p codex-hepta-fleet --all-targets
cargo test -p codex-hepta-supervisor --lib
cargo check -p codex-hepta-supervisor --bin hepta-supervisord
cargo clippy -p codex-hepta-fleet --all-targets -- -D warnings
cargo clippy -p codex-hepta-supervisor --lib --bin hepta-supervisord -- -D warnings
```

It retains logs, command record and bounded source archive. A queued workflow is not a pass receipt.

A manual selected-host workflow requires an exact candidate SHA and reviewed self-hosted Linux profile. It verifies procfs inputs, runs the focused source commands, records a real capacity observation, reopens the durable state and retains the evidence. No successful selected-host run is claimed by this dossier until such an artifact exists and is independently accepted.

## 12. Remaining gaps

1. Bind actual Agent/worker start or resource use to an allocation ID and `RevocationBoundGrantUseWitnessV1`.
2. Compose real authority/revocation trust roots at that product boundary.
3. Qualify authenticated fanout, partition, catch-up and quarantine across selected nodes.
4. Obtain exact-head and synthetic-merge source receipts.
5. Obtain selected-host physical evidence and independent acceptance.
6. Define external audit retention beyond bounded in-process history and receipts.

## 13. Truth statement

Current source status:

- durable owner: implemented;
- supervisor maintenance caller: source composed;
- canonical resource model and mapping: implemented;
- authority-bound issue: implemented;
- revocation-bound final-use API: implemented;
- concrete physical-effect caller: absent;
- selected-host qualification: absent;
- deployment qualification: false;
- independent acceptance: false;
- activation: false;
- release: false.
