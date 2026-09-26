# auth.authbus observability

Status: normative telemetry contract

The machine-readable assets in `observability/` are owned by the AuthBus module:

- `metrics.yaml` defines bounded metric names, units, labels and meanings;
- `alerts.yaml` defines warning/critical conditions and runbook routes;
- `dashboard.json` defines the minimum authority dashboard.

A deployment is incomplete when these assets exist only as documentation. The
production authority wrapper must export the specified measurements, install the
alerts and provision a dashboard with equivalent queries.

## Receipt-first instrumentation

Every security-sensitive operation emits one structured receipt and derives
metrics from that receipt. The receipt contains bounded reason codes and digests,
not secret material or arbitrary error strings.

Required receipt classes:

- issuer lookup and verification;
- trusted-time verification;
- authorization and policy revision;
- quota reservation and lifecycle transition;
- dispatch fence;
- settlement verification and terminal transition;
- owner-lock acquisition/loss;
- checkpoint compare/publish/verify;
- restart reconciliation, expiry sweep and compaction;
- maintenance tick;
- integrity/schema/API-inventory qualification.

Receipts include source SHA, schema digest and authority instance ID so an
operator cannot silently combine evidence from different binaries or schemas.

## Bounded reason taxonomy

At minimum, implementations use enumerated reasons equivalent to:

```text
ok
invalid_input
unknown_issuer
wrong_purpose
wrong_epoch
revoked
retired
invalid_signature
expired
stale
rollback
policy_unavailable
quota_exhausted
revision_conflict
invalid_transition
idempotency_conflict
owner_collision
unsafe_file
checkpoint_mismatch
checkpoint_io
sqlite_busy
sqlite_integrity
schema_mismatch
capacity_exceeded
provider_indeterminate
```

Do not put database messages, paths, user content or identifiers into metric
labels. Full diagnostic errors remain in access-controlled logs and incident
artifacts.

## Health states

The authority publishes exactly one current health state:

- `ready`: owner fence held, integrity/schema valid, checkpoint synchronized,
  trusted time fresh and maintenance current;
- `degraded`: still fail-closed and safe, but warning backlog/freshness thresholds
  exceeded;
- `recovery_required`: no new admission; operator action required;
- `stopped`: no active owner.

An HTTP or IPC readiness endpoint returns ready only for the first state. Liveness
must not report healthy solely because the process is running.

## Dashboard review order

Operators examine panels in this order:

1. owner fence and closed-world API inventory;
2. database/witness generations and dirty duration;
3. recovery-required state and backlogs;
4. trusted-time freshness and issuer failures;
5. reservation/indeterminate lifecycle and quota conservation;
6. maintenance cadence, SQLite contention and storage growth;
7. evidence outbox latency.

This order prevents availability symptoms from obscuring a trust or rollback
incident.

## Telemetry failure behavior

Telemetry export failure does not grant authority or relax a security check. It
does, however, make the service degraded. If the authority cannot persist its
local operation/maintenance receipt or the critical health signal disappears for
five maintenance cadences, the deployment must stop new admission until
observability is restored or an approved local-only incident mode is entered.

## Validation

CI validates:

- YAML and JSON syntax;
- metric names referenced by alerts/dashboard exist in `metrics.yaml`;
- required critical alerts have a runbook;
- raw identifier labels are absent;
- every SLO threshold has a corresponding panel or alert;
- source instrumentation exports every required receipt class.

Staging performs synthetic owner-collision, checkpoint-dirty, stale-time,
expired-reservation and outbox-stall drills and verifies that alerts route to the
named on-call target.
