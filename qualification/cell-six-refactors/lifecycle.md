# Cell generation lifecycle: bounded checkpoint and model transitions

This change extends `CellGenerationJournalV2`, the existing exclusive state owner. It does **not** establish long-service readiness. The journal, independent witness, worker, artifact selection, and source authority retain their existing responsibilities.

## Checkpoint and reconciliation APIs

- `checkpoint_to(successor: File)` validates the current journal, writes and syncs a complete checkpoint into a fresh exclusively locked file, advances the same independent witness, and then switches the in-memory owner. The original file remains byte-for-byte intact.
- Checkpoints preserve the complete runtime snapshot, immutable output prefix, pending admission, outbox, cancellation/drain state, operation receipts, acknowledgement identities, and cost ledger. Unknown operations remain pending and consume reserved capacity.
- Checkpoint payloads authenticate the entire owner-header digest, including task, source frontier, initial identity and record limit. An attacker cannot transplant a checkpoint by recomputing only its outer header. Ordinary event journals remain readable; checkpoint segments use `HPTACG03`.
- `reconcile_pending(control, clock)` calls only `read_generation` for the original request. It samples the clock before and after readback, rejects clock rollback, rejects a proposal for a different request, and settles with the post-read time. A late result retains measured cost but publishes no late output. Missing/error readback neither resubmits work nor invents failure.
- `journal_metrics(now_micros)` reports retained bytes, segment/lifetime sequence counts, reservations, receipt/outbox counts, pending/queue age, and the last successful local recovery's replay count and elapsed microseconds. These are owner observations, not throughput or energy benchmarks.

`CellGenerationCheckpointReceiptV2` identifies the archived bytes and new checkpoint. Its checksum is an integrity observation, **not** an authenticated archive-custody or retention receipt.

## Compatible model migration and rollback

`migrate_to(successor, target_config, verifier, now_micros)` requires a healthy, explicitly drained owner with no pending request or unacknowledged output. The target must preserve:

- Task digest, source digest and source frontier.
- Full Cell scope, runtime, device, profile and input/state/output schemas.
- Structure, component presence/topology, resource limits and cost accounting bounds.

The bundle must change. Target generation and writer epoch must each equal the current value plus one. Code, source, schema, ownership, metering and resource-limit changes are refused by this phase.

`CellGenerationMigrationVerifierV2` is an enrolled-host port, not a new authority service. Its implementation must authenticate the target's current independent selection, backend-specific qualification, allowed use and non-withdrawn source; qualify and validate the conversion of the **current** hidden state/KV; and hold the existing final-use/source barrier throughout the install callback, file sync and witness CAS. A nonzero receipt digest or decoded bundle plan is not sufficient. The production artifact/worker adapter for this port is still required; tests use an independent host-view fixture and do not demonstrate adoption of a native learned model.

The owner changes only the qualified state bytes, manifest binding, generation, writer epoch, clock floor and appended migration costs. It preserves the latest prefix, operation receipts, acknowledgement identities, revision, prior costs and stopped state. Both upgrade and rollback use this transition. Rollback never loads an old owner snapshot to overwrite newer acknowledged writes. The successor remains drained until the host loads it and explicitly resumes.

Before invoking a transition, the host must durably retain the **exact target configuration and successor pathname**. Reopening requires that exact configuration. A file handle cannot sync its parent directory or define path-retention policy. Previously committed requests remain idempotent receipt lookups; fresh requests carrying an old predecessor generation/epoch are refused.

## Crash and acknowledgement recovery

| Observed independent witness | Recovery action |
| --- | --- |
| Still points at the old segment | Reopen the old segment. A complete but unwitnessed successor cannot promote itself. |
| Points at the successor, including a lost switch acknowledgement | Reopen the successor with its exact target configuration. The old segment refuses the missing acknowledged suffix. |
| Cannot be read or CAS outcome is uncertain | Keep both files and the independent witness; resolve the witnessed cut before resuming. Do not retry generation or infer failure from the API error. |
| Points at a successor whose required bytes are missing/corrupt | Refuse recovery. Retaining an old archive does not authorize rollback past the acknowledged successor. |

No recovery path contacts a model or publishes output. A verifier reporting an error after a successful install leaves the owner unhealthy until recovery. A successful verifier result without installation is rejected.

## Regression coverage and native gate

The new lifecycle and migration suites contain 14 tests covering:

- Checkpoint/reopen preservation of prefix, outbox, receipts, ACKs, cost and archive bytes.
- Record-capacity reclamation while cancelled/unknown work remains pending and reserved.
- Witness failure before a switch and acknowledgement loss after a witnessed switch.
- Truncated checkpoint refusal and header transplants changing task, frontier, generation, writer epoch or record limit.
- Preservation of all 256 operation identities after compaction; no receipt eviction to bypass capacity.
- Wrong-request readback, readback crossing a deadline and clock rollback.
- Upgrade, an acknowledged new-model write, then rollback preserving the new bytes, state, receipts and cost; subsequent execution on the rolled-back parameters.
- Stale-consumer refusal; pending/outbox, incompatible configuration, withdrawal/stale source view and oversized converted-state refusal.
- Keeping the verifier's live-source barrier held through the independent witness switch, including lost acknowledgement.

At the time of this note, these tests are implemented and await the coordinated native gate; no native pass is claimed here. The qualification run must record the exact revision, commands and outcomes before changing this status.

## Remaining capacity and lifecycle requirements

Checkpointing resets **segment** replay/record usage. It does not reset these independent limits:

| Limit | Current bound |
| --- | --- |
| Journal segment | 128 MiB; configured 6–65,536 event records, including required reservations |
| Individual event / checkpoint payload | 2 MiB / 32 MiB |
| Per-task operation receipts | 256; all retained for exact replay |
| Per-task cost observations | 4,096, including reserved settlement/delivery capacity |
| Committed prefix | Manifest bound, at most 262,144 bytes |
| `FileAnchorWitnessStore` lifetime CAS records | 4,096; checkpoints and model transitions also consume records |

A safe task-boundary rollover needs an authenticated, durable archive-custody/retention and task-close readback contract in the same host owner. It must retain old acknowledged output and complete cost, advance generation/epoch, reject old-task requests and authorize receipt retirement only across that explicit task boundary. The current `File`-based journal API supplies neither durable path custody nor archive retention proof. A checksum alone cannot replace those contracts.

Long-running service also needs same-owner witness succession retaining the independently acknowledged minimum anchor. Clearing or rebuilding the witness from a compacted journal would remove the rollback protection and is not implemented.

Independent terminalization of an unknown operation requires authoritative current worker outcome or an authenticated worker-epoch retirement/termination proof that excludes later output. The existing worker port exposes execute/read/cancel; `read == None` and successful cancellation do not establish that proof. Unknown operations therefore remain retained. Archive deletion policies, task rollover, witness succession, worker retirement, and end-to-end queue/tail-latency measurement remain explicit follow-up owner integrations.
