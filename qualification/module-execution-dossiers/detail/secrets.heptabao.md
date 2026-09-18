# secrets.heptabao: implementation design

Parent: `docs/modules/secrets.heptabao/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: exact-version KV v2 consumption plus provider-native dynamic SecretLease issue/renew/revoke/reconcile are source implemented; remaining composition, distributed-HA and independent-acceptance work is listed in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `external/HeptaBao`, `codex-rs/hepta-bao-adapter`.
Packages: `HEPTABAO-1-SECRET-BOUNDARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`BaoClient::request_secret_lease(store, authority, grant, request, consumer) -> SecretLeaseRecord`; `BaoClient::renew_secret_lease(...) -> SecretLeaseRecord`; `BaoClient::revoke_secret_lease(...) -> SecretLeaseRecord`; `BaoClient::reconcile_secret_lease(...) -> SecretLeaseRecord`. Exact-version static retrieval remains `BaoClient::consume_kv_v2`. Deliver dynamic values only through the trusted synchronous consumer callback; lifecycle records contain provider/lease metadata, never raw values. Freeze the external source pin/API version and verify it before production activation.

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

- **Implemented entrypoints:** `consume_kv_v2` and `binding` in [https_consumer.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer.rs); `request_secret_lease_binding`, `request_secret_lease`, `renew_secret_lease_binding`, `renew_secret_lease`, `revoke_secret_lease_binding`, `revoke_secret_lease`, `reconcile_secret_lease_binding` and `reconcile_secret_lease` in [lease_lifecycle.rs](../../../codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs).
- **State and recovery:** [secret_lease.rs](../../../codex-rs/hepta-contracts/src/secret_lease.rs) defines the durable `Requesting / Active / Renewing / RevokePending / Unknown / Revoked / Expired / Rejected` lifecycle and strong-CAS store interface. [0011_secret_lease_registry.sql](../../../codex-rs/hepta-evidence/migrations/0011_secret_lease_registry.sql) plus [secret_lease_store.rs](../../../codex-rs/hepta-evidence/src/secret_lease_store.rs) provide the current SQLite metadata owner. Provider mutations are never automatically retried after ambiguous dispatch.
- **Dynamic secret boundary:** selected provider response strings remain ephemeral and are delivered only to `BaoSecretFields` inside the trusted synchronous callback. They are not stored in `SecretLeaseRecord`, evidence SQLite or lifecycle receipts, and the dynamic path deliberately does not retain a per-value SHA-256 fingerprint.
- **Final-use replay:** [final_use_store.rs](../../../codex-rs/hepta-contracts/src/final_use_store.rs) schema 2 stores the bounded revocation head separately from an append-only fixed-width nonce journal. Claims no longer rewrite the complete replay set and no longer have the former 16,384-claim logical ceiling. The filesystem owner is still local/single-active.
- **Source tests:** [https_consumer_tests.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs), [lease_lifecycle_tests.rs](../../../codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs), [final_use_tests.rs](../../../codex-rs/hepta-contracts/src/final_use_tests.rs), [secret_lease_store_tests.rs](../../../codex-rs/hepta-evidence/src/secret_lease_store_tests.rs), and the isolated [real_service_smoke.py](../../../codex-rs/hepta-bao-adapter/qa/real_service_smoke.py). These source/test identities are not themselves execution receipts.
- **Implementation and operating references:** [CURRENT_IMPLEMENTATION.md](../../../docs/modules/secrets.heptabao/CURRENT_IMPLEMENTATION.md), [SECRET_LEASE_DESIGN.md](../../../docs/modules/secrets.heptabao/SECRET_LEASE_DESIGN.md), [FAILURE_RECOVERY.md](../../../docs/modules/secrets.heptabao/FAILURE_RECOVERY.md), [HA_AND_STORAGE.md](../../../docs/modules/secrets.heptabao/HA_AND_STORAGE.md), [SECURITY_INVARIANTS.md](../../../docs/modules/secrets.heptabao/SECURITY_INVARIANTS.md), and [adapter README](../../../codex-rs/hepta-bao-adapter/README.md).
- **Remaining work / non-claims:** generic issuance whose response is lost before a provider lease ID is observed cannot be safely auto-reconciled by generic OpenBao APIs and requires engine-specific/operator evidence; the checked-in SQLite lease owner and filesystem FinalUse owner are not multi-host active-active consensus backends; the trusted callback remains a privileged host capability; exact-candidate CI, product composition, target-host qualification and independent acceptance remain separate gates. The external HeptaBao service also owns wider capabilities that must be assessed at its own source pin.
