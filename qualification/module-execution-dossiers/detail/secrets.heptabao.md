# secrets.heptabao: implementation design

Parent: `docs/modules/secrets.heptabao/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: authorized exact-version KV v2 HTTPS read consumer plus durable metadata-only lease lifecycle/reconciliation owner implemented; provider-native dynamic lease dispatch and independent acceptance remain open in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `external/HeptaBao`, `codex-rs/hepta-bao-adapter`.
Packages: `HEPTABAO-1-SECRET-BOUNDARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`request_secret_lease(secret_reference, capability, operation_id) -> SecretLeaseMetadata`; `renew(lease_id, grant) -> LeaseMetadata`; `revoke(lease_id, grant) -> RevocationObservation`. Deliver an authorized secret only through the dedicated consumer channel; ordinary receipts contain references and lease metadata, never raw values. Freeze the external source pin/API version and verify it before enabling an adapter.

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

- **Implemented entrypoints:** `consume_kv_v2` and `binding` in [codex-rs/hepta-bao-adapter/src/https_consumer.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer.rs); `DurableLeaseRegistryV1::{prepare_issue,prepare_renew,prepare_revoke,mark_unknown,reconcile,expire_at}` in [codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs](../../../codex-rs/hepta-bao-adapter/src/lease_lifecycle.rs). Authorized exact-version KV v2 HTTPS read plus durable metadata-only lease lifecycle/reconciliation are source implemented.
- **State and recovery:** BaoReadRequest binds one mount/path/version/string field, expected digest and consumer identity. The client owns no secret database. `DurableLeaseRegistryV1` persists lease metadata and operation state with atomic file replacement; reused operation IDs with changed semantics conflict, provider timeout/crash is represented as `Unknown`, and only a matching provider observation may complete renew/revoke. Kernel final-use replay uses an append-only fixed-width claim journal and durable revocation snapshot.
- **Source tests:** [codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs), [codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs](../../../codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs), [codex-rs/hepta-bao-adapter/qa/real_service_smoke.py](../../../codex-rs/hepta-bao-adapter/qa/real_service_smoke.py). These are test identities, not execution receipts for this documentation revision.
- **Implementation and operating references:** [codex-rs/hepta-bao-adapter/README.md](../../../codex-rs/hepta-bao-adapter/README.md).
- **Remaining work:** provider-native `request_secret_lease`, `renew` and `revoke` network dispatch are not enabled yet. The repository compatibility matrix still marks `leases_dynamic_secrets` as blocking `partial`; the adapter therefore stops at durable prepared/unknown/reconciled lifecycle ownership rather than fabricating an unqualified provider API. The external HeptaBao service owns its wider capabilities and must be assessed at its exact source pin. Bind the real registered host consumer; the callback and trust configuration are trusted host inputs. Existing recorded tests are tied to their recorded candidates, not this documentation revision.

## 9. Current schema-3 convergence contract

The [current lease-owner contract](../../../docs/modules/secrets.heptabao/LEASE_OWNER_V3.md)
defines the actual storage protocol and source-composed registered AuthBus path.
`BaoFinalUseHost::consume_kv_v2_with_authbus` binds the host callback, approval,
quota and durable consumption history. `reconcile_consumption` queries the original
registered observer and reservation without provider redispatch. Product-process
activation and provider-native dynamic lease qualification remain separate gaps.
