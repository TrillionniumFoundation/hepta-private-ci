# runtime.fleet operations and recovery

This runbook applies to the supervisor-owned Fleet state implemented in `codex-rs/hepta-fleet` and composed by `hepta-supervisord`. It does not authorize a second writer, manual grant fabrication, frontier reconstruction or bypass of final-use admission. Read `EXECUTION_BINDING.md` with this runbook: complete selected-host containment/quiescence-to-release composition and final-candidate execution acceptance are not yet established.

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

Only the existing supervisor owner may mutate these paths. `hepta-fleet-status` is read-only. `hepta-fleet-leased` must remain inert. State generations include boot incarnations and execution holds as well as active authorization leases.

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

The local node must appear exactly once in the closed node set. Each key ID and public key is unique inside its ring. Epoch ranges are nonzero and ordered. The example is a schema illustration; placeholder public keys are not executable credentials.

Linux host identity is normally derived from `/etc/machine-id`. `/proc/sys/kernel/random/boot_id` provides an opaque boot identity, not an ordered generation. The durable owner assigns and persists a separate monotonic incarnation. An override is accepted only when all three variables are supplied and agree with the durable boot fence:

```text
HEPTA_FLEET_HOST_ID
HEPTA_FLEET_FAILURE_DOMAIN_ID
HEPTA_FLEET_HOST_GENERATION
```

For the native physical resource profile, set `HEPTA_FLEET_RESOURCE_MAPPING_PROFILE` to a reviewed `ResourceMappingPolicyV1` JSON file. The file must be absolute, physical, outside Fleet state, root/current-owner controlled, not group/world writable, bounded to one MiB, and fixed for one driver lifetime. No CPU coefficient is inferred from an allocation grant. Logical manifest requirements without a compatible mapping do not become physical requirements automatically.

Agentd and Matrixd are separate execution scopes in the current wrapper. The allocation must cover the sum of all retained mapped process requirements. Do not copy the full grant into each process context or assume that one grant can be spent independently twice. Mapping and allocation creation must be qualified together before deployment.

## 3. Read-only health command

Using the installed binary:

```sh
hepta-fleet-status status \
  --supervisor-state-root /absolute/fleet-root/state \
  --format json
```

Equivalent development invocation from `codex-rs`:

```sh
cargo run --locked -p codex-hepta-fleet --bin hepta-fleet-status -- \
  status --supervisor-state-root /absolute/fleet-root/state --format json
```

A specific retained operation can be queried with:

```sh
hepta-fleet-status status \
  --supervisor-state-root /absolute/fleet-root/state \
  --format json --operation-id supervisor-expiry-slot-123
```

The operation ID above is illustrative, not evidence that such an operation exists. `--fail-on-alert` requests a nonzero result when the implemented alert evaluation reports an alert.

The status binary must not initialize missing state, create locks, seal a frontier or clean staging. The `cargo run` wrapper may build into its Cargo target directory; that is separate from the status binary's no-write contract for Fleet state. A missing owner directory, missing generation, unsealed/malformed frontier or corrupt chain is an operational failure, not an empty healthy Fleet. Unavailable/compacted operation history is not proof of noncommit.

The implemented status interface is JSON-only. Unknown/duplicate options, missing values and non-absolute state roots are rejected. `preflight`, `dry-run`, `open --allow-create`, the retired telemetry-fetch mode and Prometheus formatting are not implemented status capabilities and must fail, never reinterpret option tokens as journal filenames. `codex-rs/hepta-fleet/tests/status_readonly_cli.rs` contains the executable CLI regression target; source presence is not a claim that it passed on the final candidate.

## 4. Metrics and alert thresholds

Standalone status reads authoritative snapshots, not another process's volatile counters. A process-local counter unavailable to the snapshot reader must be reported as unavailable/null, not zero. The following operational metric vocabulary includes live-owner diagnostics as well as snapshot fields; it is not a claim that every metric has a deployed exporter.

### `fleet_active_grants`

- **Warn:** at or above 80% of `MAX_ACTIVE_GRANTS`.
- **Critical:** at or above 95%.
- **Action:** identify top hosts/principals, verify expiry and terminal reconciliation, and prevent new nonessential admission before exhaustion.

### `fleet_expired_uncollected_grants`

- **Warn:** nonzero for more than one 20-second maintenance interval.
- **Critical:** increasing for three consecutive intervals.
- **Action:** inspect supervisor maintenance errors, run read-only status, then restart the same supervisor owner only after recording the exact state/frontier generation. Authorization expiry does not justify deleting an execution hold.

### `fleet_revoked_uncompacted_grants`

- **Warn:** above 75% of retained history.
- **Critical:** compaction backlog grows while terminal operations continue.
- **Action:** verify immutable-generation publication and external audit export before considering retention-policy changes.

### `fleet_reserved_resource{host,axis}` versus `fleet_observed_capacity{host,axis}`

- **Critical:** committed reservations exceed persisted observed capacity on any supported axis.
- **Action:** stop new admission, preserve evidence, and treat a persisted mismatch as an invariant failure. Do not edit totals manually. A fresh attempted capacity shrink rejected before publication is instead a capacity-degradation event; it does not authorize overwriting the old observation or deleting physical pins.

### `fleet_stale_hosts`

- **Warn:** any selected active host is stale.
- **Critical:** stale host still owns an active grant past its observation TTL.
- **Action:** verify capacity observer inputs and supervisor maintenance. New issue/renew must remain denied by freshness checks.

### mutation result counters

For `fleet_grant_issue_total{result}`, `fleet_grant_renew_total{result}` and `fleet_grant_revoke_total{result}`:

- **Warn:** rejected ratio above the reviewed workload baseline.
- **Critical:** any sustained `indeterminate` result.
- **Action:** use the exact operation-ID recovery procedure below; never mint a new ID to hide ambiguity. Do not estimate a ratio from unavailable/null counters.

### `fleet_revocation_lag_ms`

- **Warn:** above half the signed update lifetime or convergence SLA.
- **Critical:** at/after expiry or convergence deadline.
- **Action:** quarantine the node; do not start/adopt Agent or Matrix processes until a fresh exact signed update and acknowledgement restore `Ready`.

### `fleet_registry_conflict_total`

- **Warn:** any observed increase in the live-owner diagnostic.
- **Action:** inspect competing registration/lifecycle operations and workspace identities. A conflict is not resolved by deleting the reservation index.

### `fleet_indeterminate_commit_total`

- **Critical:** any observed increase.
- **Action:** record operation ID, expected digest and reported generation; reopen and reconcile before retrying.

### `fleet_staging_debris`

- **Warn:** nonzero after owner startup.
- **Action:** allow the registry's locked cleanup path to classify/remove stale staging. Do not delete a directory while another owner may be active; read-only status performs no cleanup.

### `fleet_compaction_backlog`

- **Warn:** more than the retained-generation target.
- **Critical:** monotonically increasing across successful maintenance cycles.
- **Action:** verify permissions, directory synchronization and filesystem errors. Never delete the newest generation or frontier.

## 5. Indeterminate commit recovery

Applies to Fleet generations, latest frontier, Agent registration and lifecycle publication.

1. Capture operation ID, expected digest/payload, reported generation, candidate SHA, error details and non-mutating directory/file metadata.
2. Stop automatic retry with a new identity.
3. Reopen the same state root through the existing `DurableFleetOwner` writer or normal supervisor recovery path. This is a recovery mutation path, not the status command.
4. Require validation of retained generation digests/chain, the latest frontier, workspace-reservation digest and resource totals rebuilt from the union of active grants and retained physical execution holds.
5. Search the retained operation receipt by the exact operation ID.
6. If the receipt exists and the digest matches, treat that operation as committed, without inferring that a subsequent process effect completed.
7. If the same ID exists with another digest, quarantine and escalate.
8. Retry the same ID and unchanged payload only when noncommit can be established within retained history or the external audit archive. Missing compacted history is an unresolved result.
9. Preserve evidence until external audit retention confirms ingestion.

A prepared execution intent before a lost or ambiguous spawn result must stay pinned. The library selected-host quiescence probe may reconcile an allocation only after all retained execution scopes are proven empty. A successful kill, missing PID or parent wait alone is insufficient for a product process tree. No status subcommand clears these holds.

## 6. Latest-frontier recovery

`latest-frontier-v1.json` is a non-rollback anchor.

Normal writer recovery is allowed only when retained generations prove a descendant chain from the pinned frontier. This covers a crash after generation publication and before the frontier rename becomes durable. Read-only status reports that condition without sealing it.

The following require quarantine and operator escalation:

- frontier generation greater than the latest retained generation;
- same generation with a different state digest;
- missing frontier beside generation greater than zero;
- latest generation deletion;
- an unverifiable retained gap;
- malformed, symlinked or non-regular frontier/state files.

Do **not** recreate or decrement the frontier manually. Do **not** copy an older generation over a newer one. Restore from an independently authenticated backup or rebuild through the approved owner migration procedure.

## 7. Capacity observer failure

The Linux observer requires readable, bounded physical files and valid numeric values. On pressure-limit exceedance or ordinary capacity shrink below reservations, maintenance does not refresh the observation and does not terminate Supervisor solely for that capacity event. Corruption, identity failure and indeterminate durability errors remain failures, not ordinary pressure.

Before a new native process intent is prepared, the Unix wrapper independently reads current capacity/pressure and compares it with committed physical reservations. An insufficient or unavailable observation rejects that new effect without creating an intent. Existing stop/adoption management is not granted new authority by this behavior. The source does not claim kernel hard limits, globally persisted pressure gating of all grant APIs or complete automatic physical reclamation.

Operator actions:

1. inspect `/proc/meminfo` and `/proc/pressure/memory` without substituting synthetic values;
2. verify cgroup/host profile assumptions and mapping policy for the selected deployment;
3. confirm the prior observation TTL and retained execution holds;
4. keep issue/renew denied while stale and verify that insufficient capacity denies new physical starts;
5. restore observation only through the normal owner command with a stable operation ID;
6. never free capacity by deleting holds belonging to apparently stopped parents.

## 8. Revocation and partition recovery

A node may start/adopt processes only in `Ready` state. `CatchingUp`, `Quarantined` and `FeedStale` are deny states.

Recovery:

1. acquire a fresh distributor-signed update;
2. verify epoch/revision monotonicity and revoked-set semantics;
3. apply it through the authenticated revocation path;
4. produce the exact node-signed acknowledgement;
5. persist the update and acknowledgements in a new Fleet generation;
6. confirm the local node is `Ready` under the independently pinned trust profile;
7. only then resume process admission, subject to current resource and retained-intent checks.

The process wrapper requests stop when authority revalidation rejects and escalates after its grace period while the process is still polled. This is not a quiescence acknowledgement and does not release capacity. Never mark a node ready based on network reachability, unsigned state, another node's acknowledgement or an expired update.

## 9. Host-generation change

A new boot or selected-host incarnation fences predecessor authorization. The owner retires old-generation active grants but retains physical execution holds. Automatic release based on a complete old-boot/containment proof is still a product composition gate; a changed numeric generation alone does not erase holds.

Before re-admission:

- reconcile the actual execution scopes and retained intents through the approved selected-host owner;
- obtain a fresh capacity observation for the new incarnation;
- issue a new authority-bound grant that covers aggregate mapped requirements;
- ensure the Agent principal has exactly one current unrevoked, unexpired grant;
- restore a fresh revocation cut;
- let the process driver perform final-use admission.

Do not edit host generation in existing grants, order boot IDs numerically, or fall back to wall-clock time as an incarnation protocol.

## 10. Workspace conflict recovery

When registration conflicts:

1. retain both requested Agent/workspace identities;
2. inspect `workspace-reservations-v1.json` through the registry API;
3. confirm whether paths are equal or ancestor/descendant;
4. choose a non-overlapping canonical workspace;
5. retry under a new operation only after the conflicting request is intentionally retired.

Do not delete the reservation index, rename Agent directories behind the registry, or weaken canonical/symlink validation. Reading one manifest through `AgentManifest::read_registered` does not perform registry repair or migrate unrelated entries.

## 11. Compaction and long-term audit

In-process history and operation receipts are bounded. Compaction preserves chained digests but not indefinite searchable identities. Before changing a retention ceiling or removing immutable generations:

- export the relevant generation, receipt and compaction-chain evidence to the approved external audit store;
- bind the export to exact source commit, state/frontier generation and content digests;
- verify restore/reconciliation on a non-production copy;
- obtain independent operator approval.

The repository does not claim external long-term audit retention is deployed. Execution pins are not terminal-history debris and may not be removed to improve snapshot size or avoid aggregate budget checks.

## 12. Forbidden operations

Never:

- start a second Fleet writer or enable `hepta-fleet-leased` as a parallel owner;
- delete owner/registry locks or reservation indexes to clear contention;
- edit generation/frontier JSON, grants, holds, totals or signed revocation evidence;
- lower a frontier or delete the newest generation to roll back;
- treat a missing receipt after compaction as proof of nonexecution;
- mint a new effect/operation ID to hide an indeterminate result;
- bypass the mandatory start trust profile or fabricate a matching adoption intent;
- start/adopt while final-use admission rejects;
- replace physical capacity evidence with request-supplied values;
- derive actual process requirements by copying the grant under test;
- equate parent exit, a signal or lease expiry with complete physical quiescence;
- mark a stale or partitioned node ready;
- claim selected-host, multi-node, deployment or release qualification from source tests alone.

## 13. Qualification commands and evidence

Focused source/merge qualification is defined by `.github/workflows/runtime-fleet-focused.yml`. From a clean complete candidate checkout, a local exact-source attempt uses:

```sh
SOURCE="$(git rev-parse HEAD)"
BASE="a126987b84737dbc2ee2592442a314117bddb4a2"
EVIDENCE="$(mktemp -d)"
python3 scripts/runtime_fleet_qualify.py \
  --kind exact-source --source "$SOURCE" --base "$BASE" \
  --output "$EVIDENCE/exact-source"
```

The script requires full immutable commits, a clean tree, a fresh evidence directory outside source, the pinned Rust toolchain and the complete workspace/dependencies. It never formats/repairs source or rewrites success claims. Each receipt binds source/tree, tested commit/tree, base/tree, runner/workflow provenance, full tracked source archive, commands, exit codes and log digests. A synthetic-merge receipt additionally requires exact ordered parents and equality with the deterministic `git merge-tree` result. A commit with correct parents and fabricated content is rejected.

Qualification mechanism regressions run separately:

```sh
python3 -B -m unittest discover \
  -s scripts -p test_runtime_fleet_qualify.py -v
```

Those Python fixture tests do not run the Fleet Rust suite or establish product execution. The local evidence record explicitly distinguishes their result from outstanding Cargo, Clippy, merge and host qualification.

Selected-host qualification is defined by `.github/workflows/runtime-fleet-target-host.yml` and must use the final candidate SHA, protected runner labels and an approved host profile. Retain command records, source identity, logs, metrics and receipts. A queued/cancelled run, historical green run or source-only archive is not acceptance. Independent operator acceptance and release authority remain separate.
