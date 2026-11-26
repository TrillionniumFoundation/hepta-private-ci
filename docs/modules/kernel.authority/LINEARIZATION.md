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
verifier acquires the authority mutex before sampling the owner-bound clock, so
a lease that expires while waiting for the mutex is denied. The mutex is
released before the already-selected bounded consumer runs. A revocation or
replacement committed before that point denies entry. A change committed after
that point is ordered after entry and does not retroactively undo an
already-entered synchronous effect.

Production general-lease consumers use `AuthorityDispatchBinding`. The verifier
creates that one-shot, non-serializable binding only after the exact live check;
`dispatch` repeats the check and consumes the binding at the owner mutation. A
product must not retain a verified token and later call an unrelated mutation.
The extension and canonical-boundary inventories close the set of wrappers and
product callers.

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

`with_verified_effect`, `with_verified_use_async` and
`with_verified_use_async_with_witness` instead retain an active-effect fence
without holding the mutex over provider work. A trusted revocation update that
finds an active effect returns `DispatchInProgress`, but first persists the
exact monotonic head as `pending_revocations` and advances the external
frontier. While pending, new claims and every new entry path return
`RevocationPending`. After the active effect drains, the host retries that head
or a strictly stronger monotonic head; successful commit atomically publishes
the committed head and clears pending.

The committed head, optional pending head and nonce journal are bound by the
FinalUse frontier V2 digest. The pending head is therefore durable and cannot be
weakened by restart. It is not merely a process-local bit and product hosts must
not substitute an unauthenticated feed reread for kernel recovery.

## Revocation crash windows

FinalUse uses external-frontier-first ordering. For a pending or committed
revocation transition:

1. compare-and-set the rollback-independent external frontier;
2. fsync and atomically replace the local V4 snapshot;
3. publish the new in-memory state.

A crash after step 1 can leave the external frontier ahead of the local
snapshot. Recovery is allowed only through the key-ring recovery constructor
and only when an independently authenticated revocation head reconstructs a
candidate V2 frontier exactly equal to the already-stored external frontier.
The recovery path may complete the local snapshot; it never advances or invents
the external frontier. Any other mismatch is `AntiRollbackViolation`.

The candidate-bound crash matrix covers:

- persisted pending head followed by process restart;
- external pending frontier with the local snapshot still committed;
- external committed frontier with the local snapshot still pending;
- rejection of admission while pending and rejection of the revoked grant after
  exact commit.

Legacy V1–V3 snapshots migrate to V4 without introducing a pending head. A
runtime frontier-format migration must prove semantic equality before any
frontier generation changes; it may not silently reset nonce or revocation
state.

## Distribution freshness

A valid signature on a revocation head is insufficient by itself.
`FinalUseRevocationUpdate` V2 signs `issued_at_unix_ms` and
`expires_at_unix_ms`. A host rejects a not-yet-valid or stale head. The
registered Bao host begins with no freshness authority and denies provider
dispatch until it has ingested a current signed head. It samples freshness
again at the registered consumer boundary after provider I/O. That second
successful check is the revocation-feed freshness linearization point for
secret release: a feed that expires while the request is in flight cannot
release the secret.

This is the repository partition policy for that host: stale revocation
knowledge stops new affected effects. Transport fanout and fleet convergence
remain external deployment responsibilities.

## Crash and uncertainty rule

Once a local irreversible boundary has been entered, a crash, cancellation,
panic or lost acknowledgement is not evidence that the effect did not happen.
Callers preserve an indeterminate outcome and reconcile using the destination
owner's evidence before issuing replacement authority. The TaskFlow product
path persists the canonical non-authorizing entry witness with the durable
attempt before provider contact; restart uses that same attempt identity and
never treats the witness as authority to retry.
