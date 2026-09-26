# runtime.fleet durable owner and current product composition

This document records the current source implementation of `runtime.fleet` on the `runtime-fleet/durable-owner-v1` candidate. It supplements `TECHNICAL.md` and is intentionally narrower than a deployment or release claim.

The existing `hepta-supervisord` process remains the sole fleet owner. The standalone `hepta-fleet-leased` binary remains inert and must not be converted into a second writer.

## 1. Current implementation state

| Layer | Current state | Evidence boundary |
|---|---|---|
| Agent registry and lifecycle | durable source implementation | `FleetRegistry`, fleet-wide mutation lock, workspace reservation index and generation-fenced lifecycle files |
| Canonical resources | source implemented | `ResourceVectorV1`, explicit axes/units/mask/max/exact rounding and semantic digest |
| Logical-to-physical mapping | source implemented | reviewed `ResourceMappingPolicyV1` and a receipt binding policy, logical vector and physical vector digests |
| Allocation ledger | durable source implementation | active/history split, expiry index, per-host totals, generation fencing and bounded compaction |
| Authority issue boundary | source implemented | `FleetAuthorityPort::issue_with_witness` performs final live authority verification before the owner mutation |
| Durable allocation owner | source implemented | checksummed immutable generations under the existing supervisor state root |
| Capacity observer | Linux source implemented | `available_parallelism`, `/proc/meminfo` and `/proc/pressure/memory` |
| Supervisor maintenance caller | source composed | `hepta-supervisord` opens the owner, refreshes observations and reconciles expiry |
| Revocation persistence | source implemented | signed update and acknowledgement snapshot; trust roots are supplied independently at restore/final use |
| Final-use verification API | source implemented | current grant, lease, host generation and unchanged revocation snapshot are required |
| Concrete Agent/worker effect caller | not composed | no physical start/use boundary currently consumes an allocation ID and revocation-bound witness |
| Selected-host qualification | not established | a manual self-hosted workflow exists, but no accepted exact-candidate receipt is claimed here |
| Independent acceptance/release | false | externally governed |

## 2. Single-writer topology

```text
hepta-supervisord
  ├─ FleetRegistry
  │    ├─ agent manifests
  │    ├─ lifecycle generations
  │    ├─ release state
  │    └─ workspace-reservations-v1.json
  │
  └─ DurableFleetOwner
       ├─ trusted host/capacity observations
       ├─ active grants and terminal history
       ├─ per-host resource totals
       ├─ authority witnesses and operation receipts
       ├─ revocation snapshot
       └─ immutable checksummed generations
```

All state resides below the canonical fleet root. The durable allocation owner uses:

```text
FLEET_ROOT/state/fleet-allocation-v1/
```

It holds one exclusive owner lock while loading the latest committed generation, validating a candidate mutation and publishing the next generation. It does not write Agent-owned state.

## 3. Durable datasets

One `DurableFleetStateV1` generation contains the following logical datasets:

| Required dataset | Current representation |
|---|---|
| `fleet_hosts` | canonical host identity, failure domain and generation |
| `fleet_capacity_observations` | trusted bounded observation including freshness and pressure |
| `fleet_grants` | `LeaseLedgerSnapshot`: hosts, active grants, bounded terminal history and compacted-history digest |
| `fleet_resource_totals` | exact per-host canonical `ResourceVectorV1` totals rebuilt from active grants |
| `fleet_revocation_frontier` | optional signed update plus exact signed node acknowledgements |
| `fleet_revocation_acks` | acknowledgements inside the revocation snapshot, bounded by the enrolled-node ceiling |
| `workspace_reservations` | canonical registry index stored separately; every fleet generation binds the file digest |
| `fleet_operation_receipts` | bounded durable idempotency and audit receipts, including authority witness on issue |

The state also binds schema version, generation, predecessor state digest, compacted receipt-chain count/digest and its own content digest.

## 4. Generation publication and recovery

A mutation proceeds as follows:

1. Acquire the existing owner lock.
2. Load the latest complete generation.
3. Verify filename/generation identity, content digest and retained hash-chain continuity.
4. Rebuild the ledger indexes and resource totals from the snapshot.
5. Validate the typed command and any retained operation ID.
6. Apply the mutation to an in-memory candidate.
7. Validate all cross-dataset invariants.
8. Serialize and `fsync` a private temporary file.
9. Publish the immutable generation with a hard link.
10. `fsync` the owner directory before returning success.

Failure before publication is a normal rejection. Failure after the final generation link exists is `IndeterminateCommit`; the caller must reopen and query the exact operation ID before retrying.

Startup rejects partial, malformed, symlinked or digest-inconsistent state. It does not truncate unknown bytes or fabricate an empty successful history.

## 5. Grant lifecycle and the former 16,384 lifetime ceiling

The ledger now separates:

- `active_grants`: only live, capacity-consuming grants;
- `history`: revoked, expired or generation-replaced terminal records;
- `expiry_index`: deadline to allocation-ID index;
- `committed_by_host`: exact active resource totals.

`MAX_ACTIVE_GRANTS = 16,384` now limits simultaneous live grants, not lifetime allocation IDs. Revocation, expiry and host-generation replacement remove the grant from the active map, release capacity exactly once and append a bounded terminal record. Terminal history is compacted into a chained digest after its retention ceiling.

An allocation ID retained in active or terminal state cannot be reused with different semantics. Idempotency for a committed external command is additionally bound by a stable operation ID and operation digest.

## 6. Owner clock and time-dependent retries

`FleetClock` is injected by the owner. Public ledger mutations no longer accept caller-supplied “current time.” Host freshness, lease expiry, renewal and final-use checks use the owner clock.

Capacity observation and expiry reconciliation are time-dependent. Their product-facing command functions first reload the durable owner and look up the operation ID. Only an absent ID may observe the current clock or host again. This avoids changing the command digest merely because an indeterminate retry occurs later.

## 7. Registry serialization and workspace reservations

Registration and lifecycle publication share one fleet-wide file lock owned by the existing registry state root.

Registration performs workspace-overlap validation and publication within that lock. The canonical workspace reservation index is atomically replaced, directory-synced, read back and revalidated before success. Concurrent parent/child workspace registration therefore has a single winner.

A registration rename or lifecycle hard link followed by synchronization failure returns a recovery key in `FleetRegistryError::IndeterminateCommit`. Physical `.staging-*` directories left by a crashed registration are removed only while holding the registry mutation lock.

## 8. Canonical resource model

`ResourceVectorV1` has six explicit axes:

| Axis ID | Unit | Rounding |
|---|---|---|
| `cpu_millis` | milli-CPU | exact integer |
| `memory_bytes` | bytes | exact integer |
| `accelerator_millis` | milli-accelerator | exact integer |
| `concurrent_turns` | count | exact integer |
| `tool_processes` | count | exact integer |
| `turn_queue_slots` | count | exact integer |

Every vector carries schema version and a supported-axis mask. A requirement fits only when the capacity supports every required axis and every amount is within the corresponding bound. Addition, subtraction and MiB-to-byte conversion are checked; overflow and underflow fail closed.

The semantic digest binds schema, axis mask, axis IDs, units and values.

### 8.1 Legacy logical compatibility

`ResourceBudget` and `LocalAllocationShareV1` remain compatibility input shapes. They are converted immediately to canonical logical vectors.

A `ResourceMappingPolicyV1` explicitly maps each logical count to physical CPU, memory and accelerator coefficients. `map_logical_to_physical_v1` uses checked integer arithmetic and returns a receipt binding:

- policy ID and digest;
- logical vector digest;
- physical vector and digest.

The local weighted allocation calculator remains authority-free. Its output is not a grant until a reviewed mapping policy, current host observation, authority lease and durable owner transaction all succeed.

## 9. Atomic authority-bound issue

`DurableFleetOwner::issue_with_authority` executes under the owner lock:

1. Reload and validate the latest generation.
2. Deduplicate or conflict-check the stable operation ID.
3. Reconstruct active grants, expiry index and resource totals.
4. Compute the exact authority binding from allocation semantics and canonical resource digest.
5. Revalidate the live generic authority lease at the final owner boundary.
6. Revalidate host identity, generation and observation freshness.
7. Check canonical resource compatibility and capacity.
8. Insert the grant and update resource totals in the candidate generation.
9. Persist the non-authorizing authority witness and lease receipt with the same generation.
10. Publish only after all invariants pass.

A queue, handler return or authority check alone is not a successful allocation receipt.

## 10. Capacity and pressure observation

The Linux observer derives capacity from operating-system sources rather than allocation-request fields:

- CPU availability: `std::thread::available_parallelism()`;
- memory: `/proc/meminfo` `MemAvailable`;
- pressure: `/proc/pressure/memory`, `some avg10`.

The normal supervisor profile refreshes every 20 seconds with a 60-second TTL. Above the configured memory-pressure ceiling it declines to refresh; the prior observation expires naturally and subsequent issue/renew paths fail closed.

A same-generation refresh preserves active grants only when they fit the new observation. A capacity shrink below live commitments is rejected without mutating state. A host-generation change is an explicit fence and retires predecessor grants.

The selected-host probe and workflow do not themselves establish deployment acceptance. They provide the mechanism for binding physical evidence to an exact commit and reviewed host profile.

## 11. Revocation persistence and final use

The durable snapshot stores signed revocation update/acknowledgement evidence but never stores trust roots. Restore and final use require independently pinned feed and node verifiers.

`verify_final_use_with_revocation` requires:

- a durable revocation snapshot;
- authenticated, fresh and converged current update;
- the exact node to be enrolled and `Ready`;
- current allocation ID, lease generation, host ID and host generation;
- current semantic digest;
- an unchanged revocation snapshot digest before and after grant verification.

`CatchingUp`, `Quarantined` and `FeedStale` all deny final use.

This API is source complete, but the repository still needs a concrete Agent/worker effect boundary that supplies the real allocation identity and consumes the witness immediately before physical resource use.

## 12. Supervisor product caller

`hepta-supervisord` is the named source-composed maintenance caller. It:

- opens `FleetRegistry` and the durable owner under the same fleet root;
- derives a Linux host identity from `/etc/machine-id` and a boot-fenced generation from `/proc/sys/kernel/random/boot_id`, or accepts a complete immutable three-variable override;
- performs capacity refresh through the durable-ID-first command port;
- reconciles expired grants when the durable metrics show work;
- treats maintenance errors as product errors rather than silently discarding them;
- preserves the existing signed production-grant startup path.

This composition establishes the owner’s maintenance path. It does not yet prove that each spawned Agent or worker performs allocation admission/final-use verification.

## 13. Operator interface and observability

`hepta-fleet-status` is strictly read-only: it first requires an existing physical owner directory and at least one regular immutable generation. It refuses to create missing state.

It emits the requested operational surfaces:

- `fleet_active_grants`;
- `fleet_expired_uncollected_grants`;
- `fleet_revoked_uncompacted_grants`;
- `fleet_reserved_resource{host,axis}`;
- `fleet_observed_capacity{host,axis}`;
- `fleet_stale_hosts`;
- `fleet_grant_issue_total{result}`;
- `fleet_grant_renew_total{result}`;
- `fleet_grant_revoke_total{result}`;
- `fleet_revocation_lag_ms`;
- `fleet_registry_conflict_total`;
- `fleet_indeterminate_commit_total`;
- `fleet_staging_debris`;
- `fleet_compaction_backlog`.

The complete alert thresholds, recovery commands and forbidden operations are in `OPERATIONS.md`.

## 14. Repository-controlled qualification

The focused workflow checks the exact source and deterministic synthetic merge with:

- formatting;
- all `codex-hepta-fleet` targets;
- supervisor library tests;
- `hepta-supervisord` binary compilation;
- strict clippy for fleet and supervisor;
- tracked-worktree cleanliness;
- retained source, logs and command record.

The test sources cover sequential grant churn beyond the former lifetime ceiling, capacity conservation, expiry, generation fencing, final-use checks, snapshot restore, concurrent overlapping registration, post-publication crash boundaries, procfs parsing, same-generation capacity refresh, logical-to-physical mapping and operation-ID-first retry.

A separate manual workflow targets `[self-hosted, linux, x64, hepta-fleet-target]` and binds its evidence to an explicit candidate SHA and host profile. Until that workflow runs successfully on a selected host and its evidence is independently accepted, deployment qualification remains false.

## 15. Remaining work and claim boundary

Repository-controlled source work that remains before full product closure:

1. Bind a concrete Agent/worker start or use boundary to a durable allocation ID and `RevocationBoundGrantUseWitnessV1` immediately before physical use.
2. Provide the product authority-registry/trust-root composition for that boundary without embedding secrets or trust roots in fleet state.
3. Qualify authenticated revocation fanout and partition behavior on a selected multi-node environment.
4. Obtain an exact-candidate selected-host receipt and independent acceptance.
5. Decide the long-term externally retained audit policy beyond the bounded in-process receipt/history windows.

This document claims source implementation and partial product composition only. It grants no deployment, external-effect, independent acceptance, promotion or release authority.
