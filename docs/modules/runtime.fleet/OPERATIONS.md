# runtime.fleet operations and recovery

This runbook applies to the supervisor-owned `runtime.fleet` durable owner. It does not create a second fleet service. The named product process is `hepta-supervisord`; `hepta-fleet-leased` remains intentionally inert.

## 1. State location and ownership

For a fleet root `FLEET_ROOT`, authoritative runtime files are under:

```text
FLEET_ROOT/state/fleet-allocation-v1/
```

The owner publishes immutable, checksummed generation files while holding `owner.lock`. One generation binds:

- enrolled host identity and generation;
- trusted capacity/pressure observations;
- active grants and bounded terminal history;
- per-host resource totals;
- signed revocation frontier and acknowledgements;
- the workspace-reservation index digest;
- bounded operation receipts and persisted authority witnesses.

The registry separately owns `FLEET_ROOT/state/workspace-reservations-v1.json`; every fleet generation binds its exact file digest. Agent-owned stores are never written by this module.

## 2. Normal product composition

`hepta-supervisord` opens the durable owner before serving lifecycle requests. On Linux it derives a stable host identity from `/etc/machine-id`, a boot-fenced host generation from `/proc/sys/kernel/random/boot_id`, and physical capacity from:

- `std::thread::available_parallelism()`;
- `/proc/meminfo` `MemAvailable`;
- `/proc/pressure/memory` `some avg10`.

A deployment may replace the derived identity only by configuring all three immutable values together:

```text
HEPTA_FLEET_HOST_ID
HEPTA_FLEET_FAILURE_DOMAIN_ID
HEPTA_FLEET_HOST_GENERATION
```

The current source profile refreshes every 20 seconds with a 60-second observation TTL and declines refresh above 50% ten-second memory pressure. The previous observation then expires naturally, after which new grants fail closed. A host reboot changes the generation and fences predecessor grants. A same-generation refresh preserves grants only when they still fit the newly observed capacity.

## 3. Operator status command

Build the read-only status tool from `codex-rs`:

```sh
cargo build -p codex-hepta-fleet --bin hepta-fleet-status
```

Read the latest generation:

```sh
hepta-fleet-status \
  --state-root /absolute/FLEET_ROOT/state
```

Look up a retained operation after an indeterminate response:

```sh
hepta-fleet-status \
  --state-root /absolute/FLEET_ROOT/state \
  --operation-id EXACT_OPERATION_ID
```

Return exit status 2 when a configured alert is present:

```sh
hepta-fleet-status \
  --state-root /absolute/FLEET_ROOT/state \
  --fail-on-alert
```

The command is read-only. Operation lookup covers the bounded retained receipt window. It is not authority to repeat an effect.

## 4. Metrics and alert thresholds

| Metric | Threshold | Severity | Operator action |
|---|---:|---|---|
| `fleet_active_grants` | capacity dependent | information | Compare per-axis reservations with independently observed capacity. |
| `fleet_expired_uncollected_grants` | `> 0` after one maintenance interval | critical | Restore `hepta-supervisord` maintenance; do not delete or edit generations. |
| `fleet_revoked_uncompacted_grants` | sustained growth toward the 32,768 retained-history bound | warning | Verify successful commits and history compaction; retain external audit evidence before changing policy. |
| `fleet_reserved_resource{host,axis}` | `>= 90%` of observed capacity | warning | Reduce admission or add independently observed capacity. |
| `fleet_reserved_resource{host,axis}` | `>= 100%` | critical | Deny further issue; investigate observation or reconciliation drift. |
| `fleet_observed_capacity{host,axis}` | absent for a host with reservations | critical | Deny use and restore the trusted observer. |
| `fleet_stale_hosts` | `> 0` | critical | Restore the observer; new issue/renew must stay denied. |
| `fleet_grant_issue_total{result}` | rejected/indeterminate increase | warning or critical | Inspect exact operation receipts and authority/host fences. These result counters are process-local; durable receipts are authoritative. |
| `fleet_grant_renew_total{result}` | rejected/indeterminate increase | warning or critical | Check lease generation, expiry, host generation and authority epoch. |
| `fleet_grant_revoke_total{result}` | indeterminate increase | critical | Reopen and look up the exact operation ID before retrying. |
| `fleet_revocation_lag_ms` | greater than the persisted convergence SLA | critical | Quarantine non-ready nodes and restore authenticated fanout. |
| `fleet_registry_conflict_total` | `> 0` | warning | Inspect concurrent workspace/lifecycle requests; do not bypass the registry lock. |
| `fleet_indeterminate_commit_total` | `> 0` | critical | Reopen state and reconcile by operation ID. Never blind-retry. |
| `fleet_staging_debris` | `> 0` | warning | Reopen `FleetRegistry`; startup removes only physical `.staging-*` directories under the mutation lock. Investigate repeated crashes. |
| `fleet_compaction_backlog` | `> 0` after two successful commits | warning | Check owner-lock and filesystem sync health. |

## 5. Indeterminate commit recovery

A rename or hard-link can publish a record before directory synchronization reports failure. Such a result is `IndeterminateCommit`, not a normal rejection.

Recovery procedure:

1. Stop automatic retry for the affected operation ID.
2. Reopen the same fleet/state root through the normal owner API.
3. Query the exact operation ID with `hepta-fleet-status`.
4. If the receipt exists and its semantic digest matches the intended operation, treat it as committed.
5. If the receipt is absent, retry through the original typed API with the same operation ID and unchanged payload.
6. If the ID exists with a different digest, quarantine the request as an identity conflict.

Receipt deduplication is bounded. Operators must retain external audit evidence longer than the in-process receipt-retention window when business policy requires indefinite replay detection.

## 6. Restart and recovery invariants

On open, the owner verifies:

- every generation filename and embedded generation agree;
- every retained generation content digest is valid;
- adjacent retained generations form a hash chain;
- hosts, observations and lease-ledger hosts agree exactly;
- active resource totals rebuild exactly and fit capacity;
- terminal history does not overlap active identities;
- operation IDs are unique inside the retained window;
- persisted authority witnesses validate structurally;
- the revocation snapshot has a bounded, internally valid shape.

Missing, partial, malformed or symlinked control state fails closed. The owner does not truncate unknown history or synthesize zero usage/capacity.

## 7. Revocation and partition behavior

A durable revocation snapshot stores signed update and acknowledgement evidence, never trust roots. At final use, the caller supplies independently pinned feed and node verifiers. Admission requires:

- a fresh authenticated update;
- the exact node in the enrolled set;
- an acknowledgement for the exact current update;
- `Ready` node state;
- unchanged revocation-snapshot digest across grant verification;
- current allocation, lease and host-generation fences.

Before the convergence deadline a missing node is `CatchingUp`; after the deadline it is `Quarantined`. An expired feed is `FeedStale`. All three states deny final use.

## 8. Forbidden operations

Do not:

- start `hepta-fleet-leased` or any second fleet writer;
- delete `owner.lock`, generation files or the workspace-reservation index to clear an error;
- edit JSON generations, digests, grant expiry, resource totals, authority witnesses or acknowledgements by hand;
- reduce a host generation or reuse an allocation/operation identity with different semantics;
- treat caller-supplied capacity as hardware discovery;
- bypass final-use grant and revocation verification;
- convert a queued request, authority check, acknowledgement or process start into a fabricated terminal success;
- claim target-host qualification from source tests or GitHub-hosted runners.

## 9. Qualification matrix

Repository-controlled qualification must cover:

- more than 16,384 sequential issue/terminal cycles without lifetime exhaustion;
- maximum simultaneous active-grant rejection;
- exact expiry boundary and capacity release;
- same-generation capacity refresh and shrink rejection;
- host-generation replacement and predecessor fencing;
- concurrent overlapping workspace registration;
- crash after registration rename, lifecycle hard-link and fleet-generation hard-link;
- durable reopen, index reconstruction and operation-ID reconciliation;
- revocation catch-up, quarantine, stale-feed and exact acknowledgement;
- final-use lease/host/revocation fences;
- long-history receipt and generation compaction;
- exact-source and synthetic-merge fmt, tests, strict clippy and supervisor product compilation.

Physical target qualification remains separate. It must run on the selected host with its actual filesystem, `/proc` semantics, pressure behavior, process supervisor, authority trust roots and partition controls. Until that evidence is attached to an exact commit, deployment qualification, independent acceptance and release remain false.
