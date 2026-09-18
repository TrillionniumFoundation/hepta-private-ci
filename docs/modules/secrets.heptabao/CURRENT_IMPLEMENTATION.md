# secrets.heptabao current implementation

This file describes only code that exists in the current source tree. It is not
an activation, production-readiness, or release claim.

## Static KV v2 final-use path

`BaoClient::consume_kv_v2` performs one exact-version HTTPS KV v2 read. It
requires an independently signed `FinalUseGrant`, burns the grant nonce before
network dispatch, validates the exact response version and expected digest, and
revalidates live authority immediately before delivering bytes.

Final delivery no longer accepts an arbitrary call-site closure. A host builds
a `TrustedConsumerRegistry` during composition; the signed `consumer_id`
selects one registered entry. Request/plugin data cannot construct or replace
the consumer at final-use time.

Application-owned provider tokens, HTTP response bodies, decoded KV strings and
dynamic-secret payload buffers are zeroized on drop. This does not claim that
TLS, HTTP, allocator, kernel, crash-dump or other library internals never hold
temporary plaintext copies.

Serialized/debug receipts omit provider-body and secret SHA-256 fingerprints.
The static adapter still verifies the expected digest internally, but stable
low-entropy secret fingerprints are not emitted as ordinary receipts.

## Dynamic SecretLease path

The implemented V1 dynamic profile is:

- `request_secret_lease`: one provider-native GET under an explicitly enrolled
  mount/path. The response must contain a non-empty provider `lease_id`, bounded
  TTL, renewable flag and a non-empty map of string secret fields.
- `renew_secret_lease`: one POST to `/v1/sys/leases/renew` for a lease already
  owned by this registry.
- `revoke_secret_lease`: one POST to `/v1/sys/leases/revoke` for a known lease.
- `lookup_secret_lease`: read-only lookup through `/v1/sys/leases/lookup`.
- `reconcile_lease_operation`: apply an explicit independently signed
  reconciliation observation to a previously indeterminate operation.

The V1 dynamic issue profile deliberately does not accept arbitrary JSON bodies
or arbitrary HTTP methods. Engines that require a different request schema need
a separately versioned typed profile.

## Durable lease-operation state

`BaoLeaseRegistry` stores metadata only: operation identity/digest/state and
lease identity, TTL, renewable flag, consumer, scope digest and generation.
It stores no provider token, secret bytes, response body or secret fingerprint.

Each effect operation follows:

`Prepared -> Dispatched -> Succeeded | Rejected | Indeterminate`.

The transition to `Dispatched` is durable before network I/O. After that point,
a timeout, transport failure, 5xx/unexpected status, oversized body, malformed
success body, or invalid success semantics becomes `Indeterminate`. The same
operation ID is fenced before another authority claim or network dispatch.

A signed reconciliation observation can resolve an indeterminate operation as:

- `NotApplied`: return the operation to `Prepared`; a new independently signed
  grant is required before dispatch.
- `Applied`: persist the externally reconciled lease metadata and close the
  operation as succeeded.
- `Rejected`: terminally close the operation without retry.

Known-lease lookup updates observed lease metadata but intentionally does not
pretend that provider state proves which earlier ambiguous operation caused it.

## Final-use replay/revocation storage

`FinalUseAuthority` now stores a small schema-v2 authority head plus an
append-only checksummed `claims.log`. One claim appends and syncs one fixed-size
record instead of serializing the complete nonce set.

Owners cache a verified journal offset. Under the cross-process mutation lock
they refresh the small head and only the journal tail appended since their last
synchronization. There is no 16,384-claim per-epoch rejection in the current
claim path. Legacy schema-v1 state migrates without silently evicting old claims.

The OS lock is no longer held for the process lifetime. Multiple processes may
open the same qualified POSIX state directory. Claim, revocation mutation and
final synchronous secret delivery serialize through the same short-lived lock,
so active owners observe durable replay and revocation changes before acting.

This local backend requires one filesystem whose locking, atomic same-directory
rename and fsync semantics are qualified. NFS/object storage/disconnected local
copies are not a distributed consensus backend.

## Source and tests

Primary implementation files:

- `codex-rs/hepta-bao-adapter/src/https_consumer.rs`
- `codex-rs/hepta-bao-adapter/src/consumer.rs`
- `codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs`
- `codex-rs/hepta-bao-adapter/src/lease_store.rs`
- `codex-rs/hepta-contracts/src/final_use.rs`
- `codex-rs/hepta-contracts/src/final_use_store.rs`

Focused tests include static final-use TLS cases, dynamic issue/renew/revoke,
no-blind-retry timeout behavior, signed reconciliation, multi-owner replay and
revocation visibility, restart replay and legacy replay-registry migration.
