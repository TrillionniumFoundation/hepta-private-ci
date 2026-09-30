# control.runtime architecture

## Production responsibility chain

```text
authenticated canonical producer
        ↓
ControlRuntimeOwnerV1
        ↓
trusted-clock freshness check
        ↓
canonical decision envelope
        ↓
crash-consistent PlannerStoreV1 append
        ↓
independent authority request and authorization
        ↓
final-use snapshot / revocation / payload / expiry check
        ↓
guarded effect or OrganHost dispatch
        ↓
exact-attempt terminal receipt or Indeterminate
        ↓
durable reconciliation
```

`ControlRuntimeOwnerV1` is the production composition root. It owns the store writer, execution state machine, authenticated producer ports, trusted clock, authority requests, accepted authorizations, and terminal reconciliation.

## Planning layer

The planner remains advisory and deny-all. Snapshot collection, candidate preparation, NDU evaluation, finalization, and grant-request construction do not themselves confer effect authority.

## Durability layer

`PlannerJournalV1` is a bounded semantic journal. Raw mutation is private; both append and reopen enforce the Decision → SelectedPlan → Revocation state machine.

`PlannerStoreV1` is the crash-consistent byte store. Product records carry exact operation identity and are replayed into the execution state machine at owner startup. A byte-valid but semantically out-of-order store is rejected.

## Lifecycle layer

Runtime-module promotion uses a verifier-issued opaque token binding module identity, generation, implementation and artifact digests, dependency graph, serving topology, source commit, policy epoch, selection, canary, handoff, and freshness window. Final promotion rechecks the registry and trusted time.

## Organ runtime layer

The production OrganHost profile is synchronous and acyclic. Graph validation precedes route indexing. Feedback and buffered scheduling are rejected until a bounded scheduler exists. Dispatch returns per-target results and poisons the host after panic or post-return budget/deadline violations.

## Embodiment layers

Synthetic simulator support is in-tree. HIL and physical-device adapters are separate qualification layers and are not production-qualified by this module's source tests.
