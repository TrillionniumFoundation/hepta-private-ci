# AuthBus Evidence time authority

## Owner

The Evidence SQLite owner contains one `authbus_time_floor` singleton. Every
AuthBus admission, enqueue, lease, retry, acknowledgement, quarantine,
retention and operational observation advances or reads that floor while
holding the same `BEGIN IMMEDIATE` transaction used by the operation.

The effective instant is:

```text
max(host_clock_observation, persisted_authbus_time_floor)
```

With an intact persisted floor, successful operations cannot move below the
latest committed local time observation. The floor advances by compare-and-set
revision, and SQLite triggers prohibit identity changes, non-increasing updates,
revision skips and deletion. This is a local nondecreasing-time contract, not
attestation of current wall time: it supplies no freshness or drift bound, and
uncommitted observations are not claimed to survive rejection or restart.

Agentd TextIngress uses `HeptaEvidenceStore::authbus_monotonic_now_ms()` for its
pre-enqueue expiry window and post-trust signature recheck. Evidence methods also
advance the floor again after acquiring their own write transaction, so that
path does not rely only on a time observation taken before waiting on SQLite.

The Objective runtime/startup and RunStart authentication migration is incomplete
in this lineage: five callers still reference the removed `authbus_ingress::now_ms`
helper, so full Agentd compilation is blocked. These authority-bearing callers
need an explicit reviewed current-time source; restoring an unqualified wall-clock
fallback would not establish that contract. Proposed V2 interval/challenge tests
are specification evidence only and do not complete this integration.

Call-site inventory at candidate `d29ad701b9adf1171a08dd137dc7154c46ff71db`:

- Migrated TextIngress observations: `codex-rs/hepta-agentd/src/authbus_ingress.rs:142,168`.
- Blocked Objective checks: `codex-rs/hepta-agentd/src/objective_runtime.rs:147,290`.
- Blocked runtime admission/reconciliation: `codex-rs/hepta-agentd/src/runtime.rs:174,450`.
- Blocked synchronous RunStart authentication: `codex-rs/hepta-agentd/src/state.rs:708`.

Passing AuthBus/Bao package checks, qualification fixtures and the separate
Evidence suite cover those packages. They do not establish full Agentd build or
startup qualification: the exact-head authority workflow stops at these five
missing-helper compilation errors after its AuthBus and Evidence tests pass.

## Rollback semantics

The floor is part of the Evidence database owner. Replay rollback remains
protected by the independently retained replay checkpoint. Lease-only state is
intentionally not represented as external-effect authority: restoring an older
lease may permit delivery reconciliation under the same delivery identity, but
cannot mint quota, provider authority or a new durable operation identity.
Outbox consumers must continue to deduplicate/reconcile by delivery ID.

A target-host acceptance receipt must still exercise clock rollback, clock
forward jump, restart, lease expiry, terminal retention and old-database restore
against the deployed filesystem and checkpoint domains. Source tests and schema
triggers are not production evidence.
