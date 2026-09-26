# runtime.fleet operations and recovery

This runbook applies to the supervisor-owned Fleet state implemented in `codex-rs/hepta-fleet` and composed by `hepta-supervisord`. It does not authorize a second writer, manual grant fabrication, frontier reconstruction or bypass of final-use admission.

## 1. Owner and paths

Canonical owner:

```text
hepta-supervisord
```

Canonical state:

```text
FLEET_ROOT/state/fleet-allocation-v1/
  owner.lock
  generation-NNNNNNNNNNNNNNNNNNNN.json
  latest-frontier-v1.json
```

Registry coordination state:

```text
FLEET_ROOT/state/registry-mutation.lock
FLEET_ROOT/state/workspace-reservations-v1.json
```

Only the existing supervisor owner may mutate these paths. `hepta-fleet-status` is read-only. `hepta-fleet-leased` must remain inert.

## 2. Product startup prerequisites

Required:

```sh
hepta-supervisord \
  --fleet-root /absolute/fleet-root \
  --fleet-start-trust-profile /absolute/fleet-start-trust-v1.json
```

The trust profile must be a regular, non-symlink JSON file, owner-controlled and immutable for the daemon generation. It must contain:

```json
{
  "schema_version": 1,
  "local_node_id": "node-a",
  "distributor_id": "revocation-distributor",
  "distributor_keys": [
    {
      "key_id": "distributor-v1",
      "verifying_key_hex": "<64 lowercase hex characters>",
      "not_before_authority_epoch": 1,
      "not_after_authority_epoch": 99
    }
  ],
  "nodes": [
    {
      "node_id": "node-a",
      "keys": [
        {
          "key_id": "node-a-v1",
          "verifying_key_hex": "<64 lowercase hex characters>",
          "not_before_authority_epoch": 1,
          "not_after_authority_epoch": 99
        }
      ]
    }
  ]
}
```

The local node must appear exactly once in the closed node set. Each key ID and public key is unique inside its ring. Epoch ranges are nonzero and ordered.

Linux host identity is normally derived from `/etc/machine-id`; host generation is boot-fenced by `/proc/sys/kernel/random/boot_id`. An override is accepted only when all three variables are supplied:

```text
HEPTA_FLEET_HOST_ID
HEPTA_FLEET_FAILURE_DOMAIN_ID
HEPTA_FLEET_HOST_GENERATION
```

## 3. Read-only health command

From `codex-rs`:

```sh
cargo run -p codex-hepta-fleet --bin hepta-fleet-status -- \
  --supervisor-state-root /absolute/fleet-root/state
```

The status command must not initialize missing state. A missing owner directory, missing immutable generation, malformed frontier or corrupt chain is an operational failure, not an empty healthy Fleet.

## 4. Metrics and alert thresholds

### `fleet_active_grants`

- **Warn:** at or above 80% of `MAX_ACTIVE_GRANTS`.
- **Critical:** at or above 95%.
- **Action:** identify top hosts/principals, verify expiry and terminal reconciliation, and prevent new nonessential admission before exhaustion.

### `fleet_expired_uncollected_grants`

- **Warn:** nonzero for more than one 20-second maintenance interval.
- **Critical:** increasing for three consecutive intervals.
- **Action:** inspect supervisor maintenance errors, run read-only status, then restart the same supervisor owner only after recording the exact state/frontier generation.

### `fleet_revoked_uncompacted_grants`

- **Warn:** above 75% of retained history.
- **Critical:** compaction backlog grows while terminal operations continue.
- **Action:** verify immutable-generation publication and external audit export before considering retention-policy changes.

### `fleet_reserved_resource{host,axis}` versus `fleet_observed_capacity{host,axis}`

- **Critical:** reservation exceeds observed capacity on any supported axis.
- **Action:** stop new admission, preserve evidence, and treat the state as invariant failure. Do not edit totals manually.

### `fleet_stale_hosts`

- **Warn:** any selected active host is stale.
- **Critical:** stale host still owns an active grant past its observation TTL.
- **Action:** verify capacity observer inputs and supervisor maintenance. New issue/renew must remain denied.

### mutation result counters

For `fleet_grant_issue_total{result}`, `fleet_grant_renew_total{result}` and `fleet_grant_revoke_total{result}`:

- **Warn:** rejected ratio above the reviewed workload baseline.
- **Critical:** any sustained `indeterminate` result.
- **Action:** use the exact operation-ID recovery procedure below; never mint a new ID to hide ambiguity.

### `fleet_revocation_lag_ms`

- **Warn:** above half the signed update lifetime or convergence SLA.
- **Critical:** at/after expiry or convergence deadline.
- **Action:** quarantine the node; do not start/adopt Agent or Matrix processes until a fresh exact signed update and acknowledgement restore `Ready`.

### `fleet_registry_conflict_total`

- **Warn:** any increase.
- **Action:** inspect competing registration/lifecycle operations and workspace identities. A conflict is not resolved by deleting the reservation index.

### `fleet_indeterminate_commit_total`

- **Critical:** any increase.
- **Action:** record operation ID, expected digest and reported generation; reopen and reconcile before retrying.

### `fleet_staging_debris`

- **Warn:** nonzero after owner startup.
- **Action:** allow the registry’s locked cleanup path to classify/remove stale staging. Do not delete a directory while another owner may be active.

### `fleet_compaction_backlog`

- **Warn:** more than the retained-generation target.
- **Critical:** monotonically increasing across successful maintenance cycles.
- **Action:** verify permissions, directory synchronization and filesystem errors. Never delete the newest generation or frontier.

## 5. Indeterminate commit recovery

Applies to Fleet generations, latest frontier, Agent registration and lifecycle publication.

1. Capture:
   - operation ID;
   - expected operation digest or input payload;
   - reported generation;
   - current candidate SHA;
   - error detail;
   - directory/file metadata without modifying it.
2. Stop automatic retry with a new identity.
3. Reopen the same state root through `DurableFleetOwner` or the normal supervisor startup path.
4. Require successful validation of:
   - retained generation digests and chain;
   - `latest-frontier-v1.json`;
   - workspace-reservation digest;
   - resource totals rebuilt from active grants.
5. Search the retained operation receipt by the exact operation ID.
6. If the receipt exists and the digest matches, treat it as committed.
7. If the same ID exists with another digest, quarantine and escalate.
8. If absent, retry once with the same ID and unchanged payload.
9. Preserve all evidence until external audit retention confirms ingestion.

A missing old operation ID after bounded receipt compaction is not proof that it never committed. Use the external audit archive and immutable state lineage.

## 6. Latest-frontier recovery

`latest-frontier-v1.json` is a non-rollback anchor.

Normal automatic recovery is allowed only when retained immutable generations prove a descendant chain from the pinned frontier. This covers a crash after generation publication and before the frontier rename becomes durable.

The following require quarantine and operator escalation:

- frontier generation greater than the latest retained generation;
- same generation with a different state digest;
- missing frontier beside generation greater than zero;
- latest generation deletion;
- an unverifiable retained gap;
- malformed, symlinked or non-regular frontier/state files.

Do **not** recreate or decrement the frontier manually. Do **not** copy an older generation over a newer one. Restore from an independently authenticated backup or rebuild through the approved owner migration procedure.

## 7. Capacity observer failure

The Linux observer requires readable, bounded physical files and valid numeric values. On pressure-limit exceedance the supervisor intentionally does not refresh the observation; it lets the previous observation expire.

Operator actions:

1. inspect `/proc/meminfo` and `/proc/pressure/memory` without substituting synthetic values;
2. verify cgroup/host profile assumptions for the selected deployment;
3. confirm the prior observation TTL;
4. keep new issue and renew paths denied while stale;
5. restore observation only through the normal owner command with a stable operation ID.

## 8. Revocation and partition recovery

A node may start/adopt processes only in `Ready` state. `CatchingUp`, `Quarantined` and `FeedStale` are deny states.

Recovery:

1. acquire a fresh distributor-signed update;
2. verify epoch/revision monotonicity and revoked-set semantics;
3. apply it through the authenticated revocation path;
4. produce the exact node-signed acknowledgement;
5. persist the update and acknowledgements in a new Fleet generation;
6. confirm the local node is `Ready` under the independently pinned trust profile;
7. only then resume process admission.

Never mark a node ready based on network reachability, unsigned state, another node’s acknowledgement or an expired update.

## 9. Host-generation change

A boot or selected-host generation change fences predecessor grants. The owner retires old-generation active grants and releases capacity through terminal records.

Before re-admission:

- obtain a fresh capacity observation for the new generation;
- issue a new authority-bound grant;
- ensure the Agent principal has exactly one active grant;
- restore a fresh revocation cut;
- let the process driver perform final-use admission.

Do not edit host generation in existing grants.

## 10. Workspace conflict recovery

When registration conflicts:

1. retain both requested Agent/workspace identities;
2. inspect `workspace-reservations-v1.json` through the registry API;
3. confirm whether paths are equal or ancestor/descendant;
4. choose a non-overlapping canonical workspace;
5. retry under a new operation only after the conflicting request is intentionally retired.

Do not delete the reservation index, rename Agent directories behind the registry, or weaken canonical/symlink validation.

## 11. Compaction and long-term audit

In-process history and operation receipts are bounded. Compaction preserves chained digests but not indefinite searchable identities. Before changing a retention ceiling or removing immutable generations:

- export the relevant generation, receipt and compaction-chain evidence to the approved external audit store;
- bind the export to exact source commit, state/frontier generation and content digests;
- verify restore/reconciliation on a non-production copy;
- obtain independent operator approval.

The current repository does not claim that external long-term audit retention is deployed.

## 12. Forbidden operations

Never:

- start a second Fleet writer;
- enable `hepta-fleet-leased` as a parallel owner;
- delete `owner.lock`, registry lock or reservation index to clear contention;
- edit generation JSON, frontier JSON, active grants, history, totals or signed revocation evidence;
- lower the frontier generation;
- delete the newest generation to “roll back”;
- treat a missing receipt after compaction as proof of nonexecution;
- mint a new operation ID after an indeterminate result;
- bypass the mandatory start trust profile;
- start/adopt a process while final-use admission rejects;
- replace physical capacity evidence with request-supplied values;
- mark a stale or partitioned node ready;
- claim selected-host, multi-node, deployment or release qualification from source tests alone.

## 13. Qualification commands

Focused source/merge qualification is defined by:

```text
.github/workflows/runtime-fleet-focused.yml
```

Selected-host qualification is defined by:

```text
.github/workflows/runtime-fleet-target-host.yml
```

The selected-host workflow must use the final candidate SHA, protected runner labels and an approved host profile. Store its command record, exact source identity, logs, metrics and evidence receipt. Independent acceptance remains separate.
