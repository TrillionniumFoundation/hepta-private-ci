# `kernel.authority` current implementation

## Current executable contract

The implemented authority slice is the final-use boundary in
`codex-rs/hepta-contracts/src/final_use.rs`, specified in
`codex-rs/hepta-contracts/FINAL_USE.md`. A separately operated Ed25519 issuer
signs a complete short-lived binding. `FinalUseAuthority` pins the signer and
public key, verifies the signature and exact binding, durably burns a single-use
nonce, applies monotonic revocation and returns a non-cloneable,
non-serializable `VerifiedUseToken`.

The final synchronous consumer entry rechecks owner identity, binding, time,
epoch and revocation under the authority lock.

## Public symbols and source bindings

- grant and binding schemas, signing preimage, `FinalUseAuthority`,
  `VerifiedUseToken` and errors: `src/final_use.rs`;
- private Unix nonce/revocation store, process lock and fsync protocol:
  `src/final_use_store.rs`;
- independent signer command: `hepta-supervisor` production-authority binary;
- normative source-adjacent specification: `FINAL_USE.md`.

## Durability and activation

The supported backend is one owner-controlled Unix directory with no-follow
opens, owner-only permissions, a process lock, atomic same-directory replace,
file fsync and directory fsync. Equivalent non-Unix backends are not current.
Activation requires a host-selected consumer and protected trust/configuration.

## Target-only design

A general identity provider, approval-policy engine, distributed authority
service, external anti-rollback oracle, trusted time service and cross-platform
store are target-only.

## Known limits and non-claims

Deleting or restoring the complete local authority directory can reset local
history. Wall-clock rollback is not independently detected. The library is not
a sandbox against code in the same process/account. A callback already entered
cannot be revoked retroactively, and a slow callback delays revocation.

## Verification

Tests cover signed-field/key substitution, expiry, epoch changes, monotonic
revocation, replay across restart, unsafe storage, process locking, missing
state and final-use delivery fencing.

## Integration prerequisites

The host must protect issuer keys, pinned public trust, directory ancestors,
clock and consumer registry. A claimed token is consumed once at the final
adapter boundary; a failed or uncertain effect requires a new authorized
operation after reconciliation.
