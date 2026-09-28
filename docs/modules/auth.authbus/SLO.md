# auth.authbus service-level objectives

These are production defaults for the single-owner AuthBus authority service and its Evidence-owned delivery queue. A deployment may tighten them but may not weaken safety stop conditions without an independent security decision. Repository source and target values are not production evidence until the exact candidate has terminal-success qualification receipts and the selected host has accepted operational evidence.

## Safety objectives

Safety objectives have no error budget. Any violation blocks readiness or new authority use until reconciled.

| Signal | Objective | Required action |
| --- | --- | --- |
| `authbus_checkpoint_dirty` after a maintenance/reconciliation tick | always `0` | Stop new authority use; preserve both state domains and reconcile. |
| `authbus_recovery_required` after the configured restart grace | always `0` | Continue bounded recovery; do not bypass admission. |
| `authbus_expired_active_reservations` after two worker intervals | always `0` | Page the owner; repair worker/trusted-time health and run bounded sweeps. |
| quota conservation violations | always `0` | Isolate the store; no automatic repair or refund. |
| successful second owner for one database | always `0` | Stop both generations and investigate the fence/platform boundary. |
| unresolved `mutation_committed_reconciliation_required` | always `0` after one reconciliation attempt | Treat the mutation as committed, reconcile the checkpoint and inspect stable identity before retry. |
| unresolved `mutation_outcome_unknown` | always `0` after incident handling | Freeze blind retry and determine durable state by stable identity. |
| settlement signature, purpose, revision or payload-binding bypass | always `0` | Revoke the affected epoch and isolate the effect path. |
| replay accepted at or below the durable replay frontier | always `0` | Stop ingress and reconcile Evidence replay state/witness. |
| active Evidence delivery at the maximum claim-attempt bound | always `0` outside declared reconciliation | Stop automatic retry and reconcile prior delivery attempts. |
| Evidence snapshot replaced by fabricated zero values after query failure | always `0` | Treat the Evidence owner as unhealthy; do not hide missing observations. |

`authority_use_blocks` is expected during deliberate fail-closed recovery or checkpoint incidents. A nonzero delta outside such a declared interval is a critical readiness event, not an availability success.

## Availability and latency objectives

Measured over rolling 30 days after excluding declared operator maintenance and before provider-network time is added:

- 99.95% of local authorization operations complete within 100 ms at p99.
- 99.9% of reservation and settlement mutations complete within 250 ms at p99.
- 99.9% of complete authority mutations, including checkpoint publication, complete within 500 ms at p99.
- 99.9% of bounded maintenance ticks complete within one worker interval at p99.
- The default worker interval is 30 seconds and one tick processes at most 256 rows; configured limits remain in `1..=1024`.
- Oldest undispatched active reservation age remains below 120 seconds.
- Active reservations remain below 80% of the hard global capacity of 16,384.
- Aggregate quota utilization warning begins at 90%; exhaustion is critical.
- Evidence active outbox depth remains below 80% of the hard row bound of 4,096.
- Oldest unsettled Evidence delivery age remains below 120 seconds.
- Retained enqueue-to-ack latency remains below 60 seconds at p95 and 120 seconds at p99, excluding declared downstream maintenance.
- Retained claim retries remain below 5% of retained successful claims; any active row at 16 attempts is critical.

`mutation_latency` is measured from entry to the public host operation through owner-gate wait, checkpoint preflight, SQLite work, checkpoint publication and local promotion. `maintenance_latency` covers the same owner boundary for bounded restart and expiration reconciliation. Measurements that time only a local SQLite transaction are not comparable to these objectives.

The authority runtime snapshot exports bounded histograms as `count`, `p50`, `p95`, `p99` and `max`. They are process-lifetime cumulative summaries. The exporter computes interval deltas/rates and preserves the complete-operation definition.

`AuthBusOutboxOperationalSnapshot` is a bounded read-only projection over the currently retained Evidence outbox. Its claim attempts, retries and enqueue-to-ack latency can decrease after terminal pruning and therefore are evaluated as retained-window values, not monotonic counters. Dashboards must display retained row count with these values so operators can distinguish a healthier queue from a pruned observation window.

Provider latency is not charged to the local AuthBus mutation objective. Provider ambiguity is represented as `Indeterminate` and measured by the Bao/effect owner. Evidence owns enqueue-to-ack time; Agentd owns delivery-worker processing; Bao and the HTTP client own provider request duration. The service dashboard correlates those bounded operation classes without attributing the entire path to AuthBus.

## Recovery objectives

- Owner collision detection is immediate and fail-closed.
- A failed same-process duplicate initialization must leave the live cross-process fence effective.
- `SIGKILL` releases the OS-managed fence; the next owner completes bounded restart reconciliation before new writes.
- Checkpoint write, file-sync, rename and directory-sync failures are classified as committed-needs-reconciliation when the SQLite mutation is known durable.
- A dirty frontier blocks the next authority operation before its domain future is polled.
- Recovery progresses in bounded fair batches; increasing frequency is preferred to unbounded batch size.
- An indeterminate reservation is never automatically refunded to improve availability.
- A delivery with more than one retained claim is reconciled against prior effect evidence before another effect is created.
- Evidence outbox observation never takes a lease, changes a fence, acknowledges a delivery or advances replay state.

## Error-budget policy

Safety-objective violations have no error budget. Availability-budget exhaustion freezes non-safety changes and requires a recovery review. A deployment cannot improve availability by reconstructing a witness, releasing indeterminate quota, disabling signature checks, bypassing the host gate, exposing the raw store, allowing a second writer, resetting delivery attempts or acknowledging a row without the exact active lease.

The following authority result classes are budgeted separately because their remediation differs:

- deterministic rejection (`NotCommitted`);
- fail-closed authority admission (`AuthorityUseBlocked`);
- committed mutation awaiting checkpoint reconciliation (`CommittedNeedsReconciliation`);
- unknown durable outcome (`OutcomeUnknown`);
- successful fully durable operation.

Delivery health is budgeted separately as queued backlog, leased backlog, retained retries, exhausted attempts and enqueue-to-ack latency. Combining these classes into one generic error rate is prohibited because it hides whether the system is blocked on authority, worker ownership, downstream durability or an unknown external effect.

## Required dimensions

Metrics use only bounded, non-secret dimensions: result class, issuer purpose, reservation state, delivery state, operation class and blocking reason. Never use raw principal, message, policy, reservation, delivery, operation or secret identifiers as metric labels.

At minimum, dashboards expose:

- owner acquisition failures by active-owner, unsafe-path and storage class;
- checkpoint failures by rollback conflict and storage class;
- blocked authority use and each mutation disposition;
- replay rejection deltas;
- maintenance failures and incomplete-recovery ticks;
- active/expired/indeterminate reservations, oldest active age and quota utilization;
- complete-operation mutation and maintenance latency summaries;
- Evidence queued/leased/terminal counts, active depth and oldest unsettled age;
- retained claim attempts/retries and exhausted active rows;
- retained enqueue-to-ack latency summaries;
- separately owned Agentd worker and Bao/provider latency.

## Evidence binding

The claim-to-source-to-test mapping is `VERIFICATION_MATRIX.md`. SLO implementation claims are valid only for the final pull-request head whose `.github/workflows/authbus-authority-qualification.yml` exact-head and deterministic synthetic-merge jobs both terminate successfully and whose uploaded receipt names those exact Git objects. A receipt for an earlier source or documentation commit, a skipped/cancelled run or a workflow that mutates the candidate before testing is not qualification evidence.
