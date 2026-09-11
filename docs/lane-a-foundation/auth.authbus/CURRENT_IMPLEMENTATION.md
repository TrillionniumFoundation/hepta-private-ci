# `auth.authbus` current implementation

## Current executable contract

`codex-rs/hepta-authbus` is a bounded process-local replay verifier for
**preverified** envelopes. It does not authenticate a caller or verify a
signature. The trusted host supplies issuer identity, key epoch, current time
and revocation state separately from the envelope.

The replay key is `(issuer, key epoch, subject, scope digest)`. Within that key,
sequence numbers must increase. Scope, payload and signature-reference digests
must be nonzero; expected scope/payload must match; expiry and trusted
revocation fail closed. Successful receipts always carry
`AuthorityPosture::DENY_ALL`.

## Public symbols and source bindings

- `PreverifiedAuthEnvelope`: post-authentication message facts;
- `TrustedReplayContext`: host-supplied issuer, key epoch, time and revocation;
- `ReplayWindow`: bounded in-memory sequence registry;
- `VerificationReceipt`: deny-all replay observation;
- `Error`: structural, replay, expiry, mismatch and capacity failures.

All are implemented in `codex-rs/hepta-authbus/src/lib.rs`.

## Durability and activation

Replay state is process memory only and lost on restart. The crate is
library-only and has no product authorization or effect authority.

## Target-only design

Cryptographic authentication, durable replay protection, authorization policy,
quota registry, reservation, cancellation, expiry settlement and observed-cost
settlement are target-only.

## Known limits and non-claims

Constructing `TrustedReplayContext` does not authenticate its contents; the host
boundary must supply it after verification. A nonzero `signature_digest` is only
a reference to authentication material. No persistent transaction, cross-host
coordination or trusted clock exists in this crate.

## Verification

Tests cover issuer/epoch/scope replay partitioning, exact replay, capacity,
trusted revocation, expiry, payload drift, zero fields and deny-all authority.

## Integration prerequisites

An upstream authenticator must verify issuer/key/signature and provide current
revocation/time. Product authorization and quota must occur in separately
durable modules. No effect adapter may consume `VerificationReceipt` as a grant.
