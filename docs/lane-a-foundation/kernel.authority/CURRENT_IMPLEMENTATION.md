# kernel.authority current implementation

## Current executable contract

The implemented authority slice is the final-use boundary in
`codex-rs/hepta-contracts/src/final_use.rs`, specified in `FINAL_USE.md`. A
separately operated Ed25519 signer signs a complete, short-lived operation
binding. `FinalUseAuthority` pins the issuer identity and public key, validates
the signature and exact binding, persists a single-use nonce and monotonic
revocation head, then returns a non-cloneable, non-serializable
`VerifiedUseToken`.

The supported durable backend is an owner-controlled Unix directory with a
process lock, owner-only permissions, no-follow opens, atomic same-directory
replacement and file/directory fsync. A persistence failure fences the live
authority. The final synchronous consumer entry rechecks time, epoch, binding
and revocation under the authority lock.

## Target-only design

A general identity provider, approval-policy engine, distributed authority
service, remote quorum and external anti-rollback oracle are not implemented by
this slice. Equivalent durable backends for unsupported platforms require
separate qualification.

## Known limits and non-claims

Deleting or restoring the complete local authority directory can reset local
history; recovery therefore requires independent issuer/epoch action. The
library is not a sandbox against untrusted code in the same process or Unix
account. Revocation cannot undo an effect that already entered the bounded
consumer callback.

## Verification

The source and specification cover signed-field substitution, expiry, epoch
fencing, monotonic revocation, nonce replay across restart, unsafe storage,
concurrent ownership and provider-adapter integration. Those checks do not grant
production activation or operator acceptance.
