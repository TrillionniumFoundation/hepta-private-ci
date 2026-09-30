# channel.matrix alerting and diagnostic policy

This document defines the executable, read-only alert path. It does not grant
send authority, repair durable state, qualify a target host or approve release.

## 1. Two-stage execution

Create the durable snapshot outside the source checkout, then evaluate it against
an explicit policy:

```sh
evidence_dir="$(mktemp -d)"
python3 scripts/channel_matrix_diagnostics.py \
  --database /private/matrix_1.sqlite3 \
  > "$evidence_dir/diagnostics.json"

python3 scripts/channel_matrix_alerts.py \
  --snapshot "$evidence_dir/diagnostics.json" \
  --policy docs/modules/channel.matrix/ALERT_POLICY.json \
  --check
```

The first command owns bounded SQLite inspection. The second command owns alert
thresholds and emits `hepta.channel-matrix-alert-evaluation.v1`. Separating them
lets operators retain the exact snapshot and policy digests used for a page.

`--check` returns 0 for `ok`, 1 for `warning`, and 2 for `critical` or invalid
input. Prometheus output uses only the closed alert and severity inventories:

```sh
python3 scripts/channel_matrix_alerts.py \
  --snapshot "$evidence_dir/diagnostics.json" \
  --format prometheus
```

## 2. Policy fields

[`ALERT_POLICY.json`](ALERT_POLICY.json) is a conservative repository default,
not a measured production SLO. A deployment may supply another canonical regular
JSON file with exactly the same schema and fields:

- `syncStaleMs`: page when pending queue work or any unresolved dispatch lacks a
  fresh committed sync checkpoint;
- `queueAgeWarningMs`: warn on old pending, in-flight or scheduled work;
- `indeterminateAgeWarningMs`: warn when the oldest unknown remote effect has
  not reconciled;
- `parkedQueueWarning` and `parkedAgeWarningMs`: warn when permanently parked
  same-transaction reconciliation work accumulates or ages;
- `expiredClaimCountWarning` and `expiredClaimAgeWarningMs`: warn when claim
  leases have expired and exact fenced recovery has not progressed;
- `redactionPropagationWarningMs`: warn when a redaction observed during the
  diagnostic five-minute window arrived too long after the original matching
  homeserver event;
- `rateLimitedEventsWarning`: warn on sustained typed 429 observations in the
  diagnostic five-minute window;
- `authorityDeniedEventsCritical`: page on repeated authority denials;
- `responseLostEventsWarning`: warn on repeated response-loss outcomes;
- `inboxDependencyUnavailableWarning`: warn when ingress recovery repeatedly
  cannot reach a dependency.

The evaluator rejects unknown fields, unknown durable labels, negative values,
inconsistent unresolved counts, user-controlled metric labels, symlinks and
oversized policy files.

## 3. Action semantics

The additional policy alerts are:

| Code | Required response |
|---|---|
| `sync_checkpoint_stale_with_unresolved_work` | stop new admission; restore authenticated sync; preserve transaction identities |
| `indeterminate_age` | reconcile the same transaction; never invent a replacement transaction |
| `parked_work_pressure` | restore authenticated sync and preserve every stable transaction; never create replacement work |
| `claim_expiry_pressure` | verify the process lease and use only fenced recovery; never edit or delete claims |
| `redaction_propagation_lag` | inspect sync/redaction frontier continuity and preserve original terminal lineage |
| `rate_limit_pressure` | inspect normalized Retry-After handling and capacity; do not hot-loop |
| `authority_denial_pressure` | stop dispatch and restore broker/revocation freshness |
| `response_loss_pressure` | restore sync and reconcile unknown effects |
| `inbox_dependency_pressure` | restore the dependency while preserving event identity and owner backoff |

The evaluator retains built-in diagnostic alerts, upgrades severity only when a
closed policy rule requires it, and never includes transaction IDs, event IDs,
room IDs, payloads, credentials, grants or raw claim capabilities.

## 4. Measurement semantics

`oldest_parked_age_ms` is measured from the original outbox creation time.
`oldest_expired_claim_age_ms` is measured from the expired lease boundary.
Neither authorizes a new attempt. `redaction_propagation_max_last_300s_ms` is the
largest observed interval in the last five minutes between a matching
`homeserver_event` observation and its later redaction observation. It describes
completed propagation, not proof that no still-pending remote redaction exists.

All three measurements come from one read-only SQLite snapshot that includes the
live WAL. Missing measurements remain `null`; they are never rewritten as zero.

## 5. Coverage boundary

The durable snapshot still cannot measure live broker/revocation freshness,
supervisor restart counts, encrypted-session continuity, or redactions that have
not yet produced any authenticated remote observation. Those remain explicit
external probes and qualification receipts; absence from this alert result is
not a green measurement.
