# channel.matrix operations runbook

## 1. Readiness

Treat Matrix as ready only when the supervisor reports the exact companion healthy and matrixd reports: store/migrations 1-7 verified, final-use broker reachable, authenticated revocation feed current, Agentd connected, initial durable sync complete and continuous sync connected. Queue acceptance or process liveness alone is not readiness.

## 2. Required metrics

- sync lag and last committed checkpoint;
- inbox pending and oldest age;
- outbox pending/in-flight/retry and oldest age;
- dispatch counts by `dispatched`, `accepted`, `indeterminate`, `succeeded`, `failed`, `redacted`, `observed_unqualified`;
- active claims by `claimed/authorized/dispatching`, lease expiry and expired-claim rate;
- attempt events by kind and typed failure class;
- authority epoch/revision, witness/revocation-head digest presence and refresh failures;
- send latency, normalized 429 delay/jitter, DNS/TLS/connect/read/response-loss classes;
- redaction propagation latency;
- supervisor restarts, exhausted restart budgets and orphan-adoption results.

Never emit message bodies, credentials, access/session keys, signing material, raw signed grants/tokens or raw claim capabilities.

## 3. Alerts

Page on store corruption, migration/fingerprint mismatch, authority rollback, binding/generation mismatch, repeated broker failure, unresolved-dispatch capacity, sync stopped while outbound work exists, contradictory terminal observations, stale writer activity or inability to fence a claim/process. Warn on growing queue age, sustained rate limits, claim expiry, repeated indeterminate sends and authority-capacity reserve.

## 4. Safe inspection

1. Record exact release, source SHA/tree, Agent ID and supervisor/Matrix process identities.
2. Stop new admissions when terminal truth, claim ownership or authority freshness is uncertain.
3. Query typed control snapshots and bounded queue/dispatch/attempt summaries; never edit SQLite manually.
4. Correlate stable transaction, operation, attempt, lease epoch, claim-token digest, grant ID, event IDs and observation/witness digests.
5. Confirm current room binding, device/session generation and revocation frontier.

## 5. Recovery procedures

### Broker or revocation feed unavailable

Keep matrixd unready or stop outbound dispatch. Repair private path/ownership/socket/feed. Do not bypass authority or reuse a cached grant. Restart only after monotonic frontier validation.

### Indeterminate send

Do not create a new transaction ID and do not mark failure. Restore sync connectivity, use the normal durable sync path and let the owner transaction reconcile the matching transaction/event. Retain the complete attempt history.

### Stuck active claim

Verify no live exact matrixd owns the process lease. For a proven pre-entry claim use the typed fenced release path; otherwise allow lease expiry and a higher attempt to replace it. Never disclose/reconstruct the raw claim capability, delete the active row manually or decrement attempts.

### Store corruption

Fence/stop matrixd, preserve database/WAL, session and authority state, collect integrity/schema diagnostics, and restore only from a qualified authenticated snapshot. Do not delete and recreate the owner store.

### Binding/device change

Drain the old companion, commit the new public binding/session generation through its owner, then start a new exact process generation. Old grants, witnesses and claims remain historical and cannot authorize the new scope.

## 6. Rollout and rollback

Roll out with a canary Agent and bounded room set. Require current exact-head and synthetic-merge receipts plus applicable real homeserver qualification before promotion. Roll back only to a binary compatible with migrations 1-7; otherwise roll forward. Keep matrixd and agentd as one paired release and verify both program digests.

## 7. Evidence collection

Every qualification/runbook execution retains exact source/tree, source blob hashes, workflow/run/job identity, binary/container digests, configuration digest, homeserver image/version/Git SHA, authority/binding identities, structured result, failure-injection parameters, bounded redacted logs and artifact-manifest digest. `skip` is not pass, and a successful unit test is not a real homeserver, encrypted-room, restore, operator-acceptance or release receipt.
