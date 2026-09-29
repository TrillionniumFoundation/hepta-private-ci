# ADR-001: durable operation state and recovery dispositions

- **Status:** accepted for source implementation
- **Scope:** `intelligence.control` product integration through `kernel.operations`
- **Decision owners:** `intelligence-platform`, `qualification-plane`

## Context

The product route crosses admission, a leased owner, a provider effect boundary,
durable acknowledgement and destination reconciliation. Treating every error as
"retry" can duplicate a physical effect. Treating every error as terminal can
strand a safe pre-dispatch operation. Callers therefore need one typed recovery
answer derived from the authoritative durable state and error, rather than local
string matching.

## Decision

`kernel.operations` is the state authority. Its existing durable identity,
operation state, outbox lease and `DispatchEffect` remain the canonical model.
The public `DurableFailureClass` and `RecoveryDisposition` projections provide
the only generic caller actions:

| Disposition | Meaning |
|---|---|
| `Reject` | The request, authority, identity or terminal state forbids reuse. |
| `RetrySameIdentity` | The provider is known not to have been entered; retry only the same durable identity. |
| `RetryAfterCapacity` | No effect was admitted; retry after bounded capacity becomes available. |
| `ReconcileOnly` | The durable commit or provider outcome may be unknown; observe the same identity before any new effect. |
| `ReplaceOwner` | The caller is fenced; only a successor generation may resume. |
| `RepairClockOrStore` | Clock rollback or corruption requires operator repair, not request-level retry. |

`Prepared` and `DispatchEffect::NotDispatched` are the only generic states that
project to `RetrySameIdentity`. `Dispatching`, `Dispatched`, `Indeterminate`, an
unavailable durable store, a lost lease and an invalid transition project to
`ReconcileOnly`. This intentionally keeps provider-entered and durable-result-
unknown cases out of ordinary retry loops.

Durable Unix time is supplied through `DurableOperationClock`. Every writer
samples it only after acquiring SQLite `BEGIN IMMEDIATE`; writer serialization
therefore orders timestamp observations. Rollback against durable state still
fails closed and is never clamped to an invented time.

## Consequences

- Product callers switch on typed dispositions, not error text.
- Adding a new durable error requires an explicit recovery classification.
- A request timeout does not imply that the underlying effect did not enter.
- A successor generation adopts or reconciles the same identity; it does not
  manufacture a replacement operation.
- Monotonic elapsed-time budgets remain separate from persisted Unix time.

## Verification

`recovery_disposition_is_effect_boundary_aware` checks the retry/reconcile
boundary. `writer_samples_clock_after_immediate_transaction_admission` holds a
real SQLite writer lock and proves that a blocked writer samples the injected
clock only after admission. The independent qualification lane also executes the
multi-writer durable-store suite on source-head and synthetic-merge checkouts.
