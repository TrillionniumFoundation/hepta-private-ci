# AuthBus preverified replay contract V1

This is the retained legacy API. The separate
[`signed admission API`](../../../codex-rs/hepta-authbus/SIGNED_ADMISSION.md)
authenticates signatures and supports durable replay through the evidence store;
it does not change this API's semantics.

## Trust split

Untrusted message facts reside in `PreverifiedAuthEnvelope`. Trusted host facts
reside in `TrustedReplayContext`. The latter must be produced only after an
upstream authentication boundary verifies the issuer, key epoch and revocation
frontier.

## Admission algorithm

1. Reject zero scope, payload or signature-reference digest.
2. Reject sequence zero.
3. Reject trusted revocation.
4. Reject when `now_ms >= expires_at_ms`.
5. Require exact expected scope and payload digests.
6. Form replay key `(issuer_id, key_epoch, subject_id, scope_digest)`.
7. Require the sequence to exceed the recorded maximum.
8. Reject a new key when bounded capacity is exhausted.
9. Update the in-memory maximum and emit a domain-separated deny-all receipt.

## Receipt semantics

The receipt binds issuer, key epoch, message, subject, scope, payload,
signature-reference, sequence and expiry. It proves only that this in-process
window accepted the preverified facts. It grants no authentication,
authorization, quota, execution, selection, promotion or release authority.

## Restart behavior

This API's replay state is lost on process exit. Hosts requiring durable replay
must use `HeptaEvidenceStore::admit_authbus_message` instead of `ReplayWindow`.
