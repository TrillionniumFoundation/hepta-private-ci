# channel.matrix durable state machine

The authoritative send state is `matrix_dispatch_ledger` in `MatrixDurableStore`. `send_observer.rs` must never regain an independent map or sender.

## 1. External model and native encoding

The conceptual states are:

```text
Prepared -> Authorized -> Claimed -> Dispatching -> TransportAccepted -> Confirmed -> Redacted
                 \             \              \-> Indeterminate
                  \             \-> Revoked / Expired / Canceled
                   \-> PermanentlyRejected
```

The current native durable encoding deliberately compresses pre-effect phases:

| Conceptual phase | Durable representation |
|---|---|
| Prepared / Authorized / Claimed / Dispatching | dispatch row `dispatched` plus immutable per-attempt authority claim and append-only `dispatch_started` observation |
| TransportAccepted | `accepted` with unique `accepted_event_id` |
| Indeterminate | `indeterminate`; if an earlier event id is known, state remains `accepted` |
| Confirmed | `succeeded` with trusted homeserver event, authority claim and terminal timestamp |
| PermanentlyRejected | `failed`, only when no earlier effect may have crossed the boundary |
| Redacted | `redacted` with trusted redaction observation |
| Legacy observed without current gate | `observed_unqualified`; terminal evidence, not qualified success |

`Canceled`, `Expired` and `Revoked` are pre-entry dispositions. They must not be represented as remote failure. If cancellation or expiry occurs after external-effect entry, the result is unknown and follows the indeterminate path.

## 2. Identity invariants

For every logical send:

- `operation_id = "matrix.send:" + stable_txn_id`;
- `stable_txn_id` never changes across retries, restart or reconciliation;
- operation ID and stable transaction ID are unique;
- accepted and terminal event IDs are globally unique where present;
- room ID, binding revision, Matrix-plane generation and payload digest are immutable;
- each attempt has at most one immutable authority claim;
- a grant ID may authorize only one attempt;
- exact duplicate observations are idempotent; semantic conflicts fail closed.

## 3. Allowed transitions

| Current | Trigger | Next | Required evidence |
|---|---|---|---|
| absent | claimed outbox row | dispatched | stable transaction, canonical payload digest, attempt > 0 |
| dispatched | durable authority claim | dispatched | exact operation/scope/payload/attempt, signed-grant claim frontier |
| dispatched | transport returns event ID | accepted | append-only transport observation |
| dispatched | timeout/reset/unknown result | indeterminate | append-only indeterminate observation |
| dispatched | proven pre-effect permanent rejection | failed | no prior accepted event and terminal timestamp |
| accepted | retry timeout/rejection | accepted | preserve prior effect evidence; never downgrade to failed |
| dispatched/accepted/indeterminate | matching `/sync` event | succeeded | same transaction, room and event; exact attempt authority claim |
| dispatched/accepted/indeterminate | matching `/sync` event without current claim | observed_unqualified | explicit compatibility-only evidence |
| succeeded/observed_unqualified | matching redaction | redacted or observed_unqualified | target event and redaction digest |
| any terminal | exact duplicate observation | unchanged | full semantic equality |
| any terminal | contradictory observation | error | no state mutation |

## 4. Monotonicity rules

- Terminal observations never reopen a send.
- `accepted` or `indeterminate` never becomes `failed` merely because retries were exhausted.
- A later permanent rejection cannot erase an earlier transport acceptance.
- `succeeded` requires a trusted homeserver observation; SDK/HTTP return is insufficient.
- Redaction is monotonic and cannot resurrect payload or context.
- A newer binding/session generation fences earlier attempts.
- An authority claim remains consumed even when dispatch is canceled, expires or becomes unknown.

## 5. Transaction boundaries

1. Preparing a dispatch row and appending `dispatch_started` share one SQLite transaction.
2. Recording each transport result and its observation share one transaction.
3. `/sync` reconciliation, terminal dispatch update, outbox settlement and sync checkpoint advancement share one transaction.
4. Redaction mutation, dispatch redaction and checkpoint advancement share one transaction.
5. Authority nonce burn occurs in the kernel owner before the Matrix claim is recorded. Failure to persist the Matrix evidence fails closed; it never refunds the nonce.

## 6. Crash cuts

| Crash point | Recovery rule |
|---|---|
| before durable dispatch | outbox lease expires; same stable transaction is reclaimed |
| after dispatch row, before grant | no network effect; obtain a fresh grant on next attempt |
| after kernel claim, before Matrix claim | nonce remains burned; no network effect; retry uses a fresh grant |
| after Matrix claim, before effect entry | no network effect; retry uses a fresh grant and keeps immutable history |
| after effect entry, before response | mark/recover as indeterminate; never synthesize failure |
| after event ID, before local observation | retry/reconcile with same transaction ID; `/sync` settles terminality |
| after `/sync` mutation, before commit | whole transaction rolls back, including cursor; event is replayed safely |
| after terminal commit | exact duplicates are idempotent |

## 7. Capacity

The unresolved dispatch ledger is bounded at 4,096 entries. Outbox claim batches are bounded, retries are bounded, and exhausted unknown effects park for reconciliation rather than consuming CPU in a hot loop. Capacity exhaustion rejects new unresolved work without overwriting existing evidence.
