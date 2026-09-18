# Final-use production control composition

This document specifies the repository-implemented control layer around
`FinalUseAuthority`. It supplements `FINAL_USE.md`; it does not weaken or
replace that verifier, its durable nonce burn, or its monotonic revocation
rules.

## Roles and separation

A production-capable host can pin three independent Ed25519 trust roles:

1. **grant issuer** — signs the `FinalUseGrant` verified by `FinalUseAuthority`;
2. **operator approver** — signs `FinalUseApproval`, which binds the exact grant
   semantic digest, signer, grant id and authority epoch;
3. **revocation distributor** — signs `FinalUseRevocationUpdate`, which contains
   one complete monotonic `FinalUseRevocations` head.

`BaoFinalUseHost` additionally owns a closed registry from signed
`consumer_id` to a trusted process-local callback. The request cannot supply a
closure or convert a consumer-name string into code.

The roles may be operated by separate processes and keys. The repository tools
`hepta-final-use-signer`, `hepta-final-use-approver` and
`hepta-final-use-revocation-signer` are separate binaries behind the explicit
`production-authority` feature. None generates a private key. Each signing key
must be provisioned externally and kept in an owner-only file or stronger
approved key-custody boundary.

## Approval protocol

`FinalUseApproval` schema version 1 contains:

- `approver_id`;
- grant `signer_id`;
- `grant_id`;
- `authority_epoch`;
- SHA-256 of `FinalUseGrant::signing_bytes()`.

The signing domain is
`hepta.kernel.authority.final-use-approval.v1\0`. The production host verifies
this signature independently from the issuer signature before provider
dispatch. Payload, destination, scope, subject, nonce, time window or any other
signed grant semantic change changes the grant digest and invalidates approval.

## Revocation distribution protocol

`FinalUseRevocationUpdate` schema version 1 contains a bounded distributor id
and one complete `FinalUseRevocations` head. Its signing domain is
`hepta.kernel.authority.revocation-feed.v1\0`.

`FinalUseRevocationFeedVerifier` pins one distributor identity and public key,
verifies the update signature, and only then calls the durable
`FinalUseAuthority::update_revocations`. The authority store remains the owner
of monotonicity: stale/replayed revisions, epoch rollback and same-epoch
revocation removal fail closed. Transport can therefore retry the same update
without turning transport acknowledgement into authority.

The repository implements authentication and ingestion, not fleet transport
fanout, SLA or consensus. Deployment must independently qualify the mechanism
that delivers the latest signed update to each host and must stop affected
effects when current-head freshness cannot be established.

## Registered Bao consumer host

`BaoFinalUseHost` composes:

- one durable `FinalUseAuthority`;
- one `FinalUseApprovalVerifier`;
- one `FinalUseRevocationFeedVerifier`;
- a non-empty, duplicate-free registry of `RegisteredBaoConsumer` callbacks.

For one secret read the host first verifies independent approval, resolves the
signed `BaoReadRequest.consumer_id` in its registry, and delegates to
`BaoClient::consume_kv_v2`. The lower-level client still performs exact binding
construction, durable single-use claim, pinned HTTPS retrieval, response bounds,
version/digest validation and final authority recheck. An unregistered consumer
fails before dispatch.

`BaoClient::consume_kv_v2` remains public for library qualification and legacy
source compatibility, but B4 caller proof treats the registered host as its
only non-test/non-example product caller in the current tree. No named product
process is activated by this source composition alone.

## Revocation and consumer-entry linearization

The final synchronous entry rule is:

1. acquire the authority mutex;
2. revalidate owner, binding, epoch, revocation and time;
3. release the mutex;
4. enter the already selected trusted synchronous consumer.

The successful validation is the linearization point. A revocation committed
before that point denies entry. A revocation that commits after that point is
ordered after entry and cannot retroactively undo an already-entered effect.
The callback no longer runs while holding the revocation mutex, so a slow,
panicking or re-entrant callback cannot block future revocation updates or
poison the authority mutex.

The callback must still be bounded. A crash or callback error after entry is an
indeterminate effect and requires reconciliation; it is never interpreted as
proof that no effect occurred.

## Authority leases and trusted time / anti-rollback

The general `AuthorityLeaseRegistry` in `src/authority_lease.rs` is the native
owner for the documented `authority_lease` and `capability_revocation` domains.
It provides CAS mutation/revocation, bounded capacity, explicit epoch rollover,
host-supplied trusted time, and a host-supplied anti-rollback frontier.

The local filesystem is not itself an external anti-rollback oracle. The host
must protect and monotonically advance the trusted frontier outside the local
authority directory. Likewise, trusted time is supplied by the host; this
repository does not claim an attested clock service.

## Capacity lifecycle

The final-use nonce/revocation registry and general lease registry are bounded.
The general registry exposes current/max counts and an explicit durable epoch
rollover. Deployments must alert before exhaustion, coordinate epoch change
through the authority owner, and distribute the resulting trusted frontier / 
revocation epoch before admitting new work. No cache eviction or implicit
history reset is allowed.

## Current non-claims

This source closes the repository-level primitives for independent approval,
authenticated revocation ingestion, registered consumer identity and
non-blocking revocation linearization. It does **not** claim:

- fleet revocation transport/freshness SLA or consensus;
- HSM/KMS/operator ceremony qualification;
- an external anti-rollback oracle;
- an attested time service;
- a cross-platform durable authority backend;
- a selected production process caller;
- operator acceptance, activation, canary, promotion or release.

Those remain explicit target-host / external evidence gates and must not be
inferred from source compilation or unit tests.
