# auth.authbus service-level objectives

These are production defaults; a deployment may tighten them but may not weaken the safety stop conditions without an independent security decision.

## Safety objectives

| Signal | Objective | Severity |
| --- | --- | --- |
| `authbus_checkpoint_dirty` after a maintenance tick | always `0` | critical |
| `authbus_recovery_required` after recovery grace | always `0` | critical |
| `authbus_expired_active_reservations` after two worker intervals | always `0` | critical |
| quota conservation violations | always `0` | critical |
| owner collisions | always `0` | critical |
| settlement signature/purpose bypass | always `0` | critical |

## Availability and latency objectives

Measured over rolling 30 days after excluding declared operator maintenance:

- 99.95% of local authorization decisions complete within 100 ms at p99.
- 99.9% of reservation/settlement transactions complete within 250 ms at p99.
- 99.9% of checkpoint publications complete within 500 ms at p99.
- Authority worker tick interval is 30 seconds; one tick processes at most 256 rows by default.
- Oldest undispatched active reservation age remains below 120 seconds.
- Active reservations remain below 80% of the hard global capacity of 16,384.
- Aggregate quota utilization warning begins at 90%; exhaustion is critical.

Provider latency is not charged to the local AuthBus transaction SLO. Provider ambiguity is represented as `Indeterminate` and is measured separately.

## Error budget policy

Safety-objective violations have no error budget. They stop activation or mutation admission. Availability-budget exhaustion freezes non-safety changes and requires a recovery review. A deployment cannot improve availability by reconstructing a witness, releasing indeterminate quota, disabling signature checks or allowing a second writer.

## Required dimensions

Metrics are partitioned only by bounded, non-secret dimensions: result class, issuer purpose, reservation state and operation class. Never use raw principal, message, policy, reservation or secret identifiers as metric labels.
