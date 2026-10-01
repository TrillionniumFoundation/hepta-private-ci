# auth.authbus threat model

Status: normative source-security contract for `auth.authbus`.

## Assets and invariants

AuthBus protects issuer identity, policy revisions, trusted-time monotonicity,
quota conservation, durable operation identity, reservation identity, dispatch
fencing, settlement authenticity and the independently retained authority
checkpoint. A successful API call never implies provider success unless
terminal evidence proves it. A timeout, process crash or lost acknowledgement
after the dispatch fence is `Indeterminate`, never `NotApplied`.

The following invariants are mandatory:

1. Verification keys, issuer purpose, epoch and revocation state come from an
   owner-controlled persisted registry. Message payloads and callers cannot
   construct a trusted issuer registration.
2. Only `AuthBusAuthorityHost` may mutate the authority database. The raw store
   writer is crate-private.
3. Exactly one conforming live owner holds the process-lifetime owner fence for
   one authority database. Checkpoint compare/publish/promote occurs while that
   fence is held.
4. `available + reserved + consumed == limit` for every quota generation.
   Expired undispatched holds are refunded; attempted effects retain quota until
   authenticated terminal evidence.
5. The external checkpoint is outside the database rollback domain. Missing,
   older, foreign-owner or digest-divergent witnesses fail closed.
6. Purpose is part of registry selection. Message, settlement and trusted-time
   keys are not interchangeable.
7. Production operation identity is owned by `kernel.operations`; Bao and
   AuthBus accept only a sealed, current generation/revision/fence handle and
   never mint a replacement identifier after an ambiguous outcome.

## Trust boundaries

- **Untrusted ingress:** signed message bytes, settlement claims, operation
  identifiers, provider responses and all network input.
- **Owner-controlled configuration:** private issuer registries, checkpoint
  path, database path, SLO policy and deployment identity.
- **Durable authority boundary:** SQLite authority database plus the
  independently retained checkpoint.
- **Durable operation boundary:** the `kernel.operations` ledger, outbox,
  generation and writer fence. It is not owned by Bao or AuthBus.
- **External-effect boundary:** the provider call after durable
  `DispatchAttempted` and final-use verification.
- **Host isolation boundary:** a dedicated service UID/GID, mandatory access
  control profile, mount namespace and owner-only state directories.
- **Operator boundary:** key enrollment, rotation, revocation, recovery
  approval and activation.

## Threats and controls

| Threat | Required control | Verification |
| --- | --- | --- |
| Caller supplies its own public key | Opaque registration handle; private fields; persisted-registry resolution | compile/API inventory plus forged-key negative test |
| Stale handle survives revocation | Settlement reloads exact issuer/purpose/epoch in the settlement transaction | revoked-key test |
| Epoch or purpose substitution | Exact `(issuer_id, purpose, epoch)` lookup and signed epoch | epoch/purpose negative tests |
| Fake quarantine authority | Quarantine accepts only a sealed current registration and preserves queue state on rejection | evidence outbox negative test |
| Direct store bypass | Writer type and mutation surface are crate-private | closed-world source inventory |
| Conforming owners race checkpoint publication | process-lifetime process-local claim plus Linux OFD fence | dual-process and kill/restart tests |
| Arbitrary code runs under the service UID | dedicated UID/GID, SELinux/AppArmor policy, mount namespace, immutable executable/control plane and owner-only directories; advisory locks are not treated as mandatory access control | target-host identity and isolation receipt |
| Database rollback | external generation/digest witness in a separately governed storage domain; no witness reconstruction for an existing DB | rollback tests and target-host receipt |
| Caller mints or replaces operation identity | sealed `kernel.operations` handle bound to destination, payload, generation, revision and fence | product composition and recovery tests |
| Crash after provider boundary | durable operation handoff, AuthBus dispatch fence and restart conversion to `Indeterminate` | restart/fault tests |
| Reservation exhaustion | bounded active limits and bounded periodic expired-reservation sweep | capacity/sweep tests and alerts |
| Symlink, hard-link or replacement attack on trust/checkpoint files | canonical direct-child path, owner/mode/link/metadata checks, atomic write and directory fsync | filesystem adversarial tests |
| Disk-full/fsync/rename ambiguity | mutation remains dirty; next owner reconciles external/local frontier; no success response | checkpoint failpoint and target-host tests |
| Schema drift or downgrade | migration ledger, live-schema comparison, post-migration integrity checks and schema digest | schema qualification |
| Sensitive key leakage | public keys only in AuthBus; private keys remain in KMS/HSM signer; no secret logs | deployment review and signed external evidence |

## Adversary model

The source-level owner fence protects against a second **conforming AuthBus owner
process** that participates in the same process-local/OFD locking protocol. It
does not claim to stop arbitrary malicious code running under the same Unix UID:
Linux record locks are advisory, and same-UID code could otherwise bypass the
library and attempt direct SQLite, WAL, checkpoint or lock-path access.

A production deployment therefore MUST run AuthBus under a dedicated UID/GID,
with an enforced SELinux/AppArmor (or equivalent) policy, a constrained mount
namespace, owner-only database/WAL/SHM directories and a checkpoint domain whose
write authority is independently governed. Target-host receipts MUST bind the
UID/GID, executable and control SHA, LSM profile digest, mount namespace and
filesystem/device identities for both the database and checkpoint domains.

The attacker may control request payloads, message order, retries, provider
timing, network failures, process termination and files outside those protected
domains. The model does not assume protection against an administrator who can
replace the executable/control plane, rewrite both independently governed state
domains, disable mandatory access control or extract HSM keys. Those remain
explicit activation prerequisites, never source-code claims.

## Security stop conditions

Activation stops on any constructible trusted registration, externally
reachable store writer, missing owner fence, production deployment without the
required UID/LSM/mount isolation, checkpoint reconstruction from an existing
database, unresolved schema drift, nonzero expired-active reservations after
the configured grace period, unbound durable operation identity, or an
exact-head qualification result other than terminal success.
