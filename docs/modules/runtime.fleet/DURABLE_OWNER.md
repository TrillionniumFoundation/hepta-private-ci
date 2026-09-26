# runtime.fleet durable owner and product composition

This document is the implementation-level companion to [`TECHNICAL.md`](TECHNICAL.md). Its machine-readable status is [`CURRENT_STATE.json`](CURRENT_STATE.json). The existing `hepta-supervisord` process remains the sole Fleet owner; `hepta-fleet-leased` remains inert.

## 1. Current source state

| Layer | State | Boundary |
|---|---|---|
| Agent registry/lifecycle | implemented | durable manifests, lifecycle generations, release state |
| Registry serialization | implemented | Fleet-wide lock, workspace-reservation index, indeterminate publication |
| Canonical resources | implemented | versioned `ResourceVectorV1`, units, axes, exact checked arithmetic |
| Resource mapping | implemented | reviewed policy plus logical/policy/physical digest receipt |
| Allocation ledger | implemented | active/history split, expiry index, exact per-host totals, bounded compaction |
| Durable allocation owner | implemented | immutable checksummed generations under supervisor state root |
| Non-rollback frontier | implemented | independently checksummed latest generation, descendant-only recovery |
| Authority issue | implemented | final live authority revalidation and witness persisted atomically |
| Capacity observer | Linux source implemented | CPU, available memory and PSI pressure |
| Revocation persistence | implemented | signed update and exact signed acknowledgements; trust roots external |
| Supervisor maintenance | source composed | capacity refresh and expiry reconciliation |
| Physical process admission | source composed | Agent/Matrix spawn and adopt verify grant plus revocation immediately before effect |
| Operator status/runbook | implemented | read-only status, alert thresholds and recovery commands |
| Selected-host/multi-node acceptance | not established | protected external evidence gates |
| Independent release authority | false | externally governed |

## 2. Single-writer topology

```text
hepta-supervisord
  ├─ FleetRegistry
  │    ├─ agent manifests
  │    ├─ lifecycle generations
  │    ├─ release state
  │    └─ workspace-reservations-v1.json
  │
  ├─ DurableFleetOwner
  │    ├─ immutable generation-N snapshots
  │    ├─ latest-frontier-v1.json
  │    ├─ trusted capacity observations
  │    ├─ active grants / terminal history / expiry index
  │    ├─ exact per-host resource totals
  │    ├─ operation receipts and issue authority witnesses
  │    └─ signed revocation snapshot
  │
  └─ Unix ProcessDriver effect boundary
       ├─ Agent spawn/adopt admission
       └─ Matrix spawn/adopt admission
```

No component in this design writes Agent-owned state or launches another Fleet owner.

## 3. Durable datasets

One `DurableFleetStateV1` generation binds:

| Dataset | Representation |
|---|---|
| `fleet_hosts` | host, failure domain and generation |
| `fleet_capacity_observations` | capacity, pressure and freshness evidence |
| `fleet_grants.active` | live capacity-consuming grants |
| `fleet_grants.history` | retained terminal records |
| `fleet_grants.expiry_index` | deadline-to-allocation index |
| `fleet_grants.compaction` | count plus chained digest for compacted history |
| `fleet_resource_totals` | exact canonical reserved totals per host |
| `fleet_revocation_frontier` | signed update plus exact signed acknowledgements |
| `workspace_reservations` | separately stored index bound by digest |
| `fleet_operation_receipts` | bounded idempotency/audit window |
| authority witness | persisted in the same generation as successful issue |

Each state binds schema version, generation, predecessor digest and content digest. `latest-frontier-v1.json` independently binds the highest committed generation, its state digest and predecessor digest.

## 4. Publication protocol

A normal mutation:

1. acquires `owner.lock`;
2. loads all retained generation files in order;
3. verifies file type, filename/generation identity, content digest and chain continuity;
4. verifies the non-rollback frontier;
5. reconstructs indexes and totals;
6. resolves the stable operation ID;
7. applies one typed command;
8. validates cross-dataset invariants;
9. serializes and `fsync`s a private temporary generation;
10. publishes by immutable hard link;
11. `fsync`s the owner directory;
12. advances the checksummed latest frontier with a temporary file, atomic rename and directory `fsync`;
13. returns a receipt only after both state and frontier are durable.

Failure before publication is a normal rejection. A possible state or frontier publication followed by synchronization failure is `IndeterminateCommit`.

## 5. Non-rollback recovery

The owner accepts exactly three states:

- the retained latest generation equals the pinned frontier;
- a complete one-or-more-generation retained chain proves descent from the pinned frontier and advances it;
- generation zero initializes the first frontier.

It rejects:

- latest generation lower than the frontier;
- same generation with a different digest;
- missing frontier beside nonzero state;
- an unverifiable retained gap;
- malformed, symlinked or non-regular state/frontier files.

This permits recovery after a crash between state publication and frontier durability without permitting silent tail deletion rollback.

## 6. Grant lifecycle

`MAX_ACTIVE_GRANTS = 16,384` limits simultaneous live grants. It no longer limits lifetime allocation IDs. A terminal transition removes the active grant, releases exact capacity once, records the terminal reason and updates the expiry index.

Retained history is bounded. Older terminal records are folded into a chained digest. This preserves tamper-evident aggregate lineage but not searchable indefinite replay identity. Long-term searchable audit retention is an external operational obligation.

## 7. Atomic authority-bound issue

`issue_with_authority` runs under the owner lock and performs:

1. stable operation-ID deduplication/conflict detection;
2. exact allocation binding calculation;
3. live generic authority verification at the final owner boundary;
4. host generation and observation freshness verification;
5. canonical resource compatibility and capacity check;
6. active grant insertion;
7. per-host total update;
8. operation receipt and authority witness persistence;
9. immutable generation and frontier publication.

The issue result is successful only when the durable generation and frontier are established. The witness is audit evidence, not reusable authority.

## 8. Owner clock and idempotent time-dependent commands

`FleetClock` is injected. Public mutation APIs do not accept a caller-controlled current time. Capacity refresh and expiry reconciliation use adapters that first resolve an existing operation ID. Only an absent ID reads a new clock or host sample.

This ensures that an indeterminate retry with the same operation ID cannot silently acquire a different time-dependent semantic digest.

## 9. Workspace reservations and registry commit ambiguity

Registration and lifecycle transitions share a Fleet-wide file lock. Workspace overlap is checked and the canonical reservation index is persisted within that serialized boundary. Parent/child or identical workspace registration races therefore have one winner.

If rename or lifecycle hard-link publication may have happened before directory synchronization fails, the registry returns an indeterminate error with a recovery identity. Blind retries and manual file deletion are forbidden.

## 10. Canonical resource model

`ResourceVectorV1` supports CPU milli-units, bytes, accelerator milli-units, concurrent turns, tool processes and queue slots. It binds schema, unit, supported-axis mask and amount into its digest.

`ResourceMappingPolicyV1` converts logical resources to physical resources with checked exact integer coefficients. The mapping receipt binds:

- policy identity and digest;
- logical vector digest;
- physical vector and digest.

The local weighted allocator remains an authority-free calculation and cannot directly publish a grant.

## 11. Capacity and pressure

The Linux observer reads actual host surfaces rather than allocation request values. Capacity observations are bounded and expire. High pressure suppresses refresh so stale state expires naturally; it never fabricates a successful zero-capacity observation.

Same-generation capacity shrink is admitted only when all live commitments still fit. Host-generation change fences predecessor grants and releases their capacity through a terminal transition.

## 12. Durable revocation and physical final use

The snapshot stores signed updates and acknowledgements, not trust roots. `hepta-supervisord` requires a regular non-symlink `FleetStartTrustProfileV1` at startup. The profile pins:

- local node identity;
- revocation distributor identity and epoch-bounded keys;
- closed enrolled node identities and epoch-bounded keys.

At Agent or Matrix spawn/adopt, the driver:

1. opens and verifies the durable owner and latest frontier;
2. finds exactly one active grant for the Agent principal;
3. restores the signed revocation snapshot with the independently pinned trust profile;
4. requires the local node to be current and `Ready`;
5. verifies allocation ID, lease generation, host ID/generation and semantic digest;
6. rechecks the snapshot digest across grant verification;
7. performs the operating-system process effect only after successful admission.

Missing, ambiguous, stale, catching-up, quarantined or feed-stale evidence denies the effect. Automatic restart and adoption use the same driver and cannot bypass the check.

## 13. Product startup

Minimum invocation:

```sh
hepta-supervisord \
  --fleet-root /absolute/fleet-root \
  --fleet-start-trust-profile /absolute/fleet-start-trust-v1.json
```

The profile is immutable for one daemon generation. Production grant and H7 verifier triplets remain optional but all-or-nothing. Host identity can be automatically boot-fenced on Linux or supplied only as a complete three-variable override.

## 14. Operational metrics

The read-only status command exposes active/expired/revoked counts, capacity and reservations by host/axis, stale hosts, mutation outcomes, revocation lag, registry conflicts, indeterminate commits, staging debris and compaction backlog.

Durable generations and receipts are authoritative. Per-process counters reset on restart and are diagnostic only.

## 15. Qualification

The focused workflow runs exact-source and synthetic-merge jobs with formatting, all-target Fleet tests, supervisor tests, product binary compilation and strict clippy. A separate protected self-hosted workflow binds selected-host evidence to an explicit candidate SHA and host profile.

Source tests are not proof of physical deployment. Selected-host, multi-node partition/revocation, long-term audit retention and independent acceptance remain external gates.

## 16. Claim boundary

The candidate closes repository-controlled source implementation and named product source composition. It does not claim:

- a green receipt until the final candidate SHA finishes CI;
- selected-host acceptance;
- authenticated multi-node qualification;
- deployment activation;
- independent operator acceptance;
- promotion or release.
