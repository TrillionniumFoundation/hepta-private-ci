# automation.taskflow migration, checkpoint and staged-restore runbook

Current declarations: [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md).
The historical filename is retained; the current native owner schema is **22**.
This procedure does not authorize old-binary rollback or another active writer.

## 1. Retained migration topology

| Version | Migration | Purpose |
|---|---|---|
| 17 | `0017_kernel_operation_dedupe.sql` | immutable destination-operation dedupe |
| 18 | `0018_timer_lifecycle.sql` | timer lifecycle, writer epoch and drain guard |
| 19 | `0019_converged_owner_schema.sql` | convergence of reviewed displaced histories |
| 20 | `0020_recovery_sweeps.sql` | permanent frozen-frontier recovery cursors |
| 21 | `0021_recovery_frontier_indexes.sql` | indexed sparse unknown frontier |
| 22 | `0022_durable_neural_circuit.sql` | durable activation intents, reservations, receipts, choices and checkpoints |

The original SQL/checksums at 17–20 are unchanged. `reconcile_legacy_migration_ids`
recognizes only reviewed historical version/checksum pairs before the normal SQLx
migrator. Unknown history rejects. Never hand-edit `_sqlx_migrations`, remove a
trigger, reset polling state or update `automation_meta` as a repair shortcut.

## 2. Preconditions and operational ownership

Use the existing authorized native owner management to quiesce the timer. Record
owner Agent, source binary commit/tree, current schema and writer epoch. For an
actual handoff, drain leased/uncertain work and obtain current independent source
fencing. The backup command does not perform or attest to either external fencing
or native lifecycle management. Pending and unresolved evidence must be retained.

Use private operator-owned directories and singly linked, private regular database
files. Refuse symlink/hard-link aliases, shared-writable output locations and reuse
of an existing backup/staging directory. Retain old source evidence until the
approved rollback/retention policy permits removal; this tool never deletes it.

## 3. Executable inspection and consistent backup

Set explicit deployment values; do not infer expected owner/schema from an
untrusted copied database. `SOURCE_SCHEMA` is the source's pre-migration schema,
for example 19, 21 or 22, not an instruction to rewrite it.

```sh
set -eu
: "${AUTOMATION_DB:?absolute path to the native automation_1.sqlite3}"
: "${OWNER_AGENT_ID:?canonical expected owner UUID}"
: "${SOURCE_SCHEMA:?expected pre-migration schema}"
: "${PRIVATE_BACKUP_PARENT:?existing private directory owned by the operator}"
: "${NEW_BACKUP_NAME:?new non-existing backup directory name}"

python3 scripts/automation_taskflow_checkpoint.py inspect \
  --database "$AUTOMATION_DB" --owner "$OWNER_AGENT_ID" --schema "$SOURCE_SCHEMA"

python3 scripts/automation_taskflow_checkpoint.py snapshot \
  --database "$AUTOMATION_DB" --owner "$OWNER_AGENT_ID" --schema "$SOURCE_SCHEMA" \
  --output "$PRIVATE_BACKUP_PARENT/$NEW_BACKUP_NAME" \
  --max-bytes 17179869184 --timeout 60
```

`snapshot` requires an observed draining timer. It opens one read-only SQLite
snapshot and uses the SQLite backup API, including committed WAL content. It does
not truncate/checkpoint the live source WAL or copy only the main file while
ignoring sidecars. Copying is page-bounded and hashing is chunked; all phases have
byte/time limits. The sealed output is a standalone SQLite file with no sidecars.

The bundle contains `automation_1.sqlite3`, `checkpoint.json`, an informational
`INCOMPLETE` file and the final `COMMITTED` digest marker. Only successful marker,
manifest digest, byte digest and inspection validation establish a usable local
backup. An incomplete directory is retained for diagnosis and is never reused as
an apparently successful backup. Record the returned manifest digest in an
independent evidence location, not only beside the database.

## 4. Executable verification and create-only staged restore

```sh
set -eu
: "${BACKUP_BUNDLE:?absolute private backup bundle directory}"
: "${RETAINED_MANIFEST_SHA256:?independently retained exact digest}"
: "${NEW_STAGE_DIRECTORY:?non-existing directory beneath a private operator parent}"

python3 scripts/automation_taskflow_checkpoint.py verify \
  --bundle "$BACKUP_BUNDLE" --manifest-sha256 "$RETAINED_MANIFEST_SHA256" \
  --max-bytes 17179869184 --timeout 60

python3 scripts/automation_taskflow_checkpoint.py restore-stage \
  --bundle "$BACKUP_BUNDLE" --manifest-sha256 "$RETAINED_MANIFEST_SHA256" \
  --output "$NEW_STAGE_DIRECTORY" --max-bytes 17179869184 --timeout 60
```

The stage keeps the source epoch/schema unchanged and writes `STAGED.json` only
after exact copied-byte verification. It is not a live Agent layout, ready signal,
writer lease or accepted target. Both commands reject a missing commit marker,
changed payload, wrong owner/schema inventory, failed/incomplete migration ledger,
sidecar-bearing sealed checkpoint, permission alias or existing output target.

A Python inspection identifies its own SQLite implementation, not native Agentd's.
It verifies SQLite integrity, owner/lifecycle and bounded inventory; it does not
replace all native schema-object, occurrence, TaskFlow or final-use checks.

## 5. Native migration and target admission

After independent source fencing and the existing authorized controller's native
handoff procedure, open the staged compatible database with the exact selected
schema-22-capable native owner while admissions remain closed. Native SQLx must
validate/reconcile only known histories, apply outstanding migrations and execute
all owner/schema/replay checks before readiness. Reconcile historical unknown or
admitted work before permitting fresh admission.

The Python tool deliberately has no `migrate`, epoch-update, force-restore, start,
resume or promote command. These actions belong to the existing native owner and
external controller. The real cross-host controller/transport integration and its
two-host execution qualification remain unfinished; the backup tool is not a
replacement implementation of that authority boundary.

## 6. Cross-host tuple and failure handling

The existing manifest binds owner, distinct source/target hosts, source epoch,
required next epoch, current schema, pending count, checkpoint and external fence
digests. The controller must verify the external fence independently, transfer the
exact checkpoint and invoke target admission with values actually read from the
copied native store. Rehashing a caller-authored manifest does not prove physical
source isolation. A wrong owner, epoch, host or checkpoint rejects.

If native migration, epoch advance or consumer installation fails, keep admission
closed and preserve the staged/source evidence. Do not resume a fenced predecessor.
Use a compatible repaired binary and the reviewed monotone handoff path. Unknown
or unacknowledged effects never become retryable merely because restore failed.

## 7. Compatible rollback and required evidence

Rollback is another compatible writer generation over the current history. Never
open schema 22 with an older incompatible binary, lower metadata/epoch, delete
migration or sweep rows, clear unknown dispatches or overwrite a live owner with
an earlier checkpoint. Staged restore is not historical-state rollback authority.

Retain source/candidate commit/tree, actual command/exit/log receipts, native
migration results, checkpoint and independently retained manifest digests, owner,
pre/post epochs, unresolved-work counts, target host/configuration and external
fence evidence. Add actual native DST, restore, multi-scheduler and long-retention
capacity results before selected-host operational acceptance. The Python tests
cover WAL snapshots, create-only restore, a child-process cut before the commit
marker and 100,000 retained events; they are not native owner or power-loss proof.


## 8. Bounded native startup audit

The native opener verifies definitions, runs and each immutable event chain in
fixed-size keyset pages. All TaskFlow pages share one read transaction, preserving
a coherent snapshot while bounding materialized rows. This does not shorten the
complete audit or waive corruption checks. Record retained counts, wall time, RSS,
SQLite I/O/busy work and crash/reopen outcomes before operational acceptance.
