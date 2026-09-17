# secrets.heptabao: implementation design

Parent: `docs/modules/secrets.heptabao/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: authorized exact-version KV v2 HTTPS read consumer plus provider-native SecretLease issuance, renew, synchronous revoke and reconciliation implemented in the adapter; independent production acceptance and distributed/HA state remain separate. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `external/HeptaBao`, `codex-rs/hepta-bao-adapter`.
Packages: `HEPTABAO-1-SECRET-BOUNDARY`.

Operation signatures below describe the target contract and current adapter implementation. Section 8 identifies the native entrypoints and remaining integration/production work. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`request_secret_lease(secret_reference, capability, operation_id) -> SecretLeaseMetadata`; `renew(lease_id, grant) -> LeaseMetadata`; `revoke(lease_id, grant) -> RevocationObservation`. The current Rust adapter realizes these semantics as `BaoClient::request_secret_lease`, `BaoClient::renew_secret_lease`, `BaoClient::revoke_secret_lease`, provider lookup reconciliation through `BaoClient::reconcile_secret_lease`, and independently authorized lost-ack resolution through `BaoClient::resolve_unknown_secret_issue`.

Deliver an authorized secret only through the dedicated consumer channel; ordinary receipts and registry records contain references and lease metadata, never raw values. Freeze the external source pin/API version and verify it before enabling an adapter.

## 3. State records and transaction design

The external secret authority remains the source of secret values and external leases. Local `secret_metadata` and `secret_lease` records contain external identity, consumer scope, expiry, rotation generation and revocation/reconciliation status only. The executable pilot registry is `SecretLeaseRegistry`: it stores no raw dynamic value and no provider token, and it deliberately avoids a long-lived unkeyed digest of dynamic values.

Before a provider operation that can create, renew or revoke a lease is dispatched, the operation ID and `OutcomeUnknown` admission record are durably persisted. A repeated operation ID with different semantics conflicts. An indeterminate mutating operation is not automatically retried. Any cache remains sealed, strictly TTL/generation-bound and excluded from learning/export paths; its protection and erasure are independently tested.

## 4. Deterministic algorithm and scheduling

Validate host-authenticated grant and quota; resolve the enrolled external authority; bind final request and operation; persist the operation uncertainty fence; call the typed adapter; observe external lease identity and expiry; then persist the terminal observation before reporting success.

For secret-bearing issuance, live authority is checked again at the final synchronous callback boundary. Lost acknowledgement yields indeterminate. If a renew/revoke lease identity is known, reconcile through provider lease lookup instead of repeating the mutation. If issuance acknowledgement is lost before the new lease ID is observed, independent provider/audit inspection must resolve the operation. An independently discovered orphan lease is adopted only as `RevokeRequired`, never as a usable active credential, because its generated secret material was not durably delivered through the authorized consumer boundary. Rotation invalidates dependent caches and cannot silently reuse a revoked generation.

## 5. Capacity and performance profile

Pilot metadata <= 16 KiB per contract input, one external operation per request, bounded TTL and renewals from policy. Separate secret-provider latency from metadata/registry latency. Fail closed when the external authority, local registry or revocation frontier is unavailable.

The current local registry has explicit implementation bounds: 4,096 lease records, 8,192 operation records and 8 MiB serialized state. It uses a process lock and atomic local snapshot replacement and is therefore a single-active pilot backend, not an active-active distributed lease/replay authority. These are implementation limits rather than claims of production HA.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- BAO-01: raw secret bytes are absent from logs, receipts, registry state, learning rows, exceptions and exports.
- BAO-02: key/lease rotation invalidates the previous generation across process restart.
- BAO-03: lost acknowledgement is durably fenced and reconciled without issuing a duplicate unrestricted lease.
- BAO-04: expired/revoked caller scope is rejected before the external API call or before final secret delivery when revocation occurs during provider latency.
- BAO-05: renew timeout cannot cause automatic renew retry; provider lookup resolves known-lease ambiguity.
- BAO-06: independently observed orphan issuance is locally `RevokeRequired`, never `Active`.

The native lifecycle test file supplies concrete source fixtures for these semantics. Exact-candidate CI/test execution remains the receipt for a particular source SHA.

## 7. Integration, rollback and capability ceiling

Run first against an isolated fake or enrolled non-production authority. Real authority use requires exact provider identity, consent and independent acceptance. Rollback preserves current revocations, unresolved operation tombstones and lease generations and cannot restore secret values from an old general-purpose backup.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Exact-version KV entrypoints:** `consume_kv_v2` and `binding` in [codex-rs/hepta-bao-adapter/src/https_consumer.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer.rs).
- **SecretLease entrypoints:** `request_secret_lease`, `renew_secret_lease`, `revoke_secret_lease`, `reconcile_secret_lease`, `resolve_unknown_secret_issue` and their deterministic binding helpers in [codex-rs/hepta-bao-adapter/src/lease_client.rs](../../../codex-rs/hepta-bao-adapter/src/lease_client.rs).
- **Durable local lifecycle state:** [codex-rs/hepta-bao-adapter/src/lease_registry.rs](../../../codex-rs/hepta-bao-adapter/src/lease_registry.rs) persists lease metadata plus operation admission/reconciliation state. It does not store provider tokens or raw dynamic secret values. Mutation uncertainty is recorded before network dispatch.
- **Dynamic-secret exposure:** [codex-rs/hepta-bao-adapter/src/lease_types.rs](../../../codex-rs/hepta-bao-adapter/src/lease_types.rs) defines non-serializable `DynamicSecretValues`; only explicitly requested string fields enter the trusted callback.
- **Provider lifecycle:** dynamic issuance uses the registered `{mount}/{path}` read endpoint; renewal uses `/v1/sys/leases/renew`; synchronous revoke uses `/v1/sys/leases/revoke`; known-lease reconciliation uses `/v1/sys/leases/lookup`.
- **Ambiguous outcomes:** issuance with a lost acknowledgement and no locally known lease ID stays `OutcomeUnknown` and blocks replay. Independent resolution either proves no lease was created or adopts a discovered orphan as `RevokeRequired`. Renew/revoke ambiguity is resolved by lookup rather than repeating the mutation.
- **Source tests:** [codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs), [codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs](../../../codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs), and the existing KV real-service fixture [codex-rs/hepta-bao-adapter/qa/real_service_smoke.py](../../../codex-rs/hepta-bao-adapter/qa/real_service_smoke.py). Source test identity is not execution evidence for a new candidate until CI/receipts bind the exact SHA.
- **Implementation and operating references:** [codex-rs/hepta-bao-adapter/README.md](../../../codex-rs/hepta-bao-adapter/README.md) and [codex-rs/hepta-bao-adapter/SECRET_LEASES.md](../../../codex-rs/hepta-bao-adapter/SECRET_LEASES.md).
- **Remaining product/production work:** bind a named production caller and dynamic-engine real-service qualification; choose/implement a distributed or explicitly single-active production registry architecture; close the separate final-use nonce capacity/O(N) snapshot concerns; retain independent acceptance/promotion/release gates. These remaining items do not make `request_secret_lease`, renew, revoke or the ambiguity state machine target-only APIs anymore.
