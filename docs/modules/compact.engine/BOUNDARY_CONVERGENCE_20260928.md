# compact.engine boundary convergence — 2026-09-28

This branch tracks the remaining convergence work after the V2 checkpoint implementation.

## Scope

The implementation direction is to converge existing coordinator layers into four explicit boundaries:

1. pure construction and verification
2. current admission and authority checks
3. durable transactional mutation
4. recovery reconciliation

No second execution spine, store, or parallel authority model is introduced.

## Workstream A — transaction/state boundary

- Replace manually managed transaction paths with cancellation-safe transaction ownership.
- Ensure every durable mutation validates owner, lease, root, epoch and manifest inside the mutation boundary.
- Separate event timestamps from execution-time validation.
- Add interleaving regressions:
  - cancellation during transaction
  - lease takeover during publish
  - manifest rotation during publish
  - response loss after durable commit

## Workstream B — measurement closure

- Split kernel-only capacity measurements from end-to-end publish/reopen measurements.
- Replace estimated counters with measured counters where possible.
- Mark remaining estimates explicitly.
- Add p50/p95/p99 measurements for:
  - admission
  - transaction latency
  - checkpoint publication
  - reopen
  - recovery reconciliation
  - storage growth

## Workstream C — allocation and integrity optimization

- Remove avoidable payload cloning from digest construction.
- Introduce immutable metadata views where ownership permits.
- Keep current trust, revocation and integrity checks mandatory.
- Separate startup integrity scans from normal read-path validation.

## Workstream D — capacity model

Separate limits for:

- semantic payload bytes
- metadata/archive bytes
- receipts/proofs
- durable storage footprint

Add boundary tests for each layer:

- limit - 1
- limit
- limit + 1

## Workstream E — operational errors

Preserve typed error classes across Agentd boundaries:

- invalid input
- authority conflict
- lease conflict
- capacity exceeded
- corruption
- outcome unknown

Each error must map to a recovery action rather than requiring text parsing.

## Completion evidence

Completion requires:

- exact source-head qualification
- deterministic merge qualification
- native fault injection evidence
- full publish/reopen capacity evidence
- recovery reconciliation evidence
- updated implementation map with exact evidence references

This document does not assert qualification, activation, deployment or release.