# `kernel.authority` current implementation

This file is the current-source truth boundary. The target/current/product matrix is maintained in
[`TRACEABILITY.md`](../../modules/kernel.authority/TRACEABILITY.md); the general-lease trust decision is frozen in
[`ADR-0001-LEASE-TRUST-MODEL.md`](../../modules/kernel.authority/ADR-0001-LEASE-TRUST-MODEL.md), and the concurrency ordering contract is
[`LINEARIZATION.md`](../../modules/kernel.authority/LINEARIZATION.md).

## Current executable contract

The current candidate contains two native authority families.

### General authority leases

`src/authority_lease.rs` implements the durable owner for `authority_lease` and `capability_revocation`.

- `AuthorityLeaseRegistry` is the non-cloneable administrative capability. It owns put/replace, revoke, bounded expired-lease pruning and epoch advance.
- `AuthorityLeaseVerifier` is a cloneable read/verify attenuation. It cannot mutate authority state.
- a verified token is rechecked against the exact current stored lease record; replacing a lease invalidates tokens issued for an older revision;
- revocation retries are idempotent only for the same lease ID, expected revision and reason digest. The caller does not supply the revocation timestamp; the authority clock creates it once and an identical retry returns the original receipt;
- time comes from the clock bound into the owner. Product callers do not provide arbitrary `now_unix_ms` values to verifier operations;
- production-oriented open binds `AuthorityClock` plus an externally durable `AuthorityFrontierStore<AuthorityLeaseFrontier>`.

V1 general leases are registry-authoritative online references. Serialized lease values are not self-verifying portable bearer capabilities.

### Signed FinalUse

`src/final_use.rs` implements a separately signed, short-lived final operation grant with exact subject/destination/request/scope/payload binding, strict Ed25519 verification, durable single-use nonce burn, monotonic revocation and opaque `VerifiedUseToken`.

`FinalUseAuthority::open_state_dir_with_issuer_keys` binds a bounded issuer key ring with authority-epoch activation/retirement windows. The complete ring configuration is digest-pinned in durable store schema V2; legacy schema V1 remains a separate single-key compatibility model and is not silently migrated.

`FinalUseAuthority::open_state_dir_with_trust` binds a host clock and an external `FinalUseFrontier` CAS store for the single-key compatibility path. The frontier digest includes both the complete revocation head and claimed nonce set. Every mutation advances the external frontier before the local fsync/rename. A local snapshot restored behind that frontier fails closed.

Compatibility constructors without an external frontier remain available for tests/source compatibility and are not an external anti-rollback claim.

## Public symbols and source bindings

- `AuthorityLeaseRegistry`, `AuthorityLeaseVerifier`, `LeaseVerifiedUseToken`, `AuthorityLeaseFrontier`: `codex-rs/hepta-contracts/src/authority_lease.rs`.
- `AuthorityClock`, `AuthorityFrontierStore`, `SystemAuthorityClock`: `codex-rs/hepta-contracts/src/authority_trust.rs`.
- `FinalUseAuthority`, `VerifiedUseToken`, `claim_final_use`, `deliver_final_use`, `dispatch_final_use`: `codex-rs/hepta-contracts/src/final_use.rs`.
- independent approval, revocation-feed freshness, epoch-window trust keys and signed convergence acknowledgements: `codex-rs/hepta-contracts/src/final_use_control.rs`.
- owner-only nonce/revocation persistence: `codex-rs/hepta-contracts/src/final_use_store.rs`.
- strongest source-composed consumer boundary: `BaoFinalUseHost` and `RegisteredBaoConsumer` in `codex-rs/hepta-bao-adapter/src/final_use_host.rs`.

### Linearization

- `deliver_final_use` / `with_verified_use`: the final live check is the consumer-entry linearization point and the lock is released before bounded consumer code.
- `dispatch_final_use` / `with_dispatch_boundary`: the authority lock is retained only across a short local irreversible transition, never a remote wait or arbitrary plugin/user callback.
- general `AuthorityLeaseVerifier::with_verified_use` uses the same consumer-entry model and additionally checks that the exact current lease record is unchanged.

A completed revocation before the relevant linearization point denies entry. A change committed after entry does not retroactively undo the entered effect. Crash/lost acknowledgement after entry remains indeterminate and must be reconciled.

### Production-control primitives

`src/final_use_control.rs` adds independent approval and revocation roles.

- the grant issuer, approval verifier and feed verifier support bounded epoch-window key rings for staged overlap and deterministic retirement;
- verification identifies the exact trust key used for audit;
- revocation feed schema V2 signs issued/expiry times and rejects not-yet-valid or stale updates;
- enrolled nodes can sign exact-update apply acknowledgements, and the convergence verifier returns deterministic acknowledged/missing node sets while the update is still fresh; future-dated acknowledgements are rejected;
- the registered Bao host begins without fresh revocation knowledge, checks freshness before provider dispatch and again at final registered-consumer entry, and denies secret release if the feed expires while provider I/O is in flight.

The grant issuer, approver and revocation distributor remain independently pinned roles. Repository signer tools do not generate keys.

## Durability and activation

Both local stores use owner-controlled Unix directories, no-follow opens, owner-only permissions, process locking, complete-state replacement, file fsync, rename and directory fsync. Equivalent non-Unix backends are not current.

Local filesystem durability protects crash/restart consistency but is not an external rollback oracle. The repository defines `AuthorityFrontierStore<F>` with durable load/CAS semantics and `AuthorityClock`; production qualification still requires concrete protected implementations supplied by the selected host/platform.

The CAS protocol intentionally advances the external frontier before the local state. If external CAS succeeds and the local commit fails, the owner fences and a subsequent open sees the external frontier ahead of local state. Recovery is explicit; it never converts uncertainty into a reset.

### Capacity lifecycle

General leases are bounded at 16,384 live lease records and 16,384 revocation records. `prune_expired_leases` can reclaim at most 1,024 expired unrevoked leases per call. Revocation tombstones are not silently collected within an epoch. Epoch advance fences prior authority and clears bounded history.

FinalUse nonce/revocation history remains explicitly bounded and is cleared only by a stronger trusted epoch transition. There is no silent replay-history eviction.

### Source composition

The strongest source-composed boundary is the registered Bao host. It uses a crate-private typed final-delivery gate. B4 requires zero non-test product callers of the public raw `BaoClient::consume_kv_v2` closure path and independently inventories the public authority APIs.

There is still no selected deployed product process for that host in this candidate. Source composition is therefore not activation and does not prove product execution.

## Target-only design

The other registered target ModulePorts (AuthBus, Servo, Matrix, inference, memory federation, Codex, fleet and supervisor generic-authority ports) do not become implemented merely because the general lease primitive exists. Existing module-specific authority/fence mechanisms keep their own semantics and are not re-labelled as kernel.authority composition.

Fleet revocation transport/fanout, target-host trusted clock/frontier backends, HSM/KMS custody and cross-platform durable storage remain integration or external-evidence work. The signed feed and convergence verifier are repository primitives, not a claim that the fleet transport has been deployed.

## Known limits and non-claims

- no selected product-process caller for the registered Bao host;
- no generic `kernel.authority` composition for every target ModulePort;
- no measured fleet revocation convergence/freshness SLA;
- no qualified attested production clock or deployed rollback-resistant frontier store;
- no qualified HSM/KMS custody, staged operator ceremony or compromise-response process;
- no non-Unix durable authority backend;
- no independent acceptance, activation, canary, promotion or release claim.

These facts require named hosts, deployment configuration and exact-candidate evidence. Source compilation or an empty B4 caller set cannot substitute for product execution evidence.

## Verification

Current source tests cover, among other cases:

- stale-token denial after lease replacement;
- exact-predecessor identical put retries and exact revocation retry semantics with an authority-generated timestamp;
- bound-clock lease verification;
- bounded expired-lease pruning;
- external general-lease snapshot rollback detection;
- injected FinalUse clock;
- external FinalUse claim-snapshot rollback detection;
- approval/feed key overlap by authority epoch;
- signed revocation freshness, future-ack rejection and convergence acknowledgement validation;
- registered consumer, forged independent approval and in-flight feed-expiry denial;
- the documented VerifiedUse and dispatch linearization races.

`CALLERS.toml` and `qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json` classify the public privileged surfaces, including production trust constructors, raw verification/delivery methods, the bounded dispatch fence and lease pruning.

## Integration prerequisites

Before activation, a candidate must name and exercise a real product process through the registered host, bind a protected `AuthorityClock` and rollback-resistant `AuthorityFrontierStore`, ingest a fresh independently signed revocation feed, establish key-custody/rotation/compromise procedures, retain exact-head plus deterministic synthetic-merge evidence, and pass independent semantic review.

Additional target ModulePorts are composed only at their real owner boundaries with their own caller and qualification evidence. None is inferred from the existence of the generic lease type.
