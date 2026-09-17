# `kernel.authority` current implementation

## Current executable contract

The current source contains two authority-owner slices in
`codex-rs/hepta-contracts`.

The final-use slice is implemented in `src/final_use.rs` and specified in
`FINAL_USE.md`. A separately operated Ed25519 issuer signs one complete,
short-lived operation binding. `FinalUseAuthority` pins the signer and public
key, verifies the signature and exact binding, durably burns a single-use nonce,
applies monotonic revocation and returns a non-cloneable, non-serializable
`VerifiedUseToken`.

The general capability slice is implemented in `src/authority_lease.rs`.
`AuthorityLeaseRegistry` is the native owner for the documented
`authority_lease` and `capability_revocation` domains. It provides bounded
owner-CAS lease mutation, durable CAS revocation, authoritative read values,
host-supplied trusted time, a host-supplied anti-rollback frontier and explicit
durable epoch rollover.

The production-control primitives are implemented in
`src/final_use_control.rs` and specified in `FINAL_USE_CONTROL.md`. They add an
independent operator approval signature and an independently authenticated
revocation-feed signature. The Bao integration owns a closed consumer registry
in `codex-rs/hepta-bao-adapter/src/final_use_host.rs`: the signed
`consumer_id` selects one pre-enrolled process-local callback instead of allowing
a callsite to substitute arbitrary code.

The final synchronous consumer entry rechecks owner identity, binding, time,
epoch and revocation under the authority lock, then releases that mutex before
executing the already selected trusted callback. The successful recheck is the
linearization point: a completed revocation before it denies entry; a revocation
committed after it is ordered after entry and cannot retroactively cancel the
already-entered synchronous effect.

## Public symbols and source bindings

- grant/binding schemas, signing preimage, `FinalUseAuthority`,
  `VerifiedUseToken`, `claim_final_use`, `deliver_final_use` and errors:
  `src/final_use.rs`;
- private Unix final-use nonce/revocation store, process lock and fsync protocol:
  `src/final_use_store.rs`;
- general durable capability leases/revocations, trusted frontier/time and epoch
  rollover: `src/authority_lease.rs`;
- independent approval and signed revocation-ingress verifiers:
  `src/final_use_control.rs`;
- independent issuer, approver and revocation-signer commands:
  `codex-rs/hepta-supervisor/src/bin/hepta-final-use-*.rs`;
- registered Bao consumer host:
  `codex-rs/hepta-bao-adapter/src/final_use_host.rs`;
- normative source-adjacent specifications: `FINAL_USE.md` and
  `FINAL_USE_CONTROL.md`.

## Durability and activation

The current authority stores use owner-controlled Unix directories with
no-follow opens, owner-only permissions, a process lock, atomic same-directory
replace, file fsync and directory fsync. Equivalent non-Unix backends are not
current.

The general lease store does not treat the local filesystem as an anti-rollback
oracle. Opening it requires a protected host frontier; a persisted state behind
that frontier or a missing initialized store fails closed. `verify_use` accepts
host-supplied trusted time rather than reading the process wall clock.

The Bao registered host is source-composed and B4-protected, but there is still
no selected production process caller in this candidate. Source composition is
not activation, target-host qualification or operator acceptance.

A production-capable final-use host can pin three independent roles: grant
issuer, operator approver and revocation distributor. The explicit supervisor
utilities do not generate keys. Access to each private key remains an external
key-custody boundary. A host may therefore require both a valid grant signature
and an independent approval signature before dispatch, and accepts revocation
heads only after validating a separately pinned feed signature.

## Target-only design

The repository does not implement or claim a general identity provider, a full
approval-policy engine, fleet revocation transport/consensus, an HSM/KMS
ceremony, an external anti-rollback oracle, an attested time service or a
cross-platform durable authority backend.

Revocation **authentication and ingestion** are implemented; fleet fanout,
freshness SLA and stop-on-stale deployment policy remain target-host
responsibilities. Likewise, the general lease API accepts trusted time/frontier
inputs but does not manufacture those trust facts.

Both authority stores are bounded. The general lease registry exposes current
and maximum lease/revocation counts and provides an explicit durable epoch
rollover that fences old authority before clearing bounded history. Deployment
must alert before exhaustion and coordinate the trusted new epoch/frontier; no
implicit eviction or history reset is allowed.

## Known limits and non-claims

The local authority filesystem is not an external rollback oracle and the
repository does not attest host time. The registered Bao host has no selected
production-process caller in this candidate. Signed revocation ingestion does
not itself prove fleet delivery freshness. The library is not a sandbox against
code running with the same process/account authority, and a revocation cannot
retroactively undo an effect that already crossed the final synchronous entry
linearization point.

Source implementation, tests and exact-candidate receipts do not grant operator
acceptance, activation, canary, promotion or release.

## Verification

Final-use tests cover signed-field/key substitution, expiry, epoch changes,
monotonic revocation, replay across restart, unsafe storage, process locking,
missing state and final-use delivery fencing. A dedicated integration test
proves that a callback may perform a revocation update without deadlocking on
the final-use mutex.

Lease-registry tests cover durable verification/revocation, stale CAS and binding
mismatch, external-frontier rollback detection, missing-store reset denial and
durable epoch rollover. Control tests cover exact independent approval,
authenticated monotonic revocation updates and forged-feed rejection. Bao host
integration tests deny unregistered consumer identities and forged independent
approvals before any network dispatch.

These test identities are source evidence. Exact-head and deterministic
synthetic-merge workflow receipts remain the qualification evidence for one
candidate; operator acceptance, activation, promotion and release are separate.

## Integration prerequisites

The host must protect issuer/approver/distributor keys, pinned public trust,
directory ancestors, trusted time/frontier and its registered consumer set. A
claimed token is consumed once at the final adapter boundary; a failed,
panicking, cancelled or otherwise uncertain effect requires reconciliation and
a new authorized operation rather than reuse of the old grant.
