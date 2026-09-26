# auth.authbus production topology

Status: normative logical topology; environment bindings are deployment secrets

This document names the production roles and data paths without inventing cloud
resource IDs, service-account names or private key material. Those values belong
in the deployment system and activation receipt, not in source control.

## Named components

### `authbus-authority`

The only production writer. It owns `AuthBusAuthorityHost`, the SQLite authority
database, the cross-process owner lock, the external checkpoint and the unified
maintenance loop. No product caller receives a raw store or database pool.

Responsibilities:

- issuer lifecycle administration;
- signed trusted-time verification;
- policy and quota mutation;
- reservation, dispatch fence, settlement and recovery;
- checkpoint publication;
- bounded expiry/recovery/compaction maintenance;
- module-owned metrics and receipts.

### `agentd-authbus-ingress`

The named message-admission caller. It reloads the owner-controlled message
issuer registry at each admission and dispatch boundary and resolves a sealed
`IssuerRegistration` through `VerifiedIssuerRegistry`. It cannot construct a
trusted issuer from message fields.

### `kernel-evidence-authbus-outbox`

The durable replay/outbox caller. It accepts only sealed registrations produced
from the verified registry, maintains replay/checkpoint state and carries signed
messages to Agentd. Revoked-epoch quarantine requires verified revoked authority
state or an issuer-retirement receipt.

### `bao-authbus-final-use`

The named provider-side-effect caller. It authorizes and reserves through
`AuthBusAuthorityHost`, persists `dispatch_attempted` before the provider call,
then submits signed settlement evidence. Settlement issuer lookup occurs inside
the authority transaction; the Bao caller never supplies a verifying key.

### `authbus-trusted-time-signer`

An independent online signer that emits `SignedTrustedTimeAttestation` under the
trusted-time signing domain. Its private key is held in a dedicated KMS/HSM role.
It is not the authority database writer and cannot mutate policy, quota or issuer
state.

### `authbus-settlement-signer`

The online signer behind the existing `BaoAuthBusEvidenceProvider` contract. It
emits settlement evidence bound to exact reservation ID, operation ID, status,
observed cost, terminal evidence digest and observation time. Its private key is
purpose-specific and KMS/HSM-held.

## Process and data flow

```text
owner-controlled issuer registry
            |
            v
agentd-authbus-ingress <--> kernel-evidence-authbus-outbox
            |
            | sealed verified issuer handle / signed message
            v
authbus-authority --owner lock--> authority.sqlite
       |       |                     |
       |       +---------------------+--> external checkpoint
       |
       +--> policy + quota reservation
                    |
                    v
             bao-authbus-final-use ---> provider
                    |                       |
                    +<-- terminal receipt --+
                    |
                    v
authbus-settlement-signer --signed evidence--> authbus-authority

authbus-trusted-time-signer --signed time----> authbus-authority
```

## Key custody bindings

The deployment manifest must supply references, not raw key bytes, for:

- `AUTHBUS_TRUSTED_TIME_KMS_KEY_REF`;
- `AUTHBUS_SETTLEMENT_KMS_KEY_REF`;
- each message issuer's workload signer reference;
- the service identities allowed to invoke each signer;
- registry publication identity and two-person approval policy.

The authority deployment contains public keys and lifecycle state only. It must
not have permission to export signer private keys. Message, trusted-time and
settlement keys are separate even when hosted by the same KMS provider.

## Required deployment bindings

The environment activation receipt records:

```text
environment
authority service identity
authority binary digest
database path
owner-lock path
checkpoint path
message-registry path and digest
trusted-time public-key fingerprint and KMS reference hash
settlement public-key fingerprint and KMS reference hash
metrics/exporter endpoint identity
paging route identifier
source SHA, source tree and schema digest
```

KMS references may be hashed or redacted in the repository receipt, but security
reviewers must be able to resolve them in the deployment control plane.

## Network and privilege boundaries

- The authority database and checkpoint are local private files; they are not on
  a shared network filesystem.
- Only `authbus-authority` has write permission to database, lock and checkpoint.
- Registry publishers do not receive database write permission.
- Product callers use typed in-process or authenticated local IPC contracts; no
  endpoint accepts public key, revoked bit or issuer purpose as trusted input.
- Signer APIs accept only canonical purpose-specific claims and return signatures;
  they do not accept arbitrary bytes from general workloads.
- Metrics are read-only and never expose raw issuer, principal, message,
  operation or reservation IDs.

## High availability model

The supported model is active/passive, not active/active. A passive instance may
share deployment configuration and backups but must not open the production
database or checkpoint until it acquires the exclusive owner lock. Database and
checkpoint fail over as one storage pair. Cross-host shared-file failover is not
qualified by this module; a deployment needing it must add an external consensus
or fencing layer and undergo a separate review.

## Production provider acceptance

A concrete provider binding is accepted only after it demonstrates:

- non-exportable purpose-specific private key custody;
- exact canonical signing-domain enforcement;
- IAM separation from the authority writer;
- audit logging and emergency disablement;
- epoch rotation and revocation drill;
- timeout/unknown-outcome behavior that preserves indeterminate state;
- staging qualification bound to the same binary and configuration schema.
