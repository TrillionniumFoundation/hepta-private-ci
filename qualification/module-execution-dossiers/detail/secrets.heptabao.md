# secrets.heptabao: implementation design

Parent: `docs/modules/secrets.heptabao/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: exact-version KV v2 read plus source-implemented dynamic SecretLease issue/renew/revoke client are present; paired HeptaBao runtime admission, exact source pinning, product composition and independent acceptance remain separate gates described in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

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

- **Implemented entrypoints:** `consume_kv_v2` and `binding` remain the exact-version static KV path in [codex-rs/hepta-bao-adapter/src/https_consumer.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer.rs). [codex-rs/hepta-bao-adapter/src/lease_client.rs](../../../codex-rs/hepta-bao-adapter/src/lease_client.rs) additionally implements `lease_issue_binding`, `request_secret_lease`, `lease_renew_binding`, `renew_secret_lease`, `lease_revoke_binding`, `revoke_secret_lease`, `lookup_secret_lease` and `pending_secret_lease_operation`.
- **Dynamic provider owner:** the adapter is paired with `TrillionniumFoundation/HeptaBao#110`, which wires the pre-existing `DurableDynamicSecretBroker` into the runnable server. The provider owns lease identity/state and persists a mutation intent before plugin entry. Issue, renew and revoke are fenced across restart; post-entry uncertainty creates a durable pending invocation and requires explicit reconciliation rather than redispatch.
- **Authority binding:** every mutation grant binds subject, consumer, namespace, HTTPS origin, CA identity, operation/resource and the SHA-256 of the exact serialized provider mutation body. For issuance the generated secret does not exist pre-dispatch, so the authority payload digest binds the issuance request rather than a future credential digest. The observed generated-secret digest is receipt metadata only.
- **Secret delivery:** issuance decodes the provider credential into an application-owned zeroizing buffer and releases it only to the synchronous trusted consumer inside the final-use revocation fence. Ordinary issue/renew/revoke receipts contain digests and lease metadata, never raw generated bytes. Lower TLS/HTTP/parser layers may still create temporary plaintext copies; this is not locked-memory secrecy.
- **Ambiguous outcomes:** mutations have no automatic retry. Transport loss, malformed/oversized success responses and post-dispatch authority loss remain unknown. HeptaBao exposes repeatable local lease lookup plus the one pending durable invocation; clearing the provider fence is root-only and must be based on authoritative provider readback. A provider failure proven before plugin entry is represented separately but still is not retried by the adapter.
- **HA boundary:** the paired provider runtime uses a local durable single-writer state directory. Dynamic-secret configuration together with HeptaBao HA is rejected fail-closed until a shared strongly consistent lease/replay backend is supplied. This change does not claim active-active support.
- **State and recovery:** the existing KV reader still owns no lease state. Dynamic lease state remains provider-authoritative; private-ci holds only final-use replay/revocation state and transient secret buffers. A restart that finds an unresolved provider invocation reopens fenced and requires reconciliation before another provider mutation.
- **Source tests:** [codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs), unit/focused cases in [codex-rs/hepta-bao-adapter/src/lease_client.rs](../../../codex-rs/hepta-bao-adapter/src/lease_client.rs), and [codex-rs/hepta-bao-adapter/qa/real_service_smoke.py](../../../codex-rs/hepta-bao-adapter/qa/real_service_smoke.py). These are source/test identities; exact-head execution receipts are separate.
- **Implementation and operating references:** [codex-rs/hepta-bao-adapter/README.md](../../../codex-rs/hepta-bao-adapter/README.md) and the paired HeptaBao PR/runtime source.
- **Remaining work / non-claims:** the older external source binding in [external/HeptaBao/README.md](../../../external/HeptaBao/README.md) still points to the previously qualified KV candidate and does **not** activate this new lifecycle. The paired HeptaBao change must pass its repository gates and receive an exact accepted source pin before dynamic lease activation. A real registered host consumer, provider-specific reconciliation operator/readback, product execution, target-host qualification and independent acceptance remain required. Existing recorded evidence is tied to its recorded candidate and is not silently promoted to this branch.
