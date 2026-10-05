# control.engineering capacity and migration policy

This document defines the default bounded SQLite profile used by the named product owner. The values are safety ceilings for one selected host profile, not universal performance claims.

## Default admission ceilings

The source default in `capacity_policy.py` is:

| Dimension | Default hard ceiling |
| --- | ---: |
| SQLite database pages | 4 GiB |
| active WAL file | 512 MiB |
| audit events | 5,000,000 |
| active local path leases | 4,096 |
| active worker claims | 4,096 |
| active capacity reservations | 4,096 |
| migration signal | 75% of the largest dimension |

`evaluate_database_capacity` records every measured dimension, a policy digest, and a measurement digest. `EngineeringControlProduct` checks the selected policy before and after every new admission that can increase durable work: envelope admission, lease acquisition, plan publication, worker registration or renewal, claim admission, and integration-queue publication.

The before/after checks run inside the same re-entrant owner transaction as the mutation. If the post-write measurement crosses a hard ceiling, the new admission and its audit event roll back together. The owner never retains a second lease, claim, reservation, or queue row and merely reports the overflow afterward.

Capacity pressure does not disable the paths needed to drain or resolve existing work. Startup reconciliation, heartbeat, result submission, independent completion observation, and terminal integration reconciliation remain callable; recovery runs first and admission stays closed if the resulting owner remains above a hard ceiling. This distinction prevents capacity policy from trapping stale reservations or indeterminate terminal work.

The check does not delete rows, checkpoint the WAL, resize the filesystem, rewrite audit history, or grant migration authority.

## Operational policy

A deployment must replace the defaults with values derived from its retained target-host profile. Alerting should begin before the migration signal and should cover database bytes, WAL bytes, audit growth, lock wait, backup duration, restore verification, and claim latency.

A hard limit requires new admission to stop. Operators may still perform bounded diagnosis, verified backup, recovery, and terminal reconciliation. Raising a limit is a reviewed configuration revision and must not be used to hide unbounded growth.

`database_capacity()` is a read-only product observation. A green measurement is not a deployment, activation, or release certificate. A red measurement is not repaired by changing the projection; the durable cause must be drained, archived under an approved retention policy, or migrated.

## Migration trigger

Migration to a replicated external coordination owner should be planned before any of these become normal:

- sustained multi-host writes requiring consensus rather than external fencing receipts;
- write contention or recovery time outside the selected SLO;
- audit verification or owner-state anchoring whose bounded checkpoint strategy no longer meets restart requirements;
- database/WAL growth that cannot be controlled by verified retention and checkpoint policy;
- availability requirements that cannot tolerate a single SQLite writer.

The SQLite owner remains authoritative until an externally reviewed migration binds source identity, schemas, replay protection, fencing, backup/restore, rollback, and dual-read or cutover semantics. A projection, benchmark, copied database, or capacity alert alone cannot switch authority.

## Recovery objectives

RPO and RTO are deployment facts. The repository supplies online backup, restore verification, stress, capacity, and checkpoint mechanisms but deliberately records no universal RPO/RTO. The production evidence bundle must state the selected objectives and include a target-specific backup/restore and rollback rehearsal that meets them.
