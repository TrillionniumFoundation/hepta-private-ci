# channel.matrix operations runbook

## 1. Readiness

Treat Matrix as ready only when the supervisor reports the exact companion healthy and matrixd reports: store verified, final-use broker reachable, Agentd connected, initial durable sync complete and continuous sync connected. Queue acceptance or process liveness alone is not readiness.

## 2. Required metrics

- sync lag and last committed checkpoint;
- inbox pending/oldest age;
- outbox pending/in-flight/retry/oldest age;
- dispatch counts by `dispatched`, `accepted`, `indeterminate`, `succeeded`, `failed`, `redacted`, `observed_unqualified`;
- authority epoch/revision, remaining nonce/revocation capacity and refresh failures;
- send latency, rate-limit delay and classified transport failures;
- redaction propagation latency;
- supervisor restarts, exhausted restart budgets and orphan-adoption results.

Do not include message bodies, credentials, access tokens, session keys or raw signed grants in metrics/logs.

## 3. Alerts

Page on store corruption, authority rollback, binding/generation mismatch, repeated broker failure, unresolved-dispatch capacity, sync stopped while outbound work exists, contradictory terminal observations or inability to fence a stale process. Warn on growing queue age, sustained rate limits, repeated indeterminate sends and authority-capacity reserve.

## 4. Safe inspection

1. Record exact release, source SHA, Agent ID and supervisor/Matrix process identities.
2. Stop new admissions if terminal truth or authority freshness is uncertain.
3. Query control snapshots and bounded queue/dispatch summaries; never edit SQLite manually.
4. Correlate stable transaction, operation, attempt, event IDs and observation digests.
5. Confirm current room binding, device/session generation and revocation frontier.

## 5. Recovery procedures

### Broker or revocation feed unavailable

Keep matrixd unready or stop outbound dispatch. Repair private path/ownership/socket/feed. Do not bypass authority or reuse a cached grant. Restart only after monotonic frontier validation.

### Indeterminate send

Do not generate a new transaction ID and do not mark failure. Restore sync connectivity, search the enrolled room through the normal durable sync path and let the owner transaction reconcile the matching transaction/event.

### Stuck in-flight claim

Verify no live exact matrixd owns the process lease. Let the bounded lease expire or use the typed claim-release path for a proven pre-entry claim. Never mutate attempts downward.

### Store corruption

Fence/stop matrixd, preserve database/WAL and authority state, collect integrity/schema diagnostics, and restore only from a qualified authenticated snapshot. Do not delete and recreate the store.

### Binding/device change

Drain the old companion, commit the new public binding/session generation through its owner, then start a new exact process generation. Old grants and claims remain historical and cannot authorize the new scope.

## 6. Rollout and rollback

Roll out with a canary Agent and bounded room set. Require exact-head and synthetic-merge receipts plus real homeserver qualification before promotion. Rollback only to a binary compatible with the current schema; otherwise roll forward. Keep matrixd and agentd as one paired release and verify both program digests.

## 7. Evidence collection

Every qualification/runbook execution retains exact source/tree, binary and container digests, config digest, homeserver version, authority/binding identities, structured result, failure-injection parameters, bounded logs and an artifact manifest digest. A successful unit test is not a real homeserver receipt.
