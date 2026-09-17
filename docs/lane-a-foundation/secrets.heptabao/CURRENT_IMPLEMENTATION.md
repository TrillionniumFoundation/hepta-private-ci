# `secrets.heptabao` current implementation

## Current executable contract

The current native source implements two host-composed boundaries:

- `BaoClient::consume_kv_v2`: pinned-CA HTTPS read of one string field from one exact KV-v2 version, with independently signed final-use admission and live revalidation before callback entry.
- `BaoLeaseManager`: dynamic provider secret issuance plus durable lease renew, revoke and reconciliation state transitions.

Dynamic provider fields are decoded into application-owned zeroizing buffers and exposed only through a borrowed `SecretLeaseView` to an `EnrolledSecretConsumer`. Ordinary receipts and durable lease records contain metadata only.

Provider mutation intent is fsync-persisted before dispatch. One admitted mutation attempt sends at most one provider request. Timeout, transport loss, server-side uncertainty or an unusable successful response after dispatch enters an explicit `Indeterminate*` state rather than an automatic retry.

## Public symbols and source bindings

- Exact KV boundary: `BaoToken`, `BaoReadRequest`, `BaoSecretReceipt`, `BaoClient`, `BaoClientError`, `BaoClient::binding`, `BaoClient::consume_kv_v2` in `codex-rs/hepta-bao-adapter/src/https_consumer.rs`.
- Dynamic lease boundary: `BaoLeaseManager`, `SecretLeaseRequest`, `RenewSecretLeaseRequest`, `RevokeSecretLeaseRequest`, `ReconcileSecretLeaseRequest`, `ReconcileIndeterminateIssueRequest`, `SecretLeaseMetadata`, `SecretLeaseState`, `SecretLeaseView`, `EnrolledSecretConsumer` in `codex-rs/hepta-bao-adapter/src/lease.rs`.
- Durable lease metadata journal: `codex-rs/hepta-bao-adapter/src/lease_store.rs`.
- Final-use grant and durable replay/revocation state: `codex-rs/hepta-contracts/src/final_use.rs` and `final_use_store.rs`.
- Detailed current implementation and host integration: `docs/modules/secrets.heptabao/CURRENT_IMPLEMENTATION.md` and `codex-rs/hepta-bao-adapter/README.md`.

## Durability and activation

External HeptaBao remains authoritative for provider secret values and provider lease truth. Local durability is limited to metadata/control facts:

- destination-bound lease lifecycle events in `leases.events`;
- lease-store schema/enrollment metadata in `leases.meta.json`;
- final-use trust/revocation metadata in `authority.json`;
- fixed-width `(authority_epoch, nonce)` replay claims in `authority.claims`.

The lease journal contains provider lease identity, path/namespace, consumer scope, expiry, renewability, generation, operation identity and lifecycle state; it does not contain raw dynamic provider values or provider tokens.

Activation still requires protected host configuration, provider token, pinned TLS trust, independently signed final-use grants, private persistent state, a named product caller and an audited host-selected consumer callback. Source implementation does not grant production activation or acceptance.

## Target-only design

The following remain outside the current source claim:

- concurrent writers sharing one authority/destination identity through a generic strongly consistent distributed replay backend;
- provider-independent recovery of credential bytes after a lost dynamic-issuance response;
- a sandbox that makes an untrusted in-process callback safe;
- quota settlement and complete product operation/evidence composition;
- automatic production enrollment, operator acceptance, promotion or release.

Active-active deployment is supported through destination/authority sharding: every active replica has a distinct signed `provider:heptabao:<replica>` destination and private durable replay/lease state. A grant for one replica fails binding validation at another replica. This is not a claim of a shared multi-writer database.

## Known limits and non-claims

Generic OpenBao-compatible issuance has no universal operation-key lookup for arbitrary dynamic-secret plugins. If the acknowledgement is lost, the operation remains `IndeterminateIssue` and is never blindly reissued. An externally observed candidate provider lease ID may be verified by lease lookup and adopted as `Orphaned`; the lost credential bytes are not reconstructed.

Renew/revoke uncertainty is reconciled through provider lease lookup. Provider 404 closes the local lease as revoked; a live lookup refreshes TTL/renewability and restores the corresponding live state.

`EnrolledSecretConsumer` makes callback identity explicit but is not a sandbox. Trusted callback code can copy secret bytes through side effects. The older KV callback has the same trusted-host assumption.

Application-owned provider tokens, bounded response bodies and decoded secret strings are zeroized on drop. This does not prove that TLS, HTTP, serde/parser internals, allocators, kernel buffers or trusted consumers created no transient plaintext copy.

Secret/response SHA-256 values used by the KV path are excluded from ordinary serialization and redacted from `Debug`; exporting stable secret-derived fingerprints is a separate security-sensitive contract.

## Verification

Source tests cover pinned TLS/exact KV reads, forged/replayed grants, revocation during network wait, dynamic issue with borrowed secret delivery only, lost issue acknowledgement with no blind retry, renew timeout plus provider lookup reconciliation, revoke timeout plus provider-404 reconciliation, orphan adoption after lost issue response, destination-sharded grant isolation, destination-bound lease state and replay persistence past the former 16,384-claim boundary.

`.github/workflows/heptabao-lease-qualification.yml` is the focused exact-candidate gate. It runs package format, focused tests and strict Clippy, then emits a secret-free receipt binding source/tested SHA, tested tree, external HeptaBao pin and hashes of the executed command records.

Historical `qa/evidence/*` records retain their original candidate scope and are not current-head proof.

## Integration prerequisites

A production caller must enroll an exact destination identity, durable state paths and one audited consumer; provision provider/TLS/issuer trust out of band; preserve replay, revocation and unresolved lease state across restart/failover; surface `Indeterminate*` and `Orphaned` as reconciliation/cleanup work; and never delete durable state or blindly redispatch an unknown provider effect.

A failover process that keeps the same replica destination must reopen the same durable authority/lease state. A deployment that cannot preserve that invariant must issue a new destination/authority epoch rather than silently starting an empty replay registry.

Raw secret bytes must never enter general logs, prompts, learning records, ordinary receipts or generic evidence exports.
