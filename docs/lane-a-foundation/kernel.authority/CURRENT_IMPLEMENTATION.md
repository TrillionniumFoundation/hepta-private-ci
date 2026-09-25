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
- lease put retries are idempotent only when both the complete lease value and the original expected predecessor revision match; identical bytes with a different predecessor are a revision conflict;
- revocation retries are idempotent only for the same lease ID, expected revision and reason digest. The caller does not supply the revocation timestamp; the authority clock creates it once and an identical retry returns the original receipt;
- time comes from the clock bound into the owner. Product callers do not provide arbitrary `now_unix_ms` values to verifier operations; final verification acquires the owner lock first and then samples time, so a lease that expires while waiting for that lock is denied;
- production-oriented open binds `AuthorityClock` plus an externally durable `AuthorityFrontierStore<AuthorityLeaseFrontier>`.

V1 general leases are registry-authoritative online references. Serialized lease values are not self-verifying portable bearer capabilities.

### Signed FinalUse

`src/final_use.rs` implements a separately signed, short-lived final operation grant with exact subject/destination/request/scope/payload binding, strict Ed25519 verification, durable single-use nonce burn, monotonic revocation and opaque `VerifiedUseToken`.

`FinalUseAuthority::open_state_dir_with_issuer_keys` binds a bounded issuer key ring with authority-epoch activation/retirement windows. The complete ring configuration is digest-pinned in durable store schema V3. Explicit V1/V2 storage layouts migrate with nonce history intact within their original trust family; single-key trust is not converted to key-ring trust.

`FinalUseAuthority::open_state_dir_with_trust` binds a host clock and an external `FinalUseFrontier` CAS store for the single-key compatibility path. The frontier digest includes both the complete revocation head and claimed nonce set. Every mutation advances the external frontier before the local fsync/rename. A local snapshot restored behind that frontier fails closed.

Compatibility constructors without an external frontier remain available for tests/source compatibility and are not an external anti-rollback claim.

Guarded synchronous and asynchronous effects maintain an active-effect fence. If a trusted revocation update arrives while such an effect is active, the update returns `DispatchInProgress` and sets `revocation_pending`; new claims and all new consumer/dispatch entries then fail with `RevocationPending` until the exact monotonic update is retried after the active effect drains. The pending flag is process-local. A named host must durably retain or re-read the independently signed update across restart rather than treating process loss as cancellation of the revocation.

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
- a successful signed-feed apply returns an opaque receipt bound to the exact update digest; node acknowledgements require that receipt, and convergence first authenticates the distributor-signed update before validating receipt-bound node acknowledgements, rejecting future-dated acknowledgements, and recording selected distributor/node trust-key IDs;
- the registered Bao host begins without fresh revocation knowledge, checks freshness before provider dispatch and again at final registered-consumer entry, and denies secret release if the feed expires while provider I/O is in flight.

The grant issuer, approver and revocation distributor remain independently pinned roles. Repository signer tools do not generate keys.

## Durability and activation

Both local stores use owner-controlled Unix directories, no-follow opens, owner-only permissions and process locking. The general-lease owner writes a complete bounded next-state image with file fsync, same-directory rename and directory fsync. FinalUse appends and fsyncs fixed-width nonce frames on the claim hot path; trusted head/key-ring replacement uses atomic snapshot publication and journal compaction. Equivalent non-Unix backends are not current.

Local filesystem durability protects crash/restart consistency but is not an external rollback oracle. The repository defines `AuthorityFrontierStore<F>` with durable load/CAS semantics and `AuthorityClock`; production qualification still requires concrete protected implementations supplied by the selected host/platform.

The CAS protocol intentionally advances the external frontier before the local state. If external CAS succeeds and the local commit fails, the owner fences and a subsequent open sees the external frontier ahead of local state. Recovery is explicit; it never converts uncertainty into a reset.

### Capacity lifecycle

General leases are bounded at 16,384 live lease records, 16,384 revocation records and 16,384 retired lease-ID revision records. `prune_expired_leases` can reclaim at most 1,024 expired unrevoked live leases per call, but every reclaimed ID first records its last revision in the durable retired-lineage map. Same-epoch reuse must continue at exactly the next revision and can never restart at revision 1. Revocation tombstones and retired revision lineage are not silently collected within an epoch. Epoch advance fences prior authority and clears bounded old-epoch history.

FinalUse nonce/revocation history remains explicitly bounded and is cleared only by a stronger trusted epoch transition. There is no silent replay-history eviction.

### Fleet revocation control-plane composition

`codex-rs/hepta-fleet/src/revocation_control.rs` now composes the signed revocation feed and convergence verifier into a bounded fleet state machine. The coordinator:

- authenticates every installed distributor update before adopting it;
- treats an exact transport replay as idempotent and same epoch/revision semantic drift as a conflict;
- resets acknowledgements on every newer head, forcing every enrolled node to catch up;
- classifies missing nodes as `CatchingUp` before the configured convergence deadline and `Quarantined` afterwards;
- classifies every node as `FeedStale` once the signed head expires;
- accepts only one exact signed acknowledgement per enrolled node and rejects conflicting replacements.

This closes the repository-controlled admission/convergence semantics but does not implement or claim a particular network fanout protocol. A deployed transport must deliver the signed update/ack objects without weakening these checks and must provide measured latency evidence against the configured SLA.

### Source composition

The registered Bao host remains the strongest final-use secret boundary. It uses a crate-private typed final-delivery gate. B4 requires zero non-test product callers of the public raw `BaoClient::consume_kv_v2` closure path and independently inventories the public authority APIs.

Generic leases now also have one concrete owner-side consumer: `codex-rs/hepta-fleet/src/authority_port.rs` computes the exact authority binding from an `AllocationGrant`, verifies the live `AuthorityLeaseVerifier`, rechecks it at consumer entry, and only then executes the existing `LeaseLedger::issue` mutation. B4 admits that exact caller for `verify_use` and `with_verified_use`; arbitrary generic-lease product callers remain denied.

The fleet revocation control plane is separately source-composed in `revocation_control.rs`.

Agentd automation is now a named source-composed FinalUse host. `AgentdAutomationEffectHost` authenticates a signed revocation feed, opens a rotating-issuer `FinalUseAuthority` with the concrete `AgentdFinalUseTrustStore`, derives the exact provider binding, durably records one effect attempt and canonical `VerifiedUseTokenWitnessV1`, and dispatches through the registered HTTP provider adapter. The trust store is single-writer state outside the Agent home rollback domain, persists a non-decreasing clock floor and exact FinalUse CAS frontier, and fails closed on owner conflict, missing frontier, clock rollback or restored local authority state. Source tests cover owner handoff, rollback rejection, slow/active effect revocation, provider response loss, restart recovery and no redispatch.

There is still no selected deployed product process for the Bao host or fleet authority port, and the Agentd source host has no attested target clock, independently qualified storage/backup domain, HSM/KMS custody or operator acceptance in this candidate. Source composition is therefore not activation and does not prove deployed product execution.

## Target-only design

The other registered target ModulePorts (AuthBus, Servo, Matrix, inference, memory federation, Codex, fleet and supervisor generic-authority ports) do not become implemented merely because the general lease primitive exists. Existing module-specific authority/fence mechanisms keep their own semantics and are not re-labelled as kernel.authority composition.

Fleet revocation transport/fanout, target-host trusted clock/frontier backends, HSM/KMS custody and cross-platform durable storage remain integration or external-evidence work. The signed feed and convergence verifier are repository primitives, not a claim that the fleet transport has been deployed.

## Known limits and non-claims

- no selected deployed product process for the registered Bao host or fleet authority port;
- Agentd automation has a named source-composed FinalUse host and durable effect/witness path, but no selected deployment profile or external target qualification;
- `runtime.fleet` has concrete generic-lease and revocation source composition, while several registered generic ModulePorts remain target-only;
- fleet revocation admission/convergence semantics are implemented, but no deployed wire fanout or measured production convergence/freshness SLA;
- no qualified attested production clock or deployed rollback-resistant frontier store;
- no qualified HSM/KMS custody, staged operator ceremony or compromise-response process;
- no non-Unix durable authority backend;
- no independent acceptance, activation, canary, promotion or release claim.

These facts require named hosts, deployment configuration and exact-candidate evidence. Source compilation or an empty B4 caller set cannot substitute for product execution evidence.

The external trust/capacity/rotation/convergence facts now have a machine-checkable
schema-v2 admission format and hostile-case self-test in
`qualification/kernel-authority/verify.py`. A real deployment bundle is accepted
only when it is exact-candidate-bound, every referenced receipt matches its retained
SHA-256, revocation delivery/ack times and node counts satisfy the declared SLA,
and the complete numerical capacity/fault matrix passes. Bundle admission explicitly
does not grant activation or release.

## Verification

Current source tests cover, among other cases:

- stale-token denial after lease replacement;
- exact-predecessor identical put retries, wrong-predecessor identical-value rejection and exact revocation retry semantics with an authority-generated timestamp;
- bound-clock lease verification, including expiry while waiting for the final owner lock;
- bounded expired-lease pruning;
- external general-lease snapshot rollback detection;
- injected FinalUse clock;
- external FinalUse claim-snapshot rollback detection;
- approval/feed key overlap by authority epoch;
- signed revocation freshness, wrong-apply-receipt denial, forged-distributor convergence denial, future-ack rejection and per-key convergence acknowledgement validation;
- registered consumer, forged independent approval and in-flight feed-expiry denial;
- the documented VerifiedUse and dispatch linearization races;
- active-effect revocation pending, denial of new admissions, exact update retry after drain and cancellation cleanup;
- Agentd external-trust single-writer handoff and restored-local-snapshot rejection;
- durable TaskFlow authority witness after provider contact, response loss, restart and reconciliation without redispatch.

`CALLERS.toml` and `qa/b4-no-bypass/KERNEL_AUTHORITY_BOUNDARIES.json` classify the public privileged surfaces, including production trust constructors, raw verification/delivery methods, the bounded dispatch fence and lease pruning.

## Integration prerequisites

Before activation, a candidate must name and exercise a real product process through the registered host, bind a protected `AuthorityClock` and rollback-resistant `AuthorityFrontierStore`, ingest a fresh independently signed revocation feed, establish key-custody/rotation/compromise procedures, retain exact-head plus deterministic synthetic-merge evidence, and pass independent semantic review.

Additional target ModulePorts are composed only at their real owner boundaries with their own caller and qualification evidence. None is inferred from the existence of the generic lease type.

## Integrated Agentd Browser consumer

`hepta-agentd-browser` opens the durable FinalUse owner. `BrowserServoPort::call`
claims the exact grant and crosses the bounded dispatch fence around durable
Browser intent and local worker dispatch. The Browser child receives no
serializable authority token. These non-test callers remain registered in
`CALLERS.toml`; their source composition does not establish product execution
or activation. Fleet mutation uses `dispatch_authority_lease_with_witness` at
the concrete owner boundary, retaining its canonical audit witness.

## Integrated Agentd automation effect host

`AgentdAutomationEffectHost` is the named normal product source path for TaskFlow provider effects. Host schema V2 requires an issuer key ring, independently signed revocation-distributor key ring and feed file, exact provider contract/binding configuration and an absolute external trust root outside Agent home. Ordinary startup rejects the compatibility constructor and uses `FinalUseAuthority::open_state_dir_with_issuer_keys` with the same `AgentdFinalUseTrustStore` as both protected clock and external frontier.

Before provider contact the TaskFlow owner durably records the attempt and the canonical non-authorizing dispatch-entry witness. Provider acknowledgement, timeout or crash is observed separately. A crash or lost response never authorizes redispatch of the same attempt; restart exposes the same pending identity for provider-owned lookup/reconciliation. This closes the repository-controlled host and recovery chain but does not assert that a target clock is attested, a target volume is rollback-independent, or a provider effect has been independently accepted.

### Valid restart after a signed-feed advance

The normal Agentd host now recovers its stored key-ring head using
`recover_state_dir_with_issuer_keys`, checks the exact external frontier, then
authenticates and commits the current feed before returning from startup.
This handles a valid feed advance during downtime without weakening the exact
open API, refunding consumed nonces or accepting restored state behind the
external frontier. Source tests separately retain the strict-open rejection.
