# automation.taskflow runtime budgets and SLO contract

**Automation store schema: v19.** Values below are source defaults and
qualification thresholds; they are not selected-host measurements or a release
receipt.

| Signal | Source bound | Required operational observation |
|---|---:|---|
| scheduler wake interval | 250 ms | tick delay and scheduling jitter |
| new admissions per pass | 8, hard library ceiling 64 | admitted count, budget exhaustion and oldest due age |
| historical reconciliation per pass | 4 | pending/uncertain count and oldest uncertain age |
| occurrence lease | 30 s | expiry/reclaim count by writer generation |
| App Server admission timeout | 5 s | timeout count and subsequent exact-ID reconciliation |
| proven pre-admission retries | 3 consecutive | retry delay and terminal isolation/fail-stop result |
| transient runtime retries | 3, 250/500/1000 ms | failure disposition and exhausted budget |
| terminal turn scan | 16 pages x 100 per pass | durable cursor continuation and exhaustion result |

## Failure disposition

* `AccessDenied`, `TimerFenced` and `Corrupt` are fail-stop.
* `Unavailable` and proven pre-contact `Dispatch` receive bounded retry/backoff.
* `Invalid` and state `Conflict` are isolated from provider execution and cannot
  manufacture success or a new external effect identity.
* `DispatchUnknown` enters reconciliation only; blind redispatch is forbidden.

## Fairness and backpressure

The authoritative due order is `(scheduled_for_ms, task_id, occurrence)`. A batch
reuses the existing one-occurrence transaction sequentially, so provider calls do
not become unbounded concurrent work. Recovery and admission have separate source
budgets. `AutomationBacklogSnapshot` exposes a bounded task/occurrence/uncertainty
scan, oldest ages, truncation and the fairness order without claiming work.

Before activation, qualify p50/p95/p99 scheduling delay, maximum backlog age,
restart drain time, provider saturation, SQLite busy behavior, lease expiry and
writer-epoch mismatch on the selected host. Missing, truncated or fixture-only
measurements keep deployment qualification false.
