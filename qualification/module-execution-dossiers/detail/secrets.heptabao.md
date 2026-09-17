# secrets.heptabao: implementation design

Parent: `docs/modules/secrets.heptabao/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: exact-version KV v2 consumption and durable dynamic secret lease issuance/renew/revoke/reconciliation are native source implementations; product composition, target-host qualification, independent acceptance and release remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

The exact current source contract is summarized in [`docs/modules/secrets.heptabao/CURRENT_IMPLEMENTATION.md`](../../../docs/modules/secrets.heptabao/CURRENT_IMPLEMENTATION.md). Where this design describes a mature target beyond current source, the current-implementation document controls source-status claims.

## 1. Source and work envelope

Roots: `external/HeptaBao`, `codex-rs/hepta-bao-adapter`; shared final-use replay persistence is owned by `codex-rs/hepta-contracts` and is consumed rather than duplicated by this module.
Packages: `HEPTABAO-1-SECRET-BOUNDARY`.

Preserve existing authority and execution spines. The adapter may own secret-lease metadata but must not mint the authority that authorizes its own provider effects.

## 2. Public operations and contract details

Native dynamic operations are `BaoLeaseManager::request_secret_lease`, `renew_secret_lease`, `revoke_secret_lease`, `reconcile_secret_lease` and `reconcile_indeterminate_issue`. The manager also exposes operation-specific final-use binding builders and metadata lookup. `BaoClient::consume_kv_v2` remains the exact-version static read path.

An authorized dynamic secret is delivered only through an `EnrolledSecretConsumer` as a borrowed `SecretLeaseView`; ordinary receipts contain lease metadata, never raw provider values. The external source pin/API version remains frozen by `external/HeptaBao/EXTERNAL_SOURCE.json` and is independently qualified before production enablement.

## 3. State records and transaction design

The external secret authority remains the source of secret values and provider lease truth. Local `secret_metadata` / `secret_lease` state contains provider identity, consumer scope, expiry, generation, operation identity and revocation/lifecycle state only.

The native local store is a private Unix directory containing an exclusive owner lock, destination-bound schema metadata and an append-only fsynced lifecycle event journal. Dynamic secret values and provider tokens are never journal fields. Mutation intent is persisted before provider dispatch. Conflicting reuse of an operation ID fails closed; a matching operation already in an uncertain state requires reconciliation instead of redispatch.

The lease state machine includes `IssuePending`, `Active`, `RenewPending`, `RevokePending`, `IndeterminateIssue`, `IndeterminateRenew`, `IndeterminateRevoke`, `Orphaned`, `Revoked`, `Expired` and `Rejected`.

## 4. Deterministic algorithm and reconciliation

Validate and bind the complete host-authorized operation, persist pending metadata, burn the independently signed final-use nonce, then perform exactly one provider operation without automatic retry.

- A confirmed issue response creates `Active` metadata before raw fields enter the enrolled callback.
- A definite pre-effect/provider client rejection records a terminal or restored state.
- Timeout, transport loss, server-side uncertainty or an unusable successful response after a mutation is dispatched records an `Indeterminate*` state.
- Renew/revoke uncertainty is reconciled through the provider lease lookup endpoint. Provider 404 means the lease is no longer live and is recorded as revoked.
- Generic OpenBao-compatible issuance has no universal operation-key lookup. A lost issue acknowledgement therefore cannot be treated as failure and is never blindly retried. If an operator/provider-specific observer supplies a candidate lease ID, the adapter verifies it through lease lookup and adopts it as `Orphaned`; the lost credential bytes are not reconstructed.

Rotation/renewal advances local generation only after a confirmed/observed provider transition and cannot silently reuse a revoked generation.

## 5. Capacity and performance profile

Dynamic request metadata is bounded to 16 KiB; dynamic output is bounded by field count, per-field size and the existing 1 MiB response limit. One provider request is dispatched per admitted mutation attempt; there is no automatic retry loop.

Kernel final-use replay claims are persisted in an append-only fixed-width journal rather than rewriting the complete nonce set. The old 16,384-claim epoch semantic stop is removed; a large local journal-size guard remains a fail-closed resource ceiling. Revocation metadata remains a small atomic snapshot.

A local authority/lease directory is single-owner. Active-active deployment is supported by destination sharding: each active replica receives a distinct `provider:heptabao:<replica>` final-use destination and private local state, so a signed grant cannot be replayed on another replica. Sharing one authority identity across concurrent writers still requires a separately qualified strongly consistent backend and is not claimed by this implementation.

## 6. Concrete verification cases

- BAO-01: raw secret bytes are absent from durable state, ordinary receipts, logs/debug projections, learning rows and exports.
- BAO-02: lease lifecycle metadata survives process restart and destination-state substitution fails closed.
- BAO-03: a lost issuance acknowledgement enters `IndeterminateIssue`; the same operation ID cannot redispatch and an observed provider lease can only be adopted after lookup verification.
- BAO-04: renew timeout enters `IndeterminateRenew` and reconciles from provider lease truth.
- BAO-05: revoke timeout enters `IndeterminateRevoke` and provider 404 reconciliation closes it as revoked.
- BAO-06: final-use replay state survives restart/process death and exceeds the former 16,384-claim boundary without growing the authority metadata snapshot per claim.
- BAO-07: a grant signed for one replica destination fails binding validation on another replica.
- BAO-08: reserved provider control mounts are rejected by the dynamic issue adapter.

These source tests are not operator acceptance or release receipts. Exact-candidate CI evidence is emitted separately.

## 7. Integration, rollback and capability ceiling

Run first against an isolated fake or enrolled non-production authority. Real authority use requires exact provider identity, policy/consent and independent acceptance. Rollback must preserve live revocations and unresolved provider-effect records; it must never turn `Indeterminate*` into an empty/new lease registry.

The Rust callback remains trusted host code, not a sandbox. `EnrolledSecretConsumer` makes consumer identity explicit but cannot prevent an already trusted callback from copying bytes through side effects. Untrusted consumers require process/sandbox isolation outside this crate.

Application-owned provider tokens, HTTP bodies and decoded secret strings are zeroized on drop. This is not a claim that TLS/HTTP/parser/allocator/kernel or trusted-consumer internals never create transient plaintext copies.

Secret-derived response/value SHA-256 fields used by the KV path are excluded from ordinary serialization and redacted from `Debug`; exporting a stable secret fingerprint is a separate security-sensitive contract.

## 8. Current native implementation

- **Exact KV path:** `BaoClient`, `binding`, `consume_kv_v2` in [`https_consumer.rs`](../../../codex-rs/hepta-bao-adapter/src/https_consumer.rs). `BaoClient::new_for_destination` adds replica-bound destination identity.
- **Dynamic lifecycle:** `BaoLeaseManager` and the public request/metadata/state types in [`lease.rs`](../../../codex-rs/hepta-bao-adapter/src/lease.rs).
- **Durable lease metadata:** [`lease_store.rs`](../../../codex-rs/hepta-bao-adapter/src/lease_store.rs), with a private destination-bound lifecycle journal and single local owner lock.
- **Shared replay/revocation persistence:** `FinalUseAuthority` plus [`final_use_store.rs`](../../../codex-rs/hepta-contracts/src/final_use_store.rs); claims use an fsynced fixed-record replay journal while revocation/trust metadata uses the atomic state snapshot.
- **Source tests:** [`https_consumer_tests.rs`](../../../codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs), [`lease_tests.rs`](../../../codex-rs/hepta-bao-adapter/src/lease_tests.rs), and [`final_use_tests.rs`](../../../codex-rs/hepta-contracts/src/final_use_tests.rs).
- **Exact-candidate evidence:** [`.github/workflows/heptabao-lease-qualification.yml`](../../../.github/workflows/heptabao-lease-qualification.yml) emits a candidate-bound receipt from executed format/test/Clippy command records through [`emit_verification_receipt.py`](../../../codex-rs/hepta-bao-adapter/qa/emit_verification_receipt.py).
- **Current capability ceiling:** no claim of a generic strongly consistent multi-writer replay store, provider-independent recovery of credential bytes after a lost issuance response, untrusted in-process callback sandboxing, product activation, operator acceptance or release. Those require separate composition/qualification work rather than hidden fallback behavior.
