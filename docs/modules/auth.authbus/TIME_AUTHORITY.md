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

A host-clock rollback therefore cannot make an expired message valid, revive an
expired lease, move terminal retention backwards or block the owner until wall
clock catches up. The floor advances by compare-and-set revision, and SQLite
triggers prohibit identity changes, non-increasing updates, revision skips and
deletion.

Agentd uses `HeptaEvidenceStore::authbus_monotonic_now_ms()` for the pre-enqueue
expiry window and for every post-trust signature recheck. Evidence methods also
advance the floor again after acquiring their own write transaction, so a
caller cannot freeze time before waiting on SQLite.

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
