# secrets.heptabao current implementation

This document describes executable source, not the long-term target architecture and not a production-release claim. The target contract remains in [TECHNICAL.md](TECHNICAL.md); the dynamic state machine is specified in [SECRET_LEASE_DESIGN.md](SECRET_LEASE_DESIGN.md).

## Current executable surfaces

The module has two intentionally separate secret paths.

1. `BaoClient::consume_kv_v2` performs an exact-version KV v2 read for one string field. KV v2 is versioned static-secret retrieval and does **not** create a provider-native lease.
2. `BaoClient::request_secret_lease`, `renew_secret_lease`, `revoke_secret_lease` and `reconcile_secret_lease` implement provider-native dynamic leases. Issuance supports bounded GET or POST endpoints, a bounded string request map and a bounded set of selected string response fields.

Dynamic secret bytes are never fields of `SecretLeaseRecord` and are never returned by the lease API. Selected values are passed only to the synchronous trusted `BaoSecretFields` callback under final-use authority. Provider-returned lease identity, namespace/path, lifecycle state, TTL metadata and operation digests are durable metadata.

## Durable owners

`codex-hepta-contracts::SecretLeaseRecord` is the lifecycle contract. The record uses these executable states:

`Requesting -> Active -> Renewing -> Active`

`Active -> RevokePending -> Revoked`

Ambiguous paths enter `Unknown`; provider disappearance can resolve to `Expired` or `Revoked`. Deterministic issuance rejection resolves to `Rejected`.

`codex-hepta-evidence` migration `0011_secret_lease_registry.sql` is the current SQLite implementation of `SecretLeaseStore`. Creation is exact-idempotent and returns whether the caller won the insert. Updates use revision compare-and-swap. Immutable identity includes logical lease key, provider, namespace, provider path and original request digest. Once observed, a provider lease ID cannot change.

This SQLite implementation safely coordinates multiple handles/processes using the same database. It is **not** a multi-host distributed-consensus claim. The storage contract is deliberately CAS-shaped so another strongly-consistent backend can implement the same transition rules.

## Provider uncertainty

No lease mutation is retried automatically.

- issuance writes `Requesting` before dispatch;
- renewal writes `Renewing` before dispatch;
- revocation writes `RevokePending` before dispatch;
- timeout, transport loss, a provider 5xx, or an unusable successful reply moves a live operation to `Unknown` when that transition can be durably recorded.

A generic issuance response can be lost after the provider has already created a credential. If no provider lease ID was observed locally, generic OpenBao offers no operation-key lookup that proves whether the issuance happened. `reconcile_secret_lease` therefore returns `ReconciliationRequired` and never reissues automatically.

When a provider lease ID is known, reconciliation uses `POST /v1/sys/leases/lookup`. Renewal consumes the TTL and renewable values returned by OpenBao rather than assuming the requested increment was granted. Revocation uses `POST /v1/sys/leases/revoke` with `sync=true`.

## Final-use replay owner

The local `FinalUseAuthority` remains single-active per owner-controlled state directory. Schema 2 stores the bounded revocation head in `authority.json` and appends each claimed 32-byte nonce to `authority.claims`. Claims no longer rewrite the complete JSON replay set and there is no 16,384-claim logical ceiling.

Schema 1 state is migrated fail-closed. On an epoch increase the stronger head is persisted before the old claim journal is truncated. A crash in that window can create extra denials but cannot reopen an old nonce.

The revocation-head list remains independently bounded; removing the old claim ceiling does not turn the local filesystem store into an unbounded distributed replay service.

## Current limitations

- Generic lost-response issuance without an observed provider lease ID requires provider-specific/operator reconciliation.
- FinalUse filesystem state is local and single-active. It is not supported on unqualified distributed/NFS locking.
- The SQLite lease registry is not a multi-host active-active backend.
- The trusted callback is a privileged host boundary. A malicious callback can copy or exfiltrate bytes by side effect; a signed consumer ID does not authenticate an arbitrary closure.
- Application-owned provider response buffers, selected secret strings and request values use zeroizing owners. TLS, HTTP, JSON and allocator internals can still create temporary plaintext copies; this is not locked-memory secrecy.
- Dynamic lease records deliberately do not retain per-value SHA-256 fingerprints. Provider lease IDs are privileged metadata and should not be copied into general logs or unrelated receipts.

## Qualification status

Source presence is not qualification. Exact-candidate qualification is produced by the dedicated secrets.heptabao workflow and binds its receipt to the checked-out commit, tree and security-sensitive source digests. A historical receipt must never be used to claim a later HEAD passed.
