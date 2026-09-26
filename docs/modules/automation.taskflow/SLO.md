# automation.taskflow runtime SLO contract

These objectives govern operations; they do not weaken durable correctness.

| Signal | Default objective | Breach action |
|---|---:|---|
| App Server/provider dispatch response | 5 s | classify as unknown after the seam; preserve identity and reconcile |
| Unknown-result reconciliation | 5 min | alert and retain quarantine; no blind redispatch |
| Scheduler lease | 30 s | expiry permits only the reviewed reclaim path; never proves provider absence |
| Writer-epoch fence propagation | 1 s | mark host fenced and stop admission |
| Recovery work per cycle | 8 | continue next cycle with durable cursor |
| New admissions per cycle | 16 | continue next cycle; preserve age-first ordering |
| Provider calls in flight | 1 | apply backpressure rather than opening parallel authority paths |
| Consecutive proven pre-admission failures | 3 | fail-stop automation after bounded exponential backoff |

## Measurement

Each receipt must bind exact commit, host, owner Agent, writer epoch, command,
start/end time and result. Latency histograms separate queue admission,
provider response, turn terminal observation and TaskFlow reconciliation.

## Error budgets

- `DispatchUnknown` is a correctness state, not a retry budget event.
- Schema corruption and fencing have zero tolerance and fail closed.
- Temporary transport/storage errors consume the bounded retry budget.
- Occurrence-local conflicts are isolated per cycle; repeated conflict reaches
  fail-stop rather than spinning forever.
- Backlog age is measured from canonical `scheduled_for_ms`, not process wake-up.
