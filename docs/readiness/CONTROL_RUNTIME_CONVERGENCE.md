# Control runtime convergence candidate

**Module:** `control.runtime`  
**Owner:** `runtime-control`  
**Deputy:** `security-authority`  
**Candidate ref:** `codex/control-runtime-convergence-v1`  
**Authority delta:** none

This document describes the current source candidate for planner integrity,
durable recovery, authority-separated dispatch, and read-only organ fanout. It
is not an activation, production-selection, independent-acceptance, promotion,
or release receipt. The canonical stage facts remain in
`docs/modules/control.runtime/CURRENT_STATE.json`; native symbols and tests
remain mapped by `docs/modules/control.runtime/IMPLEMENTATION_MAP.json`.

## 1. Boundaries that remain unchanged

The planner, utility owner, authority owner, and effect owner remain separate.
`control.runtime` constructs bounded snapshots, enforces resource floors, binds
the NDU evaluation, and emits authority-free decisions and grant requests. It
does not mint a capability, execute an effect by itself, or treat a test receipt
as production authority.

The Agentd cognitive-context caller is a read-only product composition. It binds
exact records, owner generation, request identity, retrieval policy, ranker
policy, the complete plan receipt, and a bounded monotonic process lease before
final use. This local read decision is not a global-effect product caller.

## 2. Public planning admission

The public facade rejects owner summaries outside the exact requested set,
cardinality excess before normalization, duplicate final-payload identity,
planning time before collection, expired owner observations, and an `abstain`
candidate carrying an effect payload. Finalization and grant-request construction
recheck the original snapshot and owner freshness. All planner outputs remain
`DENY_ALL`.

## 3. Closed planner journal

Typed mutations, raw append, and reopen all cross the same lifecycle validator.
A structurally valid hash chain cannot select an unrecorded decision or reselect
a revoked decision merely by bypassing a typed helper. Exact retries remain
idempotent; conflicting identity reuse fails closed.

## 4. Durable planner store

`PlannerStoreV1` remains an owner-local, authority-free source candidate. The
public wrapper now enforces the following additional invariants around the
versioned frame codec:

- an operating-system-backed owner lock is held for the complete public open,
  backup, and restore windows; the lock file is not deleted for stale takeover;
- store size is bounded before `read_to_end`, and per-record limits are checked
  while scanning fixed frame prefixes;
- a truly incomplete final fixed prefix may be truncated by the codec, but a
  complete prefix that declares a missing body fails closed instead of being
  silently treated as a crash tail;
- any mutation error whose durable outcome may be uncertain permanently poisons
  the current handle; further mutation requires drop and verified reopen;
- compaction treats `retain_last` as a lower bound and preserves every
  non-snapshot identity/decision/revocation/dispatch/terminal record plus the
  latest snapshot needed to interpret the preserved semantic history;
- backup requires a verified checkpoint and holds destination ownership before
  replacement; restore holds shared backup ownership and exclusive destination
  ownership before changing the destination.

The existing core PID lock remains a compatibility layer for the current schema.
All selected product callers must use the public wrapper. A named independent
anchor owner, target-filesystem profile, and two-process crash qualification are
still external gates.

## 5. Durable dispatch and recovery state machine

Dispatch uses one exact operation identity and a stable v2 claim binding. The v2
claim digest excludes attempt time, so a retry at a later time cannot conflict
with the same request merely because its local clock advanced. Existing v1 claim
envelopes remain readable.

The public sequence is:

```text
inspect exact durable operation state
  -> conclusive terminal: return the original receipt unchanged
  -> unresolved claim/indeterminate receipt: query effect owner by identity
  -> no state: validate request expiry and obtain an independent grant
       -> persist exact request/grant/payload claim
       -> revalidate authority immediately before executor invocation
       -> persist terminal or indeterminate observation
```

A retry never redispatches. Reconciliation preserves the original grant digest;
a refreshed authorization cannot be reported as the grant used by the first
attempt. A conclusive receipt can be returned after the original execution
request expires because this path authorizes no new effect.

If final authority revalidation is revoked or indeterminate after the claim is
durable, the wrapper persists a deterministic failed receipt stating that the
executor was not invoked, then returns the authority error. This prevents a
known non-dispatch from becoming a permanent unknown-effect claim. Executor or
transport failure after invocation remains unresolved and must be reconciled.

The public reconciliation entry requires an existing durable claim, rejects a
mismatched grant, never creates a claim, and returns an existing conclusive
terminal receipt without appending a later contradictory observation.

## 6. Read-only organ fanout

`OrganHostV1` remains a trusted compiled-in, synchronous, read-only host—not a
sandbox and not a model/plugin/I/O executor. The receipt-preserving fanout path
returns one stable target slot for every admitted route and distinguishes
`Delivered`, `DeliveredOutputUnavailable`, `Failed`, and `NotAttempted`. The
host retains generation fencing, input/output limits, quarantine, startup
cleanup, and migration rollback semantics.

Blocking handlers, external plugins, model calls, and effectful work require a
separate bounded owner and cannot be admitted by implementing the read-only
trait alone. Product-level fanout retry and downstream target idempotency remain
composition work.

## 7. Qualification matrix

The branch workflow runs the same non-mutating checks against the exact source
head and a deterministic synthetic merge:

- canonical state validation;
- `cargo fmt --check`;
- package regression tests for control plane, Agentd, and NDU;
- all-target compilation;
- strict Clippy with warnings denied;
- clean tracked source and immutable candidate identity capture.

Source tests include request-time and owner-age rejection, effect-free abstain,
closed journal replay, uncertain-handle poisoning, public writer exclusion,
missing-body corruption rejection, semantic compaction, v1/v2 claim recovery,
terminal replay after expiry, no-claim reconciliation rejection, authority
revocation before executor invocation, process reopen, and reconciliation
without redispatch.

A queued, skipped, or historical run is not a pass. Stage booleans remain false
until current exact-head and fixed-merge receipts exist.

## 8. Remaining external work

The candidate deliberately does not assert completion of:

- a named production planner writer and independently retained checkpoint anchor;
- a named effectful product caller, authority adapter, and effect owner using
  the durable protocol end to end;
- two-process kill/restart, disk-full, filesystem-loss, stale-owner, and restore
  qualification on the selected target host;
- semantic garbage collection once non-snapshot operation history reaches the
  configured retention ceiling;
- long-running overload, fair pending-reconciliation scheduling, and product
  backpressure evidence;
- product fanout idempotency for partially delivered organ routes;
- independent semantic acceptance, operator approval, canary, rollback
  rehearsal, activation, promotion, and release.

Those gates require named owners and execution evidence. They cannot be advanced
by source presence or documentation alone.
