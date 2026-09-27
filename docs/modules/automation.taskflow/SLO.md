# automation.taskflow runtime SLO contract

This schema-v19 SLO applies to the durable V1 scheduler, recovery lanes, external-effect bridge and the bounded Neural Circuit runtime slice. These objectives govern operations; they do not weaken durable correctness.

| Signal | Default objective | Breach action |
|---|---:|---|
| App Server/provider dispatch response | 5 s | classify as unknown after the seam; preserve identity and reconcile |
| Unknown-result reconciliation | 5 min | alert and retain quarantine; no blind redispatch |
| Scheduler lease | 30 s | expiry permits only the reviewed reclaim path; never proves provider absence |
| Writer-epoch fence propagation | 1 s | mark host fenced and stop admission |
| Distinct recovery rows per cycle | 8 | continue next cycle; each selected row is contacted at most once |
| New admissions per cycle | 16 | continue next cycle; preserve scheduled-age ordering |
| Provider calls in flight | 1 | apply backpressure rather than opening parallel authority paths |
| Consecutive proven pre-admission failures | 3 | fail-stop automation after bounded exponential backoff |
| Consecutive recovery transport failures | 3 | block admission during retry; fail-stop after the independent bounded budget |

## Measurement

Each receipt must bind exact commit, host, owner Agent, writer epoch, command,
start/end time and result. Latency histograms separate queue admission,
provider response, turn terminal observation and TaskFlow reconciliation.

## Error budgets

- `DispatchUnknown` is a correctness state, not a retry budget event.
- Schema corruption and fencing have zero tolerance and fail closed.
- Temporary transport/storage errors consume the appropriate admission or
  recovery retry budget; the budgets are independent.
- A failed recovery attempt admits no new work in the same cycle.
- Occurrence-local conflicts are isolated per cycle; repeated conflict reaches
  fail-stop rather than spinning forever.
- New-admission backlog age is measured from canonical `scheduled_for_ms`.
  Unknown-dispatch recovery age is measured from `observed_at_ms`; admitted turn
  observation age is measured from the durable occurrence `updated_at_ms`.
