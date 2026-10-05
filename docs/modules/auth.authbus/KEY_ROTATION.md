# auth.authbus key rotation and custody

## Key roles

AuthBus recognizes distinct purposes: `Message`, `Settlement` and `TrustedTime`. One key epoch has exactly one purpose. A key enrolled for one purpose is never accepted for another, even when issuer ID and public bytes match.

Private keys never reside in the AuthBus database, checkpoint, logs or repository. Production signing keys are generated and used by an approved KMS/HSM. AuthBus stores only Ed25519 public keys, purpose, epoch, lifecycle state and revision.

## Enrollment

1. Generate the key in KMS/HSM and record its non-exportable key identifier.
2. Independently verify issuer ID, purpose and public key fingerprint.
3. Enroll epoch `n` through `AuthBusAuthorityHost` using a revision-bound operation.
4. Publish and verify the external checkpoint.
5. Confirm the signer emits canonical claims with the enrolled purpose/epoch.
6. Enable traffic only after positive and wrong-purpose negative probes.

## Rotation

1. Create epoch `n+1`; epochs strictly increase.
2. Enroll the new public key while epoch `n` remains available for bounded in-flight verification.
3. Move signers to `n+1` and verify telemetry.
4. Revoke epoch `n`; settlement reloads the durable registry so stale handles immediately fail.
5. After the maximum message/evidence validity window and incident-retention window, retire epoch `n`.
6. Publish checkpoint after every lifecycle transition.

Public-key bytes, purpose and epoch are immutable. Rotation creates a new row; it never updates an existing key in place.

## Emergency revocation

Stop the affected signer, revoke the exact purpose/epoch, publish checkpoint, stop mutation admission if publication fails, and inspect verification failures and messages signed since the suspected compromise time. Do not release reservations merely because a settlement signer was revoked; recover terminal state through an independently trusted path.

## Dual control and audit

Production enrollment, revocation and retirement require two-person approval, immutable operation identity and retention of KMS key ID, public fingerprint, AuthBus revision, checkpoint generation, source SHA and operator identities. Break-glass actions use the same API and evidence requirements; there is no direct database-edit procedure.
