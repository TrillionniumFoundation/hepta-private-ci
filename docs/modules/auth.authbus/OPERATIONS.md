# auth.authbus operations

Status: production runbook contract

## Supported deployment topology

`auth.authbus` is a single-active-owner authority. One named process owns one
SQLite database, one owner-lock file and one external checkpoint. Standby
processes may exist, but they must fail to acquire the owner lock while the active
owner is alive and may start only after the previous lock is released.

The production composition must name:

- the process that constructs `AuthBusAuthorityHost`;
- the database and checkpoint paths;
- the owner ID and service identity;
- the trusted-time issuer and signer custody location;
- the settlement issuer and signer custody location;
- the message issuer registries used by Agentd/evidence ingress;
- the only processes permitted to replace those registries;
- the metrics exporter, dashboard and paging route.

## Required filesystem layout

Use separate private directories for database/owner state and the external
checkpoint. Both directories must be canonical absolute paths and owned by the
service account.

```text
/var/lib/hepta/authbus/                 mode 0700
  authority.sqlite
  .authority.sqlite.authbus-owner.lock mode 0600
/var/lib/hepta/authbus-witness/         mode 0700
  authority-checkpoint.json            mode 0600
/etc/hepta/authbus/                     mode 0700
  message-issuers.json                  mode 0600
```

The checkpoint directory must not be the database directory. Symlinks, multiple
hard links, group/world-writable files and foreign ownership are rejected.

## Startup sequence

1. Resolve canonical absolute paths and verify service-account ownership.
2. Acquire the exclusive owner lock before opening SQLite or reading the
   checkpoint.
3. Open SQLite with foreign keys enabled, WAL mode and full synchronous writes.
4. Run pre-migration integrity checks, migrations, schema verification,
   post-migration `quick_check` and `foreign_key_check`.
5. Read and compare the external checkpoint. Bootstrap an absent checkpoint only
   for a new authority with no prior witness and while owner-fenced.
6. Reconcile crash-left `dispatch_attempted` state in bounded batches.
7. Run a bounded expired-reservation sweep until the startup budget is exhausted.
8. Publish initial health and backlog metrics.
9. Admit product traffic only after all preceding steps succeed.

Any failure before step 9 keeps the service unready.

## Periodic authority work

A single authority worker owns maintenance. It must not create a second host or
raw writer. Every tick uses a fresh verified trusted-time sample and performs, in
order:

1. checkpoint synchronization;
2. bounded restart/recovery reconciliation;
3. bounded expired-reservation sweep;
4. bounded terminal-reservation compaction when retention permits;
5. capacity/backlog sampling and alerts;
6. publication of a maintenance receipt.

Recommended default cadence is 30 seconds, with jitter below 10 percent. The
worker must stop admission when checkpoint synchronization or authoritative
integrity checks fail. It may continue reporting diagnostics while fail-closed.

## Admission and dispatch

- Resolve issuer registrations from the durable authority registry; never accept
  a caller-created trusted registration.
- Revalidate policy and trusted time at final use.
- Persist `dispatch_attempted` before invoking an external provider.
- Treat transport timeout, worker death and unknown provider outcome as
  indeterminate. Do not release quota from an ambiguous outcome.
- Acknowledge or settle only with exact operation/reservation binding and valid
  authority evidence.

## Capacity controls

Operators must configure and monitor:

- total active reservation cap;
- per-principal active reservation cap;
- maximum policies, quotas and issuer epochs;
- expiry-sweep batch size and backlog limit;
- terminal retention and compaction batch size;
- database-size warning and hard-stop thresholds;
- outbox retry and maximum-age thresholds.

When the active-reservation or storage hard limit is reached, reject new work
without mutating existing reservations. Capacity pressure never permits bypassing
issuer, policy, time or checkpoint validation.

## Planned shutdown

1. Mark the service unready and stop new admission.
2. Allow in-flight calls to reach a durable terminal or indeterminate state.
3. Run one final maintenance tick.
4. Synchronize and verify the checkpoint.
5. Flush telemetry and the shutdown receipt.
6. Drop the host, releasing the owner lock.

Do not delete the owner-lock file as a normal shutdown step. The lock is attached
to the open file description; deleting the path while a process is alive can
create a second lock inode and defeat fencing.

## Operator commands

The production wrapper should expose read-only commands equivalent to:

```text
authbus inspect --database ... --checkpoint ...
authbus verify-integrity --offline
authbus maintenance-once --limit 256
authbus checkpoint-status
authbus reservation-status <id>
authbus issuer-status <purpose> <issuer-id> <epoch>
```

Offline commands must acquire the same owner lock. Repair or mutation commands
require a separate administrative capability and an auditable two-person
procedure; they must not reuse normal product credentials.

## Escalation conditions

Immediately page the authority on-call for:

- owner-lock collision on the designated active host;
- checkpoint rollback/digest mismatch or dirty duration above threshold;
- SQLite integrity/schema failure;
- trusted-time rollback or expired attestation;
- any indeterminate reservation older than the reconciliation SLO;
- expired-reservation backlog that grows for three maintenance ticks;
- unexpected issuer-purpose, epoch or signature-failure surge;
- inability to fsync the database, checkpoint file or checkpoint directory.

Follow `RECOVERY.md`; do not create a replacement checkpoint or release quota by
manual SQL without the documented evidence and approval procedure.
