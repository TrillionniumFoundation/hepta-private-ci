# control.runtime journal formats

## Planner semantic journal

`PlannerJournalV1` stores a bounded sequence of `Snapshot`, `Decision`, `SelectedPlan`, and `Revocation` entries. Every entry carries sequence, kind, identity digest, payload digest, predecessor digest, and entry digest.

Structural validity is not sufficient. Append and reopen replay the same semantic state machine:

- a selection requires a recorded decision;
- a revoked decision cannot be selected again;
- only one active selection exists at a time;
- a revocation requires a known decision;
- duplicate serialized identities are rejected;
- truncation, sequence drift, predecessor drift, and digest corruption fail closed.

The raw append primitive is private. Callers use typed transition methods.

## Product execution store

`PlannerStoreV1` uses a fixed header and length-delimited frames. Product records include:

1. canonical decision envelope;
2. authority request;
3. independent authorization;
4. dispatch receipt;
5. terminal receipt;
6. reconciliation;
7. checkpoint.

Every product-stage record carries the exact operation identity. Owner startup replays records into the execution FSM. Missing predecessors, duplicate attempts, invalid terminal order, trailing data, invalid lengths, or unsupported legacy product records reject startup.

## Crash consistency

Append writes the full frame, synchronizes the data file, and advances in-memory state only after successful sync. A partial tail is truncated on reopen; corruption of a complete frame is fatal. Backup and atomic replacement synchronize the containing directory.

## Checkpoints and anti-rollback

A checkpoint records the current store root plus an externally retained anchor receipt. Internal hash chains and local checkpoint files do not by themselves prove freshness. Production recovery must compare with the trusted external anchor before accepting a generation or restored backup.

## Compaction

Raw suffix compaction remains a reference/migration primitive and is not exposed by `ControlRuntimeOwnerV1`. Production compaction requires a checkpointed state snapshot and an externally acknowledged retention boundary.
