# auth.authbus current implementation

## Current executable contract

The checked-in `codex-rs/hepta-authbus` implementation is a bounded,
process-local replay verifier. `ReplayWindow` checks nonzero scope, payload and
signature-reference digests; nonzero sequence; explicit revocation; expiry;
exact expected scope and payload; monotonically increasing sequence per subject;
and a configured maximum subject count.

`signature_digest` is an opaque reference to authentication material that must
already have been verified by a trusted boundary. This crate does not verify a
signature or authenticate the caller. A successful check returns a receipt with
`AuthorityPosture::DENY_ALL`; it is never an execution grant.

## Target-only design

Cryptographic verification, durable replay protection, authorization-policy
evaluation, quota registry, quota reservation, cancellation, expiry settlement
and observed-cost settlement are target-only. The corresponding target design
in the general module guide or execution dossier does not describe current
native symbols.

## Known limits and non-claims

The replay map is lost on process restart and is not safe as cross-process or
cross-host replay protection. Its check/update is only serialized by the
caller's exclusive `&mut ReplayWindow`; no persistent transaction exists. A
nonzero signature digest is structural data, not proof of a valid signature.

## Verification

Native tests cover exact matching, replay, explicit revocation, payload drift,
expiry and deny-all authority. The Lane A verifier fails if policy/quota methods
or cryptographic-verification claims are added to the current capability set
without corresponding source and qualification.
