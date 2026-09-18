# `kernel.authority` current implementation

This file is the current-source truth boundary. The target/current/product
matrix is maintained in
[`TRACEABILITY.md`](../../modules/kernel.authority/TRACEABILITY.md); the
general-lease trust decision is frozen in
[`ADR-0001-LEASE-TRUST-MODEL.md`](../../modules/kernel.authority/ADR-0001-LEASE-TRUST-MODEL.md).

## Executable authority owners

The current candidate contains two native authority families.

### General authority leases

`src/authority_lease.rs` implements the durable owner for
`authority_lease` and `capability_revocation`.

- `AuthorityLeaseRegistry` is the non-cloneable **administrative** capability.
  It owns put/replace, revoke, bounded expired-lease pruning and epoch advance.
- `AuthorityLeaseVerifier` is a cloneable read/verify attenuation. It cannot
  mutate authority state.
- a verified token is rechecked against the exact current stored lease record;
  replacing a lease invalidates tokens issued for an older revision;
- revocation retries are idempotent only for identical lease/revision, reason
  digest and revocation timestamp semantics;
- time comes from the clock bound into the owner. Product callers no longer
  provide arbitrary `now_unix_ms` values to verifier operations;
- production-oriented open binds `AuthorityClock` plus an externally durable
  `AuthorityFrontierStore<AuthorityLeaseFrontier>`.

V1 general leases are registry-authoritative online references. Serialized
lease values are not self-verifying portable bearer capabilities.

### Signed FinalUse

`src/final_use.rs` implements a separately signed, short-lived final operation
grant with exact subject/destination/request/scope/payload binding, strict
Ed25519 verification, durable single-use nonce burn, monotonic revocation and
opaque `VerifiedUseToken`.

`FinalUseAuthority::open_state_dir_with_issuer_keys` additionally binds a
bounded issuer key ring with authority-epoch activation/retirement windows.
The complete ring configuration is digest-pinned in durable store schema V2;
legacy schema V1 remains a separate single-key compatibility model and is not
silently migrated.

`FinalUseAuthority::open_state_dir_with_trust` binds a host clock and an
external `FinalUseFrontier` CAS store for the single-key compatibility path. The frontier digest includes both the
complete revocation head and claimed nonce set. Every mutation advances the
external frontier before the local fsync/rename. A local snapshot restored
behind that frontier fails closed.

Compatibility constructors without an external frontier remain available for
tests/source compatibility and are not an external anti-rollback claim.

## Linearization

The normative ordering is
[`LINEARIZATION.md`](../../modules/kernel.authority/LINEARIZATION.md).

- `deliver_final_use` / `with_verified_use`: the final live check is the
  consumer-entry linearization point and the lock is released before bounded
  consumer code.
- `dispatch_final_use` / `with_dispatch_boundary`: the authority lock is
  retained only across a short local irreversible transition, never a remote
  wait or arbitrary plugin/user callback.
- general `AuthorityLeaseVerifier::with_verified_use` uses the same
  consumer-entry model and additionally checks that the exact current lease
  record is unchanged.

A completed revocation before the relevant linearization point denies entry.
A change committed after entry does not retroactively undo the entered effect.
Crash/lost acknowledgement after entry remains indeterminate and must be
reconciled.

## Production-control primitives

`src/final_use_control.rs` adds independent approval and revocation roles.

- the grant issuer, approval verifier and feed verifier all support bounded
  epoch-window key rings for staged overlap and deterministic retirement;
- verification identifies the exact trust key used for audit;
- revocation feed schema V2 signs issued/expiry times and rejects not-yet-valid
  or stale updates;
- the registered Bao host begins without fresh revocation knowledge, requires a
  current signed head before secret use, and denies new secret use after the
  signed freshness deadline until another current head is ingested.

The grant issuer, approver and revocation distributor remain independently
pinned roles. Repository signer tools do not generate keys.

## Persistence, trusted time and rollback

Both local stores use owner-controlled Unix directories, no-follow opens,
owner-only permissions, process locking, complete-state replacement, file
fsync, rename and directory fsync. Equivalent non-Unix backends are not current.

Local filesystem durability protects crash/restart consistency but is not an
external rollback oracle. The repository now defines
`AuthorityFrontierStore<F>` with durable load/CAS semantics and
`AuthorityClock`; production qualification still requires concrete protected
implementations supplied by the selected host/platform.

The CAS protocol intentionally advances the external frontier before the local
state. If external CAS succeeds and the local commit fails, the owner fences and
a subsequent open sees the external frontier ahead of local state. Recovery is
explicit; it never converts uncertainty into a reset.

## Capacity lifecycle

General leases are bounded at 16,384 live lease records and 16,384 revocation
records. `prune_expired_leases` can reclaim at most 1,024 expired unrevoked
leases per call. Revocation tombstones are not silently collected within an
epoch. Epoch advance fences prior authority and clears bounded history.

FinalUse nonce/revocation history remains explicitly bounded and is cleared only
by a stronger trusted epoch transition. There is no silent replay-history
eviction.

## Source composition

The strongest source-composed product boundary is currently the registered Bao
host in `codex-rs/hepta-bao-adapter/src/final_use_host.rs`. B4 restricts the
lower `BaoClient::consume_kv_v2` caller set to that host and independently
inventories the raw authority APIs.

There is still **no selected deployed product process** for that host in this
candidate. The other registered target ModulePorts (AuthBus, Servo, Matrix,
inference, memory federation, Codex, fleet and supervisor generic-authority
ports) do not become implemented merely because the general lease primitive
exists. Existing module-specific authority/fence mechanisms keep their own
semantics and are not re-labelled as kernel.authority composition.

## Verification added by this candidate

Current source tests cover, among other cases:

- stale-token denial after lease replacement;
- exact revocation retry semantics including timestamp;
- bound-clock lease verification;
- bounded expired-lease pruning;
- external general-lease snapshot rollback detection;
- injected FinalUse clock;
- external FinalUse claim-snapshot rollback detection;
- approval/feed key overlap by authority epoch;
- signed revocation freshness;
- registered consumer and forged independent approval denial.

`CALLERS.toml` and
`qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json` independently classify the
public privileged surfaces, including production trust constructors, raw
verification/delivery methods, the bounded dispatch fence and lease pruning.

## Remaining external/product gates

Repository source does not manufacture or claim:

- a selected product process for the registered Bao host;
- generic kernel.authority composition for every target ModulePort;
- fleet revocation transport/consensus or measured convergence SLA;
- an attested production clock;
- a deployed rollback-resistant external frontier store;
- HSM/KMS custody, operator rotation/compromise ceremony;
- cross-platform durable authority storage;
- independent acceptance, activation, canary, promotion or release.

Those facts require named hosts, deployment configuration and exact-candidate
evidence. Source compilation or an empty B4 caller set cannot substitute for
product execution evidence.
