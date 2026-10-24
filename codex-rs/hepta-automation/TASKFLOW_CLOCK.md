# Live original-clock TaskFlow effect admission

The existing caller-time APIs accept explicit logical `now_ms` values. Their
atomic SQLite admission checks current cancellation, fence, step and payload
state, but a timestamp captured before an await is not fresh expiry evidence.
Those compatibility APIs remain available with their existing time semantics.

The optional `TaskFlowClockClaim` path obtains time from the **same existing
FinalUseAuthority object** used for effect authorization. It creates no clock,
grant, signing key, database, frontier or retry authority. The authority's new
`observe_now_unix_ms` method forwards its configured clock and propagates clock
failure. A HostAuthorityClock observation may perform I/O and renew its own
existing protected time frontier; it does not consume a FinalUse nonce or alter
that authority's revocation frontier. A compatibility SystemAuthorityClock
retains its documented trust limitations.

## Typed live provenance

`AutomationStore::claim_taskflow_run_with_authority_clock` returns an opaque,
non-serializable `TaskFlowClockClaim` borrowing the exact original store and
authority. It invokes the original lease implementation and event history.
Under `BEGIN IMMEDIATE`, it requires an original-owner **no-lease** state and
samples the original clock after awaited validation queries before committing
the new lease. It samples again after commit; a lease that expired during
persistence remains recorded but produces no usable live claim handle.

Every pre-existing lease tuple is refused. The code cannot infer that a legacy
lease using logical time 130 has expired merely because a Unix clock reports a
larger number. It cannot attach the typed claim to an active lease, recreate it
from a row after restart, or use an old apparently expired lease as unproven
takeover authority. Fresh entry needs a new run or a lease legitimately cleared
or requeued by the original owner. The old claim command identity remains
unique in the original `taskflow_events` table, preventing same epoch/generation
lease ABA even if a later proposed fence and deadline look identical. The new
typed claim path also checks the latest immutable lease event's generation and
epoch before appending: clearing the projection does not permit a non-advancing
generation under a different epoch. This enforces the existing history
verifier's rule before the new typed claim is returned.

The typed handle exposes the immutable original claim receipt and fence. Its
`execute_authorized_effect` and `execute_authorized_effect_async` methods select
the same original store and authority, and still require the original signed
grant, exact wire payload, binding and command identity. A caller cannot replace
the handle's store, authority, run, generation, fence or deadline. The handle is
a time-domain/lease binding, not an effect grant.

## Two fresh checks and original recovery

The strict effect path shares the original dispatch implementation. In the same
SQLite admission transaction, it validates the current run/definition/step,
the exact typed lease tuple, and then samples the original authority clock
after the awaited reads. The immutable attempt receives that admission time.
A lease that expired while waiting for the database lock cannot be admitted.

After insert and commit, the path resamples inside the original active-effect
closure, before invoking the registered driver. It rejects a sample older than
the admitted timestamp or outside either the TaskFlow lease or signed grant
window. Rechecking the grant window also matters because this additional clock
read can itself perform protected I/O after FinalUse's first guarded check.
No authority mutex is held across SQLite awaits; the original active-effect
fence continues to order revocation against an entered effect. A configured
clock callback must not reenter the same AutomationStore transaction.

Expiry before driver entry produces original-owner `ProvenAbsent` evidence and
the existing requeue path, with the nonce still consumed. It is not cancellation
or proof that any remote process stopped. A failure to retain that evidence,
future cancellation, or unavailable observation time preserves the original
unresolved attempt. After actual driver entry, later expiry or a failed time
observation never fabricates absence, issues another key, refunds a grant or
reports a stop acknowledgement. Recovery remains through the original attempt
and registered provider evidence.

The guarantee is registered **driver entry**, matching the existing FinalUse
consumer contract. A driver may do further asynchronous work before physical
network submission. This path is not a continuously checked lease, an atomic
clock/network action, or retroactive cancellation of entered work. A stricter
physical transport deadline would require that original transport owner to
consume the same restricted entry permission at its own submission boundary.

## Companion correction: retain admitted-effect recovery ownership

This is a distinct original-owner correction, not a consequence of choosing a
clock. The prior same-transaction guard covered ordinary `Cancel` only. An
ordinary `Succeed` or `Fail` could clear a committed effect's exact recovery
fence before driver entry; `Wait` and `Retry` retained the tuple but moved the
run outside the existing provider-observation settlement path. A generic step
receipt could also consume the claimed step before actual provider evidence.

The existing TaskFlow transaction now consults the original immutable effect
ledger for every generic run mutation. No parallel owner, table or lock is
added. `Indeterminate` remains permitted because it preserves the exact tuple.
The original authorized-effect settlement alone selects a crate-private
reconciliation entry; the shared transaction still validates actual retained
ledger evidence and matching settled step receipts. A digest supplied directly
to a generic command is not equivalent to that evidence.

| Original mutation | Admitted-effect behavior |
| --- | --- |
| `Start` | Refuses any non-absent admitted effect. Historical, fully settled absence remains valid across a legitimate new generation. |
| `Wait`, including a changed resume node | Refuses pending/non-absent effects, preserving the original settlement-compatible state and graph position. |
| `Resume`, including sticky cancellation | Uses the same guard before changing state or clearing a lease. |
| `Retry` | Uses the same guard before moving to retry-backoff. No retry authority is created. |
| Generic `Cancel`, `Succeed`, `Fail` | Refuse non-absent effects; no terminal assertion may erase recovery ownership. |
| `Indeterminate` | Keeps the original lease/fence. The existing evidence-owned quarantine still accepts expired historical ownership. |
| Generic `Reconcile` | Refuses runs with admitted effects; non-effect TaskFlow behavior remains unchanged. |
| Evidence-owned `Reconcile` | Requires exactly one non-absent terminal effect, the exact retained evidence/outcome, and settled original step receipts for every admitted attempt before clearing the run lease. |
| Private `RequeueProvenAbsent`, `CancelProvenAbsent` | Require all admitted attempts to have original absence observations and matching settled absence step receipts, plus the supplied proof to match retained evidence. A missing observation is never absence. |
| Lease replay/takeover | Active same-fence legacy replay does not mutate ownership. Existing pending-effect checks prevent takeover; the new strict mode additionally refuses every pre-existing lease tuple and requires advancing immutable generation history. |
| Step `prepare`, `claim` | Existing immutable identity/state checks prevent rewriting an already claimed `(run, step, attempt)`. |
| Step `record`, `reconcile`, private absence settlement | If that exact effect attempt exists, require its actual retained ledger observation and digest before changing the claimed/recorded step. Non-effect step semantics remain unchanged. |

Historical absent steps retain their original fences. The guard verifies their
immutable chain and exact admitted intent, payload and absence evidence; it
does not pretend an old settled fence equals the current generation. Unresolved
or non-absent effects still require their current exact recovery tuple.

**Generic multi-effect aggregation remains unsupported.** The original schema
can admit different effects under one run. If two or more non-absent effects
exist, this correction keeps the run `Indeterminate` even after their individual
terminal observations and step receipts are retained. It does not choose the
last completion's outcome, grant a retry, or release another effect's fence.
The original per-attempt recovery APIs remain available, but run settlement
returns a conflict until an actual aggregate-outcome owner contract is defined.
The native status adapter uses a separate pre-admitted effect run for each
tool operation and does not claim to supply this missing aggregation policy.
One actual effect plus fully settled historical/parallel absence can settle.

These guards add reads of existing attempt/step evidence in the same mutation
transaction. This source change does not establish their performance cost.
The legacy lease-takeover query can still conservatively refuse a formerly
indeterminate attempt later reconciled as absent; this stage does not weaken
that existing availability restriction or infer an unsafe takeover.

## Restart and activation limits

Current TaskFlow records contain no persisted clock identity, and AuthorityClock
does not expose a stable authenticated domain identifier. The live typed handle
therefore cannot be reconstructed after process loss. This availability
restriction is intentional. Existing-attempt reconciliation requires no handle
and remains available; fresh dispatch cannot fall back to a caller assertion or
an unproven timestamp comparison.

Persisting an authenticated time-domain binding for fresh dispatch on an old
lease across restart would need a separate reviewed extension to the **original
database** and a real host-supplied stable clock identity. This module creates
neither. Agentd's current compatibility SystemAuthorityClock bootstrap also does
not establish protected-clock production attachment. Adding this library path
does not activate a deployment or establish native/Codex tool-policy parity.

## Verification scope

The `effect_clock` tests exercise actual original SQLite stores and FinalUse
state with an explicit controlled implementation of the existing AuthorityClock
and test-only signed grants. Their provider fixture writes exact bytes once to
an owned file and uses the original observation/recovery APIs. They cover lock
contention, both synchronous and asynchronous entry, expiry after commit,
entered-effect recovery, time unavailability, refusal to wrap existing leases,
same-fence ABA, no fallback, and unchanged legacy overflow validation.
The companion tests use two actual database connections and both serial orders
for generic run transitions. They verify that forged step/run receipts cannot
preempt an admitted effect, that successor generation can start after genuine
settled absence, and that two actual file effects retain both receipts and the
run fence instead of claiming an aggregate result. A separate absent-versus-
entered-effect race verifies that one absence proof cannot requeue the other.

These are owner-contract regressions. They are not a production clock
attestation, live remote-provider test, controller-crash qualification, general
exactly-once guarantee, model A/B result or deployment approval.
