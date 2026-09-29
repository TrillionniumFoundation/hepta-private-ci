# channel.matrix operations runbook

## 1. Readiness

Treat Matrix as ready only when the supervisor reports the exact companion healthy and matrixd reports: store/migrations 1-13 and their exact schema/invariants verified, final-use broker reachable, authenticated revocation feed current, Agentd connected, initial durable sync complete and continuous sync connected. Queue acceptance or process liveness alone is not readiness.

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

### Legacy canonical-content hold

Do not retry, rename or delete a transaction listed in the sealed legacy-hold snapshot. Migration 11 closes any stale local claim, creates or reopens the durable result as `accepted`/`indeterminate`, and parks active queue states at the non-runnable maximum schedule. Restore authenticated sync and reconcile the original transaction; only the normal sync-owner transaction may settle it. A large held set consumes unresolved capacity by design and requires retention/archival planning rather than evidence deletion.

### Store corruption

Fence/stop matrixd, preserve database/WAL, session and authority state, collect integrity/schema diagnostics, and restore only from a qualified authenticated snapshot. Do not delete and recreate the owner store.

### Binding/device change

Drain the old companion, commit the new public binding/session generation through its owner, then start a new exact process generation. Old grants, witnesses and claims remain historical and cannot authorize the new scope.

## 6. Rollout and rollback

Roll out with a canary Agent and bounded room set. Require current exact-head and synthetic-merge receipts plus applicable real homeserver qualification before promotion. Roll back only to a binary compatible with migrations 1-13, including canonical pins, entered-use proofs, parked legacy holds, migration-12 cross-attempt terminal qualification and migration-13 recovery scheduling/quarantine state; otherwise roll forward. Keep matrixd and agentd as one paired release and verify both program digests.

## 7. Evidence collection

Every qualification/runbook execution retains exact source/tree, source blob hashes, workflow/run/job identity, binary/container digests, configuration digest, homeserver image/version/Git SHA, authority/binding identities, structured result, failure-injection parameters, bounded redacted logs and artifact-manifest digest. `skip` is not pass, and a successful unit test is not a real homeserver, encrypted-room, restore, operator-acceptance or release receipt.

## 8. Executable diagnostics and alert policy

Run the read-only diagnostic tool on the private owner database:

```sh
python3 scripts/channel_matrix_diagnostics.py --database /private/matrix_1.sqlite3
python3 scripts/channel_matrix_diagnostics.py --database /private/matrix_1.sqlite3 --transaction EXACT_TXN_ID
python3 scripts/channel_matrix_diagnostics.py --database /private/matrix_1.sqlite3 --event EXACT_EVENT_ID
python3 scripts/channel_matrix_diagnostics.py --database /private/matrix_1.sqlite3 --format prometheus --check
```

A transaction selector returns closed reason/retry/action codes without echoing the
transaction ID. `active_claim_preparing`, `active_claim_authorized` and
`active_claim_dispatching_or_unknown_effect` prohibit another retry while the
claim is live. `expired_active_claim_requires_fenced_recovery` requires process
lease verification before owner recovery. `retry_window_not_due` exposes the
next durable schedule. `fresh_authority_required` requires a new broker grant and
current revocation frontier. `remote_result_not_yet_reconciled`, legacy holds and
parked work preserve the same transaction and require authenticated `/sync`
reconciliation; none authorizes a new transaction or manual SQL repair.

The tool uses `mode=ro`, `query_only`, a consistent read transaction and a bounded
SQLite instruction budget. It performs no migrations, writes, retries, grant
issuance or automatic remediation. It reads only counts/timestamps and explicitly
selected state fields; payloads and credential material are never queried.
`--transaction` is parameterized and its value is not echoed. Diagnostic schema
checks are not a substitute for the native store-open integrity validator.

Default policy (tune to a measured deployment, not a claimed SLO): warning when
unresolved capacity reaches 80%, queue age exceeds 300s or a claim is expired;
critical at capacity or when pending outbound work has no sync checkpoint or a
checkpoint older than 120s. A slow/idle checkpoint is a freshness warning, not
a claim that the network is disconnected. Capacity is a policy input and must
match the deployed owner configuration. Prometheus labels are closed enums only.
The `--check` exit status is 0 healthy, 1 warning, 2 critical/error. Transport
window counters come from the production sender's ten-second structured stderr
events (`hepta.channel-matrix-runtime-metrics.v1`); the normal log collector must
retain them before an external dashboard can display the measurements.

Unmeasured live broker/revocation freshness, redaction propagation latency,
supervisor restart counts and encrypted-session continuity remain explicitly
`not_in_snapshot`, never zero-valued green signals. Missing metrics require
independent live probes/receipts; the tool does not authorize rollout.

## Ingress recovery diagnostic workflow

See [Recovery and diagnostics](RECOVERY_DIAGNOSTICS.md) for exact-event selectors,
quarantine/backoff classifications, gate metrics and the cooperative budget.
Never turn a pending/quarantined/unknown identity into new work by editing SQL.
