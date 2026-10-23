# kernel.evidence operations runbook

This runbook covers repository-supplied operational surfaces. It does not
activate production, enroll an external backend, create signing authority or
advance any acceptance/release gate.

## 1. Read-only external frontier capacity

Use the dedicated binary rather than opening journal/index files manually:

```bash
cd codex-rs
cargo run --locked -p codex-hepta-evidence \
  --bin kernel_evidence_frontier_status -- \
  --backend-root /absolute/external/kernel-evidence \
  --backend-identity-sha256 <64-lowercase-hex> \
  --local-rollback-root /absolute/local/agent-home \
  --store-id <stable-store-id>
```

All four flags are required exactly once. Both roots must be absolute. The
backend open still enforces canonical paths, private owner-controlled
permissions, stable backend identity and a rollback domain distinct from the
local root. The command neither claims the SQLite publication owner nor
prepares, dispatches, acknowledges, activates or releases anything.

The command emits one canonical JSON object with:

- `latestGeneration`;
- `segmentCount`;
- archived and active record/byte counts;
- active record/byte limits and remaining headroom;
- `alert`, one of `healthy`, `active_near_rollover` or
  `segment_count_elevated`.

`active_near_rollover` is an early operational signal, not corruption. Normal
publishing should seal the active tail and continue. Repeated failure to roll,
zero headroom, an identity error or a corrupt result is fail-closed and must not
be repaired by deleting history. `segment_count_elevated` requires retention,
filesystem and capacity review; normal operation never truncates authenticated
segments to clear the alert.

## 2. Publication workflow

Publication is explicit and owner controlled:

1. run the Agentd publication command with a private `prepare` request;
2. retain the returned immutable batch identity and exact snapshot;
3. create the externally signed next frontier and real backup/restore witness;
4. run the `publish` request for the same batch;
5. retain the durable backend acknowledgement and local acknowledgement.

The writer stores the operation identity before external CAS. An uncertain
backend result leaves the same batch `dispatching` or `indeterminate`; a new
owner may reconcile that batch only after acquiring the next durable owner
generation. Never prepare a replacement batch or reinterpret an error as
success while an earlier batch remains unresolved.

## 3. Recovery decisions

For one unresolved batch, compare authenticated external latest state with the
durable preparation:

- exact proposed frontier present: recover and re-fsync its durable
  acknowledgement, then finish local acknowledgement;
- exact predecessor still latest: revalidate current controls and retry the same
  batch;
- any other generation/digest/backend: stop with conflict and preserve all
  evidence for operator review.

A latest read alone is not a durable acknowledgement. Recovery revalidates the
stored journal or immutable segment, file and directory durability before
returning success.

## 4. Startup and resource limits

Production startup performs read-only migration/schema/integrity preflight
before opening the restricted runtime connection. Before canonical
qualification-row reconstruction materializes the table, aggregate preflight
rejects more than 1,000,000 rows, more than 512 MiB of canonical envelope data,
a receipt above 256 KiB or an authentication signature outside the fixed
64-byte width.

Recovery/provenance computation itself uses keyset pages under one SQLite read
transaction. Product query pages are separately bounded and verification
returns a compact summary instead of serializing an unbounded evidence vector.

## 5. Backup and restore

A backup receipt is admissible only when it binds the real backup object bytes,
object length, storage backend, accepted generation, governed source/build
identity and a successful restore witness. The restore witness binds the
restored object and authenticated snapshot plus SQLite integrity evidence.

Repository tests and validators do not prove the selected platform's fsync,
coherent-lock, power-loss, RPO or RTO behavior. Retain target-host receipts for
backup publication, restore, rollback rejection and measured objectives.

## 6. Safe retained diagnostics

Retain digests and bounded metadata for:

- current mode, store/backend identity and accepted generation;
- source/tree, qualification artifact and executable identity;
- signer/trust generations and revocation state;
- pending/unresolved publication batch identity and owner generation;
- segment/record/byte capacity and alert;
- recovery-required reason class;
- backup/restore witness identity and timing.

Do not log raw private keys, credentials, unredacted evidence payloads or
secret-bearing control files.
