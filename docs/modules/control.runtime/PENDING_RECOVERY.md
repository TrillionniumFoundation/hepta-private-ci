# `control.runtime` bounded pending-recovery protocol

## Status and source of truth

This document specifies the source-level recovery protocol around durable planner dispatch claims. It does not certify maturity. `docs/modules/control.runtime/CURRENT_STATE.json` remains the canonical status source; exact-source, fixed-merge, selected-target-host, independent acceptance, activation and release gates remain separate facts.

## Preserved ownership boundaries

The planning kernel remains advisory. Control owns coherent snapshot collection and resource-feasibility filtering. NDU owns utility evaluation. A separate authority owner issues and revalidates final-payload-bound grants. The effect owner alone executes or observes an operation. Neither a plan, a grant request, a pending projection nor a fanout continuation grants execution authority; each remains `DENY_ALL`.

`PlannerStoreV1` remains the single durable owner for dispatch claims and terminal/reconciliation observations. `pending_dispatches_page` is an inherent read-only projection over that same owner. It does not introduce a second journal, executor, queue or recovery database.

## Pending inventory contract

`PlannerStoreV1::pending_dispatches_page(after_sequence, limit)` accepts a page limit from 1 through 256. Before returning any result it:

1. rejects a store handle whose durable mutation outcome is uncertain;
2. decodes every canonical v1/v2 dispatch claim and rejects duplicate operation identities;
3. decodes terminal and reconciliation records through the canonical execution codec;
4. requires every receipt to follow an exact claim and to preserve request, final-payload and original-grant identity;
5. rejects duplicate initial receipts, receipt-before-claim ordering and reconciliation after a conclusive result;
6. excludes operations whose latest observation is `Succeeded` or `Failed`;
7. keeps claims with no observation and claims whose latest observation is `Indeterminate`;
8. returns only bounded evidence carrying `AuthorityPosture::DENY_ALL`.

The cursor is the last returned claim sequence. The next call starts at the first unresolved claim with a greater sequence and wraps to the beginning when necessary. This gives a bounded recovery controller round-robin progress without treating the inventory as permission to redispatch.

Each item binds the claim sequence, immutable claim-record digest, stable operation identity, exact request digest, original grant digest and final-payload digest. A product controller must resolve the original request from an independently owned exact binding and invoke only the existing observation-only reconciliation port. Missing request material or an unknown downstream result remains unresolved; it is not converted into permission for a new execution.

## Existing bounded driver

`reconcile_pending_dispatches_v1(store, after_sequence, limit, resolver, executor)`
uses this inventory and the existing execution state machine. Its resolver must
implement `PlannerPendingRequestResolverV1` over an independently owned exact
request ledger. The driver verifies the operation identity, complete request
digest and final payload before contacting the effect owner's observation-only
port, and preserves the original durable grant.

Missing or indeterminate request material, resolver errors and binding mismatches
become per-item evidence; they do not authorize execution or prevent the next
item from being considered. Store/recovery errors stop the pass immediately.
Every batch and item remains `DENY_ALL`. Product scheduling, backoff, request
ledger retention and the real effect adapter still require a named product owner;
the generic driver does not establish that product composition.

## First observation after an interrupted dispatch

A durable claim may have no initial observation after process loss or a transport
error. The effect owner is queried only through its observation-only reconciliation
port. The returned observation is stored as the initial terminal frame for that
claim; subsequent observations of an indeterminate initial result use reconciliation
frames. This preserves the same closed transition validator across repeated
reopen, including legacy v1 claims, without redispatching the operation.

Existing invalid transition records remain rejected by the same validator.
Recovery of such a store requires independently retained claim/anchor bindings
and authoritative effect-owner evidence through the product recovery protocol.

The public reconciliation entry checks the supplied grant against the original
claim even when a conclusive receipt already exists. A matching retry returns the
unchanged receipt; a mismatched grant is rejected before any effect-owner call.

## Abnormal-process regressions

The repository includes a separate binary fixture and integration tests for boundaries that an in-process destructor test cannot establish:

- a live child process holds the operating-system writer lock and a second opener is rejected;
- after the child is killed abnormally, the lock is reclaimed and the store can reopen;
- a child aborts after log sync but before in-memory publication or normal `Drop`, and the synced frame is recovered on reopen;
- backup restoration is rejected while another process owns the destination and succeeds only after that owner exits.

These are repository source cases. Their presence does not set `targetHostRecoveryPassed`; that gate requires retained results for the selected target host and the fixed candidate under review.

## Organ fanout interaction

The synchronous organ host remains a trusted in-process, read-only host rather than a sandbox. Its complete per-target receipt and independently retained evidence digest identify the successful prefix, first incomplete target and unattempted suffix. A continuation remains `DENY_ALL`; actual retry, downstream idempotency, backpressure, model calls, plugins and blocking work belong to separately bounded product owners.

## Product composition still required

A production recovery controller must compose the existing owners rather than bypass them. It needs bounded polling/backoff, an exact request resolver, fair scheduling over the pending cursor, effect-owner reconciliation, terminal persistence through `PlannerStoreV1`, metrics for pending age and reconciliation latency, and shutdown behavior that does not discard accepted work. It must never infer that timeout, process loss, `NotFound` or missing evidence means an operation was not executed.

Independent anchor ownership, disk-full and filesystem-loss exercises, backup rollback detection, sustained-overload qualification, selected-target-host evidence, independent semantic review, operator acceptance, canary, activation, promotion and release remain external gates.
