# Kernel operations bounded reference model V1

## State machine

| Current state | Command | Required checks | Next state |
| --- | --- | --- | --- |
| absent | `begin` | nonzero payload digest, capacity | `Pending` |
| `Pending` | `authorize` | exact reference witness, unexpired | `Authorized` |
| `Authorized` | `record_dispatch` | nonzero dispatch digest | `Dispatched` |
| `Dispatched` | `mark_indeterminate` | nonzero reason digest | `Indeterminate` |
| `Dispatched`/`Indeterminate` | `observe_terminal` | current owner generation, nonzero evidence | `Applied`, `NotApplied` or `Quarantined` |

Exact replays return the existing state without revision movement. Reusing an
identity with changed payload, witness, dispatch or terminal semantics conflicts
or is terminally rejected.

## Outbox model

`enqueue` is idempotent for identical intent identity and payload. `claim` is
idempotent only for the same owner generation. `acknowledge` requires the same
generation and a nonzero digest; exact acknowledgement replay is idempotent.

## Bounds

Both ledgers default to at most 16,384 records and clamp configured model
capacity to that ceiling. Capacity rejection happens before visible mutation.

## Explicit omissions

There is no persistence, claim expiry, higher-generation takeover, background
worker, atomic co-commit with a domain store or external terminal observer.
Those are durable-backend requirements, not properties of this oracle.
