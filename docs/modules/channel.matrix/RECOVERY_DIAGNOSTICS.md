# Recovery isolation and operational diagnostics

## Owner and identities

Migration 13 adds scheduling rows to the existing `MatrixDurableStore`; it is not
another sender, inbox, authorization source or execution runtime. Each row keeps
one existing event identity, monotone attempt count, start/due times, disposition
and a bounded reason code. It carries no message payload or remote error prose.
The current visible-inbox/actionable-dispatch views still enforce room fences.
A delayed or quarantined event remains pending and its client id never changes.

## Scheduling and cancellation contract

Default recovery policy: at most 64 selected IDs and a 250 ms cooperative pass
budget. Public policy bounds are 1–256 IDs and a positive budget up to five
seconds. This is NOT a hard per-request latency bound. A bridge call already in
flight finishes according to its existing timeout/uncertainty contract. Only
semaphore acquisition is cancelled at the pass deadline. Work yields the gate
between events, ordering unattempted events ahead of recently attempted events.
A running row is scheduled 30 seconds ahead before the bridge call; abrupt task
loss therefore retains the original identity for later reconciliation.

Dependency failures use bounded exponential backoff (2–64 seconds). Identity
conflicts, unrecoverable binding/protocol mismatches and invalid bridge inputs
are quarantined. Corrupt/unavailable persistence, failed disposition writes,
owner lifecycle errors and local invariant failures stop the owner. Store
failure is never relabelled as a successfully isolated event. There is no direct
SQL/manual unquarantine or delete procedure: remediation must preserve identity
and requires a separately reviewed authenticated owner operation.

Known `(thread_id, turn_id)` output bypasses admission recovery and is serialized
only against other output projections. A missing association consults only
pending existing dispatches for that exact current thread, using `ReconcileOnly`
so the output path cannot create new Agent work. If matching candidates exist
but cannot produce the association, `ProjectionPending` stops that generation;
this does not prove replay/delivery. A durable deferred-output/replay profile is
still needed before claiming availability under persistent association loss.

## Input compatibility

For m.text, display-only extension fields (including HTML fallback metadata) do
not block the plain text body. They are not forwarded as Agent inputs or treated
as authority. `m.mentions` remains typed and strict. Plain replies and thread
relations are accepted; replacement/annotation relations are not admitted as
new commands. Empty, malformed, wrong event/message type and unsupported
relation cases have distinct process-lifetime numeric counters. No raw input or
unknown-field content enters metrics labels.

## Operations

`MatrixRuntime::operational_metrics()` emits identity-free cumulative admission
and projection gate acquisition, wait and hold nanosecond sum/max counters,
plus unsupported-input reason counts. The runner logs a snapshot on its existing
inbox tick every ten seconds or on fatal recovery errors. These are process
lifetime observations, not p95/p99 measurements or durable audit records. An
in-flight slow call can delay a log emission; ten seconds is not an export SLA.

Run `python3 scripts/channel_matrix_diagnostics.py --database <canonical-owner-db>`
for a bounded read-only transactional SQLite snapshot. `--event <event-id>`
explains the exact pending event's attempts, disposition, reason and due time;
`--transaction <stable-txn-id>` explains outbound reconciliation. Neither selector
is echoed as a metric label. `--format prometheus` emits bounded labels only.
`--check` exits 1 for warnings and 2 for critical/unavailable diagnostics.

The snapshot includes oldest visible pending inbox and oldest indeterminate
transaction ages, pending recovery states/reasons, lifetime recovery attempts,
capacity, expired claims and sync checkpoint age. An absent age is unavailable,
not zero. A future durable timestamp is a clock diagnostic error. The reader
uses mode=ro, query_only and a query budget, without immutable=1 (which could
ignore an active WAL). It is not the native store-open integrity proof or current
live authority information. Quarantine suggests exact binding inspection;
unknown remote effects suggest authenticated reconciliation under the SAME txn.

## Evidence boundaries

Python SQLite/receipt tests prove their narrow executed scope only. The closed
MATRIX-Q01–Q29 registry requires every test-bearing native scenario—including
recovery tests Q24–Q29—to execute on the actual final source and deterministic
merge candidates. The generated ledger binds each testcase result to the exact
candidate, source snapshot, command receipt and JUnit digest. Real encrypted
rotation, protected restore, sustained capacity, process crash/replay and
independent operator/security acceptance remain gates.
No tests are disabled, skipped or replaced by receipt-generator self-approval.
