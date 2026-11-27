# C2 live resource observation (evidence only)

**HOLD_NO_GO / all_closed=false. Full independent replay remains 0/6.**

This successor to #6252 preserves two bounded read-only observations:

1. configured `h` health/hardware/effective-config responses for `desktop` and `ai395`;
2. one pre-frozen, zero-model desktop cgroup witness reconciled under the same idempotency key.

The cgroup witness first had an accepted/unknown dispatch observation. Exact same-key reconciliation returned `reused=true`, `retried_launch=false`, and authoritative job `1a1d068d908-2564-1b7c` as `succeeded` with exit 0, 7,604 stdout bytes, zero stderr bytes, complete durable output, and no timeout/cancellation.

At 2026-11-12T15:38:23Z the witness recorded the job cgroup and every ancestor through `/sys/fs/cgroup`. At the observable memory-controller levels, `memory.max` and `memory.high` were `max`; the job-local event counters were zero. Shared ancestor counters included cumulative `oom=315` and `oom_kill=15`. Those cumulative values are retained without attributing their causes or victims to this job. The root cgroup did not expose the queried memory files.

This closes only point-in-time reachability, host memory, and observable ancestor-cgroup values. It does **not** establish a durable allocation, safe long-run headroom, six-fit concurrency/calendar reservation, a coherent source/runtime/model/data freeze, all six original start parents, or the non-refunded remaining-wall ledger. `concurrent_execution=unbounded_by_runtime` and cgroup `memory.max=max` are not resource reservations.

Therefore this evidence cannot authorize or justify starting the original six-worker full replay. Historical OOM/cancelled attempts, full replay 0/6, known diagnostic calls 52, lifetime optimizer total UNKNOWN, and original controller terminal UNKNOWN remain unchanged.

Files:

- `OBSERVATION.json`: complete returned health, hardware, and redacted effective-config objects.
- `CGROUP-REQUEST.json`: frozen request and refusal contract.
- `CGROUP-STDOUT.txt`: complete 7,604-byte witness stdout.
- `CGROUP-STATUS.json`: authoritative durable terminal status.
- `CGROUP-RECONCILIATION.json`: accepted/unknown to same-key terminal reconciliation.
- `HOLD.json`: exact closure and remaining prerequisites.

No model, optimizer, native training campaign, workflow rerun, or second idempotency key was used.
