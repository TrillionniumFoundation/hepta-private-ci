# runtime.fleet operations for the SQLite candidate

Revision: 2026-09-28. Read [CURRENT_STATE.json](CURRENT_STATE.json) and [DURABLE_EXECUTION.md](DURABLE_EXECUTION.md) before interpreting readiness. These commands are implemented in `scripts/runtime_fleet_status.py`; they are not undocumented subcommands of the retired JSON-owner binary.

## Supported read-only surface

Python 3.11 or newer with SQLite `deserialize` support is required. The input must be a regular, checkpointed, quiescent schema-v2 snapshot supplied by the existing owner. A live database, WAL, SHM or recovery journal is rejected. Do not delete sidecars, copy only a live main database, or modify the source header to make diagnosis succeed. The command changes only its private in-memory copy and never opens the source through SQLite.

`--state-dir` names a snapshot directory containing `supervisor.sqlite3`, not permission to create a state directory. `--database` instead names the exact snapshot. Both are mutually exclusive. The explicit `--now-ms` is diagnostic time only and is never persisted or accepted as authority time. Exit 0 means the diagnostic command succeeded, not that a task is authorized or the product is accepted. Exit 2 means invalid arguments, snapshot, schema or unavailable diagnostic data.

```bash
python3 scripts/runtime_fleet_status.py status \
  --database "$FLEET_SNAPSHOT" --now-ms "$DIAGNOSTIC_NOW_MS" --format json

python3 scripts/runtime_fleet_status.py preflight \
  --database "$FLEET_SNAPSHOT" --now-ms "$DIAGNOSTIC_NOW_MS" \
  --profile "$FLEET_DEMAND_JSON" --format json

python3 scripts/runtime_fleet_status.py dry-run \
  --database "$FLEET_SNAPSHOT" --now-ms "$DIAGNOSTIC_NOW_MS" \
  --request "$FLEET_DEMAND_JSON" --format json
```

The profile/request has exactly these fields; all six nonnegative integral axes are mandatory and at least one must be positive:

```json
{
  "host_id": "selected-host",
  "resources": {
    "cpu_millis": 500,
    "memory_bytes": 268435456,
    "accelerator_millis": 0,
    "concurrent_turns": 1,
    "tool_processes": 2,
    "turn_queue_slots": 16
  }
}
```

`admissible_in_snapshot` means only that this demand fits the observed snapshot after existing reservations. It does not check a live generic-authority lease, produce a launch grant or mutate allocation state. Unknown/abbreviated flags, duplicate JSON keys, missing axes and `open --allow-create` are rejected. There is no implicit create, repair, migration, WAL checkpoint or live-authority fallback in this diagnostic interface.

## Recovery and capacity

A stop-requested or unbound prepared execution continues to reserve resources. Do not remove its hold or decrement its total manually to clear an alert. Route reconciliation through the process owner, establish producer fencing and real stop evidence, then perform the owner transaction. A missing PID alone is not stop evidence, and the current candidate still requires that product integration.

For temporary capacity pressure, stop new admissions while retaining lifecycle and recovery control. Treat indeterminate commits as a reconciliation requirement, never as permission to issue another launch. Corrupt lineage and accepted-clock rollback require owner quarantine rather than silent reinitialization. These are the required policy semantics; the Supervisor's complete policy consumption remains an open gate.

Before schema-v1 migration, drain and prove quiescence through the existing Supervisor. Preserve a coherent backup with its owner metadata and recovery obligations. Schema-v1 active grants cause open to fail. Even zero active rows do not prove old processes stopped. Do not approve a migration without the separate real-process and rollback rehearsal.

## Verification commands

```bash
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_runtime_fleet_status.py
PYTHONDONTWRITEBYTECODE=1 python3 scripts/test_runtime_fleet_qualify.py

# Run from the exact immutable checkout, with output outside the source tree.
python3 scripts/runtime_fleet_qualify.py \
  --source "$SOURCE_SHA" --base "$BASE_SHA" --lane exact-source \
  --output "$EXTERNAL_EVIDENCE_DIRECTORY"
```

The second Python suite injects deliberate command failures to test receipt honesty; it is not a Rust substitute. The candidate workflow constructs the fixed merge lane separately. Both lanes retain `--locked`, full command logs, exit codes and a clean-tree check. The current lockfile synchronization and Cargo execution gates are not waived by the successful Python tests.
