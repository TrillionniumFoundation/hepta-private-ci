# kernel.evidence security model

## Security properties are separate

The module reports three independent readiness dimensions:

1. **Local integrity** — canonical serialization, digests, append-only schema,
   immutable identities, transaction atomicity, file replacement controls and
   reopen verification.
2. **Authenticated frontier truth** — Recovery Frontier V2 Ed25519 signatures,
   distinct trusted principals, key IDs/epochs, validity, revocation and
   signer-policy generation.
3. **Independent anti-rollback** — a monotonic CAS/history service in a rollback
   domain independent from the evidence database and local host.

Passing one dimension never implies another. The legacy V1 local field called
`signature` is an integrity token, not an identity-authenticating signature.
Production admission uses V2 signatures and an independently identified backend.

## Threats and controls

- Same identity with changed content is a hard conflict.
- Same frontier generation with different canonical identity is a split-brain
  conflict; no lexical or timestamp tie-break is allowed.
- Stale generations cannot overwrite newer state.
- Unknown external outcomes remain indeterminate and are reconciled by exact
  batch/frontier digest.
- A trust registry cannot silently downgrade verification policy.
- Removed, revoked, expired, role-mismatched or key-rotated issuers cannot
  continue satisfying a positive claim.
- Backup receipts bind actual object bytes, governed build provenance and a
  restore witness.
- Local database and frontier rollback together are detected only when the
  independently retained monotonic anchor is available.

The external backend classifies a proposal only after acquiring its exclusive
store/journal lock. The current durable frontier used by the classifier is read
under that same lock. Reopen verification repeats the state-machine decision for
every journal transition. The segmented backend walks sealed segments from
genesis and then validates the archive-to-active boundary; it does not trust a
self-consistent latest index as semantic proof. Therefore a party that merely
rewrites bytes and recomputes local SHA-256 fields cannot convert a source,
migration or issuer-trust transition into `IncomingWins`. A party controlling
the independent signing and monotonic-anchor authorities remains outside the
local-integrity threat boundary and is governed by the next two readiness
dimensions.

## Key lifecycle

Every production signer record carries principal ID, key ID/epoch, validity
window, revocation state and trust-root generation. Rotation must advance the
relevant policy generation. Overlap is explicit and bounded; a revoked key is
never accepted because an older artifact was once valid. Trust-root replacement
is an explicit signed transition and cannot be inferred from a colocated file.

## Repair authority

Repair is not a generic administrative overwrite. Authorization is valid for one
current/target digest pair, one generation transition, one store, one operator,
one reason and one expiry/nonce. It is verified against an independently admitted
Ed25519 authority record. Invalid current state, invalid target state, stale
input, exact duplicates and same-generation identity splits are not converted
into ordinary repair writes.

The checked-in verifier establishes authorization authenticity and exact scope.
The normal external CAS APIs deliberately reject `RepairRequired`, even when a
caller possesses a signed document. A production repair service must add a
separate durable one-time-nonce ledger and audit record that retains the exact
authorization and current/target digests before performing that one transition.
That service and ceremony are not source-composed in Agentd today, so repair
publication remains an activation gate rather than a repository-issued
capability.

## Non-claims

Repository workflows do not prove target-host filesystem semantics, independent
operator control, external service deployment, repair-service activation,
canary acceptance or release. These require separate receipts bound to the same
immutable candidate.
