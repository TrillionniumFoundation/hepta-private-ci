# auth.authbus threat model

Status: normative source-security contract for `auth.authbus`.

## Assets and invariants

AuthBus protects issuer identity, policy revisions, trusted-time monotonicity, quota conservation, reservation identity, dispatch fencing, settlement authenticity and the independently retained authority checkpoint. A successful API call never implies provider success unless terminal evidence proves it. A timeout, process crash or lost acknowledgement after the dispatch fence is `Indeterminate`, never `NotApplied`.

The following invariants are mandatory:

1. Verification keys, issuer purpose, epoch and revocation state come from an owner-controlled persisted registry. Message payloads and callers cannot construct a trusted issuer registration.
2. Only `AuthBusAuthorityHost` may mutate the authority database. The raw store writer is crate-private.
3. Exactly one live owner holds the process-lifetime owner fence for one authority database. Checkpoint compare/publish/promote occurs while that fence is held.
4. `available + reserved + consumed == limit` for every quota generation. Expired undispatched holds are refunded; attempted effects retain quota until authenticated terminal evidence.
5. The external checkpoint is outside the database rollback domain. Missing, older, foreign-owner or digest-divergent witnesses fail closed.
6. Purpose is part of registry selection. Message, settlement and trusted-time keys are not interchangeable.

## Trust boundaries

- **Untrusted ingress:** signed message bytes, settlement claims, operation identifiers, provider responses and all network input.
- **Owner-controlled configuration:** private issuer registries, checkpoint path, database path, SLO policy and deployment identity.
- **Durable authority boundary:** SQLite authority database plus the independently retained checkpoint.
- **External-effect boundary:** the provider call after durable `DispatchAttempted` and final-use verification.
- **Operator boundary:** key enrollment, rotation, revocation, recovery approval and activation.

## Threats and controls

| Threat | Required control | Verification |
| --- | --- | --- |
| Caller supplies its own public key | Opaque registration handle; private fields; persisted-registry resolution | compile/API inventory plus forged-key negative test |
| Stale handle survives revocation | Settlement reloads exact issuer/purpose/epoch in the settlement transaction | revoked-key test |
| Epoch or purpose substitution | Exact `(issuer_id, purpose, epoch)` lookup and signed epoch | epoch/purpose negative tests |
| Fake quarantine authority | Quarantine accepts only a sealed current registration and preserves queue state on rejection | evidence outbox negative test |
| Direct store bypass | Writer type and mutation surface are crate-private | closed-world source inventory |
| Two writers race checkpoint publication | process-lifetime cross-process owner fence | dual-process and kill/restart tests |
| Database rollback | external generation/digest witness; no witness reconstruction for an existing DB | rollback tests |
| Crash after provider boundary | durable dispatch fence and restart conversion to `Indeterminate` | restart/fault tests |
| Reservation exhaustion | bounded active limits and bounded periodic expired-reservation sweep | capacity/sweep tests and alerts |
| Symlink, hard-link or replacement attack on trust/checkpoint files | canonical direct-child path, owner/mode/link/metadata checks, atomic write and directory fsync | filesystem adversarial tests |
| Disk-full/fsync/rename ambiguity | mutation remains dirty; next owner reconciles external/local frontier; no success response | checkpoint failpoint tests |
| Schema drift or downgrade | migration ledger, live-schema comparison, post-migration integrity checks and schema digest | schema qualification |
| Sensitive key leakage | public keys only in AuthBus; private keys remain in KMS/HSM signer; no secret logs | deployment review |

## Adversary model

The attacker may control request payloads, message order, retries, provider timing, network failures, process termination and files outside protected owner directories. The attacker may run a second process as the same service account. The model does not assume protection against an administrator who can replace the executable, rewrite both the authority database and independent checkpoint domain, or extract HSM keys; those are host-platform and key-custody controls and remain activation prerequisites.

## Security stop conditions

Activation stops on any constructible trusted registration, externally reachable store writer, missing owner fence, checkpoint reconstruction from an existing database, unresolved schema drift, nonzero expired-active reservations after the configured grace period, or an exact-head qualification result other than terminal success.
