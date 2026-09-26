# automation.taskflow schema v19 migration and recovery runbook

This runbook is normative for `automation_1.sqlite3`. It covers the v17–v19
convergence and does not authorize downgrade to an older writer.

## 1. Topology

| Version | Migration | Purpose |
|---|---|---|
| 17 | `0017_kernel_operation_dedupe.sql` | immutable destination-operation dedupe receipt |
| 18 | `0018_timer_lifecycle.sql` | timer writer epoch, active/draining/retired lifecycle and unresolved-dispatch drain guard |
| 19 | `0019_converged_owner_schema.sql` | convergence head after recognized displaced v17/v18 histories |

`reconcile_legacy_migration_ids` accepts only the reviewed legacy
version/checksum pairs embedded in source. It runs before the normal SQLx
migrator so SQLx still validates every resulting migration checksum. Unknown
history is corruption, not an invitation to relabel the database.

## 2. Preconditions

1. Stop new admissions with `quiesce_timer`.
2. Read `timer_status`; leased and uncertain counts must be zero before writer
   transfer. Pending occurrences may remain.
3. Record owner Agent ID, current writer epoch, exact binary commit and current
   schema.
4. Checkpoint WAL and copy the database plus required SQLite sidecars atomically.
5. Hash the completed checkpoint image.
6. Retain filesystem ownership, mode and mount identity.
7. Do not remove the source copy until target verification and rollback-window
   policy permit it.

## 3. In-place startup migration

1. Start exactly one schema-v19-capable writer while admission remains closed.
2. `AutomationStore::open` opens the durable evidence pool.
3. The loader recognizes only approved displaced migration IDs/checksums.
4. SQLx applies remaining migrations through 19.
5. Startup verifies owner metadata, required tables/indexes/triggers and writer
   epoch.
6. The database file is protected.
7. Agentd may advertise readiness only after the store and required control
   dependencies are ready.

Any error keeps automation unavailable. Do not edit `_sqlx_migrations` by hand.

## 4. Backup restore

Restore is allowed only to an isolated target:

- verify the checkpoint digest before open;
- verify the owner Agent ID;
- use a schema-v19-capable binary;
- keep admissions closed;
- verify migration convergence and integrity;
- reconcile historical unknown/admitted work before new admission;
- resume only after the target writer/fence tuple is accepted.

Restoring an older image over a live writer can resurrect completed work and is
forbidden.

## 5. Cross-host transfer

Create `AutomationCrossHostRecoveryManifestV1` from a draining, handoff-safe
source. The manifest binds:

- owner Agent ID;
- source and target host IDs;
- source epoch and required target epoch (`source + 1`);
- schema 19;
- pending occurrence count;
- SQLite checkpoint digest;
- external host-fence receipt digest;
- export time and canonical manifest digest.

The deployment controller must fence the source outside this SQLite database,
copy the exact checkpoint, establish the target epoch and call `admit_target`
with the observed tuple. A mismatch is `TimerFenced`. The manifest is not a
storage transport or distributed lock.

## 6. Rollback

Compatible rollback means launching another schema-v19-aware binary at a newer
writer epoch. It does **not** mean:

- opening the store with a v16/v17/v18-only binary;
- decrementing `automation_meta.schema_version`;
- deleting migration rows;
- restoring an old database over current state;
- clearing unknown dispatch evidence;
- reusing an old writer epoch.

If a new binary cannot start after an epoch advance, leave the store draining,
repair or deploy a compatible binary, and advance through the reviewed handoff
path. The fenced predecessor must not resume.

## 7. Required evidence

Retain:

- exact source commit and tree;
- migration command and test results;
- pre/post schema and integrity query results;
- owner Agent ID and writer epochs;
- checkpoint and manifest digests;
- unresolved-dispatch counts;
- target-host identity and external fence receipt;
- restore, DST and multi-scheduler qualification receipts.
