# AuthBus preverified replay contract V1

Status: deprecated compatibility contract, disabled in the default build.

The public types `PreverifiedAuthEnvelope`, `TrustedReplayContext` and
`ReplayWindow` are exported only when the explicit Cargo feature
`legacy-preverified-replay` is enabled. Production profiles MUST leave that
feature disabled. The default external API contains only the cryptographic
`signed admission API`, which verifies a sealed issuer registration with
Ed25519 `verify_strict`; durable replay is owned by the Evidence store.

## Trust split

Untrusted message facts reside in `PreverifiedAuthEnvelope`. Trusted host facts
reside in `TrustedReplayContext`. Constructing either public compatibility type
is not authentication. The latter must be produced only after an upstream
boundary verifies issuer identity, key epoch and revocation frontier.

## Compatibility algorithm

When the non-default feature is intentionally enabled, the deprecated window:

1. rejects zero scope, payload or signature-reference digest;
2. rejects sequence zero;
3. rejects trusted revocation;
4. rejects when `now_ms >= expires_at_ms`;
5. requires exact expected scope and payload digests;
6. forms replay key `(issuer_id, key_epoch, subject_id, scope_digest)`;
7. requires the sequence to exceed the in-process maximum;
8. rejects a new key when bounded capacity is exhausted; and
9. emits a domain-separated deny-all receipt.

## Receipt semantics

The receipt binds issuer, key epoch, message, subject, scope, payload,
signature-reference, sequence and expiry. It proves only that this in-process
structural window accepted caller-provided facts. It grants no authentication,
authorization, quota, operation identity, execution, selection, promotion or
release authority.

## Restart and migration rule

Replay state is lost on process exit. New callers MUST use
`SignedMessage::authenticate` and
`HeptaEvidenceStore::admit_authbus_message`/`enqueue_authbus_message`. A build
that enables `legacy-preverified-replay` is not production-qualified unless a
separate compatibility exception is named in the exact-candidate readiness
manifest.
