# Kernel operations bounded reference model V1

## Reference witness binding

`ReferenceAuthorityWitness::expected_digest` uses the domain
`hepta.kernel.operations.reference-authority-witness.v1\0` and binds the exact
operation identifier, final payload digest, authority generation and expiry.
`ReferenceAuthorityWitness::new` rejects a supplied digest that does not equal
that canonical value. The value remains deterministic reference evidence only;
it is not a signature, caller authentication or a production grant.

Every `authorize` call, including an apparent replay of an already authorized
record, revalidates the operation/payload binding and requires
`now_unix_ms < expires_at_unix_ms`. A stale, payload-drifted or operation-drifted
witness cannot be accepted through the idempotent branch.

## State machine

| Current state | Command | Required checks | Next state |
| --- | --- | --- | --- |
| absent | `begin` | nonzero payload digest, capacity | `Pending` |
| `Pending` | `authorize` | exact canonical reference-witness tuple, unexpired | `Authorized` |
| `Authorized` | `authorize` replay | exact canonical tuple, same generation/digest, still unexpired | unchanged |
| `Authorized` | `record_dispatch` | nonzero dispatch digest | `Dispatched` |
| `Dispatched` | `mark_indeterminate` | nonzero reason digest | `Indeterminate` |
| `Dispatched`/`Indeterminate` | `observe_terminal` | current owner generation, nonzero evidence | `Applied`, `NotApplied` or `Quarantined` |

Exact replays return the existing state without revision movement. Reusing an
identity with changed payload, witness, dispatch or terminal semantics conflicts
or is terminally rejected.

## Outbox model

`enqueue` is idempotent for identical intent identity and payload. `claim` is
idempotent only for the same owner generation. `acknowledge` requires the same
generation and a nonzero digest. The acknowledged state persists both values;
terminal replay is idempotent only for the exact
`(owner_generation, acknowledgement_digest)` tuple. A different generation is
stale and a changed digest conflicts.

## Bounds

Both ledgers default to at most 16,384 records and clamp configured model
capacity to that ceiling. Capacity rejection happens before visible mutation.

## Explicit omissions

There is no persistence, claim expiry, higher-generation takeover, background
worker, atomic co-commit with a domain store or external terminal observer.
Those are durable-backend requirements, not properties of this oracle.
