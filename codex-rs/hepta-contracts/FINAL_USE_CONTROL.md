# Final-use production control composition

This document specifies the repository-controlled production control layer
around `FinalUseAuthority`. It supplements `FINAL_USE.md`; it does not weaken
the durable nonce burn, exact binding, live revocation or fail-closed rules.

The general-lease trust decision is separately frozen in
[`ADR-0001-LEASE-TRUST-MODEL.md`](../../docs/modules/kernel.authority/ADR-0001-LEASE-TRUST-MODEL.md)
and the final-use ordering contract is in
[`LINEARIZATION.md`](../../docs/modules/kernel.authority/LINEARIZATION.md).

## Roles, key rotation and separation

A production-capable host can pin three independent Ed25519 trust roles:

1. **grant issuer** — signs `FinalUseGrant`;
2. **operator approver** — signs `FinalUseApproval` over the exact grant
   semantic digest;
3. **revocation distributor** — signs fresh `FinalUseRevocationUpdate` heads.

All three roles support bounded epoch-window rotation. The grant issuer uses
`FinalUseIssuerTrustKey`; approval and revocation roles use
`FinalUseTrustKey`. Each ring accepts at most eight keys. Each entry has a stable key id and inclusive
authority-epoch window. Overlapping windows permit staged rotation; a key
outside its epoch window is rejected even when its signature is otherwise
valid. Verification can report the selected key id for audit evidence.
Duplicate ids/keys, weak Ed25519 keys and invalid epoch windows are rejected.

The one-key verifier constructors and the single-key
`FinalUseAuthority::open_state_dir_with_trust` remain compatibility helpers.
Production host configuration should use `open_state_dir_with_issuer_keys`
plus the control verifiers' `new_with_keys` constructors and retain required
historical trust material in its audit/evidence system. The complete issuer
trust-set digest is pinned into FinalUse durable store schema V2; legacy schema
V1 single-key state is never silently upgraded into a key-ring trust model. Repository utilities never
generate private keys; custody, compromise response and HSM/KMS policy remain
external operational responsibilities.

## Approval protocol

`FinalUseApproval` remains schema version 1 and binds:

- approver identity;
- grant issuer identity and grant id;
- authority epoch;
- SHA-256 of the exact `FinalUseGrant::signing_bytes()` payload.

The signing domain remains
`hepta.kernel.authority.final-use-approval.v1\0`. Any change to subject,
destination, scope, payload, nonce, time window or other grant semantic field
changes the digest and invalidates approval.

## Revocation distribution protocol V2

`FinalUseRevocationUpdate` schema version 2 contains:

- bounded distributor identity;
- one complete monotonic `FinalUseRevocations` head;
- signed `issued_at_unix_ms`;
- signed `expires_at_unix_ms`.

The signing domain is
`hepta.kernel.authority.revocation-feed.v2\0`. The window must be positive
and no longer than `MAX_REVOCATION_FEED_LIFETIME_MS` (300,000 ms).
Verification rejects not-yet-valid and stale updates before changing the
authority owner.

`FinalUseRevocationFeedVerifier::apply` verifies identity, shape, freshness,
active epoch-key and Ed25519 signature, then delegates the head to
`FinalUseAuthority::update_revocations`. The durable authority owner still
enforces monotonic revision/epoch and same-epoch revocation-superset rules.
The returned `FinalUseRevocationReceipt` records the distributor, selected
trust key, head epoch/revision and freshness deadline without secret material.

A signature is therefore not a perpetual revocation credential. Transport may
retry while the signed freshness window is current; deployment must obtain a
new head before expiry.

## Enrolled-node convergence acknowledgement

`FinalUseRevocationAck` is a separate node-signed receipt over the exact
revocation-update digest, distributor identity, epoch/revision and local apply
time. `FinalUseRevocationConvergenceVerifier` pins a closed set of at most 256
enrolled nodes, each with its own bounded epoch key ring. It verifies every
supplied acknowledgement and returns deterministic acknowledged/missing node
sets for one still-fresh update.

A missing node is never silently counted as converged. Duplicate, unknown,
forged, wrong-head, pre-issuance or post-expiry acknowledgements fail closed.
A restarted host has no Bao freshness authority until it applies a current
signed update again; only after that catch-up may its host identity produce an
ack. The resulting report can prove repository-protocol convergence, but it
does not perform transport or prove a deployment's latency SLA by itself.

## Registered Bao consumer host and partition policy

`BaoFinalUseHost` composes one durable `FinalUseAuthority`, independent
approval verifier, independent revocation-feed verifier, owner-bound
`AuthorityClock`, and a closed non-empty registry of
`RegisteredBaoConsumer` callbacks.

The host starts with **no fresh revocation knowledge**. It must ingest a current
signed V2 head before allowing secret final use. It records only the signed
freshness deadline. When the bound trusted clock reaches that deadline, new
secret final use fails with `StaleRevocationFeed` until another authenticated
head advances the owner. This makes the repository host policy for network
partition explicit: stale revocation knowledge stops new affected effects.

The request's signed `consumer_id` must resolve to the pre-enrolled callback.
Independent approval is checked before provider dispatch. The lower Bao client
still performs exact request binding, single-use claim, pinned HTTPS, response
bounds, exact version/digest checks and final VerifiedUse revalidation.

`BaoClient::consume_kv_v2` remains public for lower-level qualification, but
B4 permits its non-test caller only from the registered host. No deployed
product process is selected merely by this source composition.

## External time and anti-rollback

Both authority families now expose explicit host trust interfaces:

- `AuthorityClock` supplies time. Product code cannot pass arbitrary
  `now_unix_ms` into a lease verifier.
- `AuthorityFrontierStore<F>` supplies externally durable load/CAS state that
  must survive rollback/replacement of the local authority directory.

General-lease production construction uses
`AuthorityLeaseRegistry::open_state_dir_with_trust`. FinalUse production
construction uses `FinalUseAuthority::open_state_dir_with_trust`.
On open, local and external frontiers must match exactly.

For each mutation, the owner CAS-advances the external frontier **before**
committing the corresponding local fsync/rename. CAS failure fences the live
owner. If the external CAS succeeds but the local commit fails or the process
crashes, reopening observes the external frontier ahead of local state and
fails closed until explicit operator recovery. This is intentional uncertainty,
not an automatic rollback.

`SystemAuthorityClock` and constructors without an external frontier exist for
compatibility/tests. They are not an attested-time or external anti-rollback
claim and must not be used to upgrade production qualification.

## Least authority for general leases

`AuthorityLeaseRegistry` is the non-cloneable administrative owner. It alone
can put/replace leases, revoke, prune expired unrevoked leases and advance
epochs. `AuthorityLeaseVerifier` is a cloneable attenuation that can read and
perform live verification but cannot mutate authority state.

A verified token is rechecked against the **exact current lease record**.
Replacing a lease invalidates an outstanding token from an older revision.
Revocation retry is idempotent only when lease/revision, reason digest **and
revocation timestamp** are identical.

The lease is registry-authoritative, not a portable signed bearer. See ADR-0001.

## Linearization

There are two explicit final-use boundaries:

- `deliver_final_use` / `with_verified_use`: successful live validation is
  the consumer-entry linearization point; the owner lock is released before
  bounded consumer code.
- `dispatch_final_use` / `with_dispatch_boundary`: the lock is held only
  across a short local irreversible dispatch transition, then released.

Neither boundary may hold the authority mutex over remote provider waits,
reconciliation loops or arbitrary plugin/user code. See `LINEARIZATION.md`
for the normative ordering and crash-uncertainty rule.

## Capacity lifecycle

The general lease owner remains bounded at 16,384 leases and 16,384 revocation
records. `prune_expired_leases` provides bounded online reclamation (maximum
1,024 entries per call) for expired **unrevoked** leases. Revocation tombstones
are not silently collected inside an epoch. Epoch advance fences prior authority
and clears bounded history.

FinalUse nonce and revocation state remains bounded and uses explicit epoch
rollover. It does not silently evict replay history. Hosts monitor the exposed
capacity snapshots and rotate epoch before fail-closed exhaustion.

## Current non-claims

The repository-controlled candidate implements the primitives above but does
**not** claim:

- a fleet transport, consensus service or measured convergence-latency SLA (the signed per-node convergence proof is implemented);
- an attested production clock implementation;
- an externally deployed anti-rollback frontier backend;
- HSM/KMS custody, rotation ceremony or compromise-response qualification;
- a cross-platform durable authority store;
- product composition for every registered kernel.authority ModulePort;
- independent acceptance, activation, canary, promotion or release.

The canonical target/current/product/evidence table is
[`TRACEABILITY.md`](../../docs/modules/kernel.authority/TRACEABILITY.md).
