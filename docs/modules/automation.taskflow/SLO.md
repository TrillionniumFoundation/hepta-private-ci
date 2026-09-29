# automation.taskflow runtime SLO contract

Current source and evidence states: [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md).
These schema-22 objectives do not weaken durable V1 correctness and are not
measurements of an activated deployment.

| Signal | Default objective / bound | Breach or boundary |
|---|---:|---|
| App Server admission response | 5 s | after possible contact preserve unknown; never infer absence |
| Configured external provider response | exact host configuration, at most its accepted 30 s limit | separate from scheduler timeout; retain ambiguous attempt |
| Unknown-result reconciliation age | 5 min objective | alert and retain quarantine, not blind redispatch |
| Scheduler lease | 30 s | expiry alone never proves absence |
| Writer-epoch fence propagation | 1 s objective | retain rejection and stop new owner work |
| Recovery keys reserved per cycle | 8 | independent persistent sweeps; bounded exact-ID reads |
| Terminal-observation allocation | at least one slot with both lanes populated and budget > 1 | transient unknown errors do not consume the reserved terminal attempt |
| New admission budget per cycle | 16 | fresh clock and cancellation check before each new claim |
| Scheduler contacts in flight | 1 | not a global claim about all external control requests |
| Consecutive pre-admission failures | 3 | first failure yields; capped exponential backoff; bounded fail-stop |
| Consecutive recovery transport failures | 3 | no admission in failed cycle; independent recovery budget |

## Polling progress and known limits

Schema 20 stores two permanent keyset cursors with a frozen upper identity and
monotone sweep generation. Schema 21 indexes the sparse unknown frontier.
Reservation is timer-fenced and advances polling state before observation;
it does not alter occurrence business timestamps or create terminal evidence.
A crash after reservation may delay a key until the next sweep, never authorize
an effect. Settled keys are re-read by exact identity and disappear from work.

The finite-frontier guarantee does not bound latency under arbitrary overload,
backdated identities or unlimited arrivals inside a frozen interval. A budget of
one explicitly keeps unknown-first priority. Record these limitations in load
results rather than converting a slot-allocation test into a global liveness claim.

## Measurement

Retain exact candidate/tree, owner, writer epoch, host/configuration identity,
actual command, start/end time and result. Separate admission, provider response,
turn observation, TaskFlow reconciliation and polling-reservation latency.
Track oldest unresolved age, per-key revisit interval, ready-backlog age, skipped
or settled keys, retry class, cancellation-to-last-new-claim delay, SQLite busy
work and recovery query work. Keep business age separate from polling age.

Native occurrence and TaskFlow startup verification now materializes at most one
fixed-size keyset page at a time while preserving a coherent TaskFlow snapshot.
That source bound does not establish a selected-host SLO: total scan time still
grows with retained history, and long-retention recovery, peak RSS, SQLite I/O,
busy behavior and physical crash/power-loss outcomes require measured receipts.

## Error budgets

`DispatchUnknown` is a correctness state, not retry allowance. Schema corruption,
wrong identity and stale fencing have zero tolerance. Retryable pre-contact and
read-only recovery failures consume separate budgets; deterministic exponential
backoff is currently implemented, not jitter. A failed recovery cycle admits no
new work. Cancellation is checked before each new claim while already-started
work retains its acknowledgment/uncertainty. Unresolved effects survive retirement.


## Layered capacity evidence

Retain definition, run and event counts, page size, one-snapshot confirmation,
wall time, peak RSS, SQLite read/I/O work, reopen result and oldest unresolved age.
A source-present page bound is separate from exact-head execution, selected-host
capacity qualification and independent operational acceptance.
