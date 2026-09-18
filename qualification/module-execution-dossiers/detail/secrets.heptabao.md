# secrets.heptabao: implementation design

Parent: `docs/modules/secrets.heptabao/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: exact-version KV v2 final-use and provider-backed dynamic SecretLease issue/renew/revoke/reconciliation are source implemented; product composition and independent acceptance remain separate and are listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `external/HeptaBao`, `codex-rs/hepta-bao-adapter`.
Packages: `HEPTABAO-1-SECRET-BOUNDARY`.

Operation signatures below describe the contract and are now backed by the native entrypoints identified in section 8. Product composition, external-provider qualification and release remain separate. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`request_secret_lease(...) -> BaoLeaseReceipt`; `renew_secret_lease(...) -> BaoLeaseMetadata`; `revoke_secret_lease(...) -> BaoLeaseMetadata`; `lookup_secret_lease(...) -> BaoLeaseMetadata`; `reconcile_lease_operation(...) -> ()`. Deliver an authorized secret only through the dedicated consumer channel; ordinary receipts contain references and lease metadata, never raw values. Freeze the external source pin/API version and verify it before enabling an adapter.

## 3. State records and transaction design

The external secret authority remains the source of secret values and leases. Local `secret_metadata` and `secret_lease` records contain external identity, consumer scope, expiry, rotation generation and revocation status only. Any cache is sealed, strictly TTL/generation-bound and excluded from learning/export paths; its protection and erasure are independently tested.

## 4. Deterministic algorithm and scheduling

Validate host-authenticated grant and quota; resolve the enrolled external authority; bind final request and operation; call the typed adapter; observe external lease identity and expiry. Lost acknowledgement yields indeterminate until the external authority is queried. Rotation invalidates dependent caches and cannot silently reuse a revoked generation.

## 5. Capacity and performance profile

Pilot metadata <= 16 KiB, one external operation per request, bounded TTL and renewals from policy. Separate secret-provider latency from metadata cache latency. Fail closed when the external authority or revocation frontier is unavailable.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- BAO-01: raw secret bytes are absent from logs, receipts, learning rows, exceptions and exports.
- BAO-02: key/lease rotation invalidates the previous generation across process restart.
- BAO-03: lost acknowledgement is reconciled without issuing duplicate unrestricted leases.
- BAO-04: expired/revoked caller scope is rejected before the external API call.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Run first against an isolated fake or enrolled non-production authority. Real authority use requires exact provider identity, consent and independent acceptance. Rollback preserves current revocations and cannot restore secret values from an old general-purpose backup.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented static entrypoints:** `binding` and `consume_kv_v2` in [https_consumer.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer.rs). Final delivery resolves the signed consumer ID through a host-built `TrustedConsumerRegistry`; there is no per-request public callback.
- **Implemented lease entrypoints:** `issue_binding`, `request_secret_lease`, `renew_secret_lease`, `revoke_secret_lease`, `lookup_secret_lease`, `reconciliation_binding` and `reconcile_lease_operation` in [lease_lifecycle.rs](../../../codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs).
- **State and recovery:** [lease_store.rs](../../../codex-rs/hepta-bao-adapter/src/lease_store.rs) persists only operation/lease metadata. Effect operations move durably through `Prepared -> Dispatched -> Succeeded|Rejected|Indeterminate`; an ambiguous dispatched operation is fenced from blind retry until an explicit signed reconciliation observation resolves it.
- **Final-use replay state:** [final_use_store.rs](../../../codex-rs/hepta-contracts/src/final_use_store.rs) uses a small schema-v2 authority head plus an append-only checksummed replay journal. Active processes share the state directory through short cross-process fences and incremental journal-tail refresh; the former 16,384 claim ceiling and whole-state rewrite on every claim are removed.
- **Secret handling:** application-owned provider tokens, response bodies, decoded strings and dynamic-secret payload buffers zeroize on drop. Serialized/debug receipts omit stable secret/body fingerprints. This is not a claim of complete plaintext exclusion from TLS/HTTP/allocator/kernel internals.
- **Source tests:** [https_consumer_tests.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs), [lease_lifecycle_tests.rs](../../../codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs), [final_use_tests.rs](../../../codex-rs/hepta-contracts/src/final_use_tests.rs), plus the existing real-service smoke fixture for the previously qualified KV profile.
- **Authoritative implementation notes:** [CURRENT_IMPLEMENTATION.md](../../../docs/modules/secrets.heptabao/CURRENT_IMPLEMENTATION.md), [SECRET_LEASE_DESIGN.md](../../../docs/modules/secrets.heptabao/SECRET_LEASE_DESIGN.md), [FAILURE_RECOVERY.md](../../../docs/modules/secrets.heptabao/FAILURE_RECOVERY.md), [HA_AND_STORAGE.md](../../../docs/modules/secrets.heptabao/HA_AND_STORAGE.md), and the adapter [README](../../../codex-rs/hepta-bao-adapter/README.md).
- **Remaining integration/qualification:** compose a named production caller, qualify the chosen HeptaBao dynamic-secret engine/profile and multi-host state backend, and obtain independent acceptance/promotion/release evidence. The generic V1 issue profile is intentionally GET-only with string secret fields; wider provider request shapes require a new typed profile.
