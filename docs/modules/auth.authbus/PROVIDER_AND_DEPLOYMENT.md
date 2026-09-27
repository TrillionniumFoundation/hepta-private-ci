# auth.authbus production providers and deployment

## Named providers

A production deployment must bind these interfaces to named implementations:

1. **Trusted-time provider:** verifies an Ed25519 attestation from the enrolled `TrustedTime` issuer, enforces monotonic source revision and supplies `TrustedTimeSample`. Wall-clock APIs alone are not trusted time.
2. **Settlement evidence provider:** receives immutable reservation/operation identity and provider observation, asks the HSM/KMS-backed settlement signer to sign canonical evidence, and never accepts caller-supplied verification keys.
3. **Checkpoint backend:** private regular file on an independently retained local/attached volume with atomic rename and directory fsync semantics.
4. **Operations exporter:** reads the bounded snapshot and emits metrics/dashboard data; it has no mutation or signing capability.

The current source-composed Bao path is the named product consumer. It must obtain final-use authority immediately before the provider call, durably mark dispatch attempted, and settle only with signed evidence. Agentd remains the named signed-ingress/outbox host.

## Key custody

Use non-exportable Ed25519 keys in KMS/HSM. Separate trusted-time, message and settlement keys and policies. The authority owner may enroll public keys but cannot sign. The signer cannot mutate AuthBus. The observer can do neither. Audit logs bind KMS key ID, public fingerprint, purpose, epoch and operation identity without recording secrets.

## Filesystem layout

Recommended layout:

```text
/var/lib/hepta/authbus-db/authority.sqlite
/var/lib/hepta/authbus-db/authority.sqlite.authbus-owner-lock.sqlite
/var/lib/hepta/authbus-checkpoint/authority-checkpoint.json
/etc/hepta/authbus/message-issuer-registry.json
```

Each directory is owned by the dedicated service account and mode `0700`; files are mode `0600`, regular, single-link and direct children of canonical directories. Database and checkpoint directories are distinct rollback domains.

## Process and network isolation

Run one authority owner process. Deny network access except explicitly registered provider/KMS endpoints. Bao/provider credentials are available only to the product adapter, not the observer or message ingress. Use read-only root filesystem where possible and dedicated writable mounts for the two state domains.

## Activation inputs

Activation requires exact qualified binary digest, source SHA/tree, schema digest, configured owner ID, database/checkpoint device identities, enrolled issuer fingerprints, KMS policies, trusted-time freshness limits, SLO policy digest and successful target-host power-loss/ENOSPC rehearsal.
