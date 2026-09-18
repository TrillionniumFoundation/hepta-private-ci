# SecretLease lifecycle design

## Contract

The dynamic lease control-plane has three provider effects:

`request_secret_lease(request, final_use_grant, registry, consumer)`

`renew_secret_lease(request, final_use_grant, registry)`

`revoke_secret_lease(request, final_use_grant, registry)`

Every effect is bound to subject, consumer, provider origin, operation identity,
resource identity and semantic payload digest. Reusing an operation ID with
different semantics fails with `OperationConflict`.

## State machine

Issue:

`IssuePending -> Active | Unknown | NotApplied`

Renew:

`Active -> RenewPending -> Active | Unknown -> Active`

Revoke:

`Active -> RevokePending -> Revoked | Unknown -> Revoked | Active`

`Unknown` is mandatory whenever the provider may have committed but the host
cannot prove the result. An unknown operation is never automatically reissued.

`ReconciliationObservation::Active` records the provider lease identity,
renewability and expiry observed by a trusted provider-specific reconciler.
`Revoked` records terminal revocation. `NotApplied` terminates a failed
issuance or restores an existing lease to `Active` after a proven-not-applied
renew/revoke.

## Dynamic secret data

The generic adapter accepts bounded JSON request parameters but persists only
their semantic digest. Provider response secret data must be a bounded string
map. The complete response buffer and decoded string values are zeroized on
drop. Secret data is serialized into a zeroizing buffer and delivered only to
the final-use callback; only its SHA-256 digest may enter lease metadata.

A dynamic lease response whose lease identity, duration, body or semantics
cannot be validated after dispatch is treated as ambiguous, not as proof that
nothing happened.

## TTL and retries

A caller supplies `max_ttl_seconds`; source currently caps it at 86,400
seconds. A provider response exceeding the caller bound becomes
`Indeterminate`. Renewal increments are also capped at 86,400 seconds.

Provider mutations have no automatic retry. Retry is allowed only as a new
operation after trusted reconciliation proves the previous effect was not
applied.

## Authority timing

The final-use grant is claimed durably before dispatch. For issuance, provider
credential creation may already have occurred before a later revocation update;
the adapter therefore persists the provider lease observation before releasing
secret bytes, then rechecks authority immediately before callback entry.

Renew/revoke have no secret-release callback. Their provider mutation is the
effect, so the single-use claim is the admission fence. Cancellation or
revocation after network dispatch cannot retroactively undo the provider
operation; an uncertain result must be reconciled.
