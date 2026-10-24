# Original TaskFlow effect-admission serialization

The immutable `taskflow_effect_dispatch_attempts` row is the original owner's
linearization point for an admitted provider contact. Its insertion now holds
an SQLite `BEGIN IMMEDIATE` transaction while checking the current run and
claimed step, their original event chains, definition/intent/payload bindings,
generation/fence, cancellation state and caller-owned lease timestamp. The
transaction commits before entering the original final-use provider boundary.
Both synchronous and asynchronous authorized dispatch use that same path.

If a separate owner connection commits cancellation, lease takeover or a step
observation first, the new transaction sees that state and refuses admission;
the provider driver is never called. The original signed nonce may already
have been consumed before the failed SQLite admission. It is deliberately not
refunded, and no fresh grant or attempt is generated automatically.

If the immutable attempt commits first, an ordinary TaskFlow `Cancel` command
must not report terminal cancellation or clear the original reconciliation
fence. That command now checks admitted attempts in its own existing SQLite
transaction and explicitly rejects an effect without authoritative proven
absence. This also covers provider evidence retained just before its terminal
TaskFlow projection. The existing owner already rejects lease takeover while
provider-contact evidence remains unresolved. Original status/reconciliation
paths remain responsible for settling the effect under its original key.

Legacy TaskFlow exposes no separate cancel-request transition. This change
therefore uses explicit rejection and preserves the existing run/fence; it
does not invent a cancellation ACK or an additional request ledger. The native
agent's separately existing TurnOwner retains its CancelRequested cursor.

## Time boundary

`now_ms` remains the existing caller-owned TaskFlow timestamp. It is checked
again inside the admission transaction, but a value captured before waiting is
not fresh wall-clock evidence after a long wait. This patch establishes
serialization against committed run/step/cancellation/generation changes; it
does **not** claim to close elapsed TaskFlow lease expiry for a stale timestamp.
No second time authority is introduced. Original FinalUseAuthority continues
to resample its configured clock after nonce persistence and again at physical
provider entry, preserving its own grant-expiry/revocation enforcement.

## Scoped regression evidence

The added tests open two independent AutomationStores on the same isolated
database and use the original configurable authority clock as a deterministic
fixture barrier before insertion or after committed insertion/before provider
entry. Cancellation, takeover and step-observation-first cases must produce
zero file effects and no immutable attempt. The insertion-first case must
reject terminal Cancel and takeover, preserve uncertainty, perform one
controlled file effect and reconcile that same attempt later. A separate test
checks rejection at the original caller-declared lease deadline. These tests
exercise original owner APIs and actual SQLite connections; no adapter mutex
supplies the serialization and no production authority is activated.

The private ledger fixture is also corrected to prepare and claim its actual
step before inserting contact evidence. There is no schema migration, new
store, new authority, deployed runtime change or retry path.
