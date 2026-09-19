# kernel.authority linearization contract

This document is normative for the repository-controlled authority primitives.

## General lease use

`AuthorityLeaseVerifier::verify_use` checks the exact current lease revision,
binding, epoch, revocation and owner-bound trusted time and returns an opaque,
non-serializable `LeaseVerifiedUseToken`.

`AuthorityLeaseVerifier::with_verified_use` rechecks the token against the
**current stored lease record** and current revocation/time state. A replaced
lease invalidates an older token even when its former binding was identical.

The successful final validation is the consumer-entry linearization point. The
authority mutex is released before the already-selected bounded consumer runs.
A revocation or replacement committed before that point denies entry. A change
committed after that point is ordered after entry and does not retroactively
undo an already-entered synchronous effect.

## FinalUse delivery

`claim_final_use` validates issuer signature and exact binding, persists the
single-use nonce, and returns `VerifiedUseToken`. Claim is dispatch admission,
not proof of effect completion.

`deliver_final_use` / `with_verified_use` revalidate owner, exact binding,
epoch, revocation and trusted time. Their successful validation is the
consumer-entry linearization point and the mutex is then released before
consumer code.

For a caller that must make revocation linearize with a short local irreversible
transition, `dispatch_final_use` / `with_dispatch_boundary` keeps the mutex
only across that bounded local transition. The callback must only publish
durable intent or cross an already-selected local adapter/worker boundary and
return promptly. It must not contain network waits, provider terminal waits,
reconciliation loops or arbitrary plugin/user code.

## Distribution freshness

A valid signature on a revocation head is insufficient by itself.
`FinalUseRevocationUpdate` V2 signs `issued_at_unix_ms` and
`expires_at_unix_ms`. A host rejects a not-yet-valid or stale head. The
registered Bao host begins with no freshness authority and denies final secret
use until it has ingested a current signed head; it denies new final use again
when that freshness window expires.

This is the repository partition policy for that host: stale revocation
knowledge stops new affected effects. Transport fanout and fleet convergence
remain external deployment responsibilities.

## Crash and uncertainty rule

Once a local irreversible boundary has been entered, a crash, cancellation,
panic or lost acknowledgement is not evidence that the effect did not happen.
Callers preserve an indeterminate outcome and reconcile using the destination
owner's evidence before issuing replacement authority.
