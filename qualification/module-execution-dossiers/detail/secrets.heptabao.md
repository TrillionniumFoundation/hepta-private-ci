# secrets.heptabao: implementation design

Parent: `docs/modules/secrets.heptabao/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: authorized exact-version KV v2 HTTPS read plus bounded source-level dynamic secret-lease issuance, renewal, revocation and known-lease lookup are implemented. Durable lease-registry recovery, provider support for reconciling an issuance whose response is lost, product composition and independent acceptance remain in section 8. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `external/HeptaBao`, `codex-rs/hepta-bao-adapter`.
Packages: `HEPTABAO-1-SECRET-BOUNDARY`.

Operation signatures below describe the target contract. Section 8 identifies the implemented native subset and remaining integration; names in section 2 are not automatically native API symbols. Preserve existing stores and APIs; do not create another authority or execution spine.

## 2. Public operations and contract details

`request_secret_lease(request, grant, consumer) -> SecretLeaseIssueOutcome`; `renew_secret_lease(handle, request, grant) -> SecretLeaseMutationOutcome<SecretLeaseRenewal>`; `revoke_secret_lease(handle, request, grant) -> SecretLeaseMutationOutcome<SecretLeaseRevocation>`; `lookup_secret_lease(handle, request, grant) -> SecretLeaseLookupOutcome`. The handle retains the provider lease identifier only inside the trusted host boundary and exposes only a digest publicly. Secret bytes are delivered only through the dedicated consumer callback; receipts contain digests and lease metadata, never the raw value or raw lease identifier. Freeze the external source pin/API version and verify it before enabling an adapter.

## 3. State records and transaction design

The external secret authority remains the source of secret values and leases. Local `secret_metadata` and `secret_lease` records contain external identity, consumer scope, expiry, rotation generation and revocation status only. Any cache is sealed, strictly TTL/generation-bound and excluded from learning/export paths; its protection and erasure are independently tested.

## 4. Deterministic algorithm and scheduling

Validate the independently signed final-use grant; resolve the enrolled external authority; bind provider origin, CA identity, namespace, mount/role or lease identity, consumer and caller-owned operation identity; then call exactly one typed adapter operation. Dynamic issuance cannot bind a secret-value digest before dispatch, so its signed payload digest binds the complete issuance operation. The returned value is digested after the provider response and exposed only inside the final-use callback. Transport failure or response-body timeout after a mutation begins yields `Indeterminate` and never authorizes blind retry. A known lease can be inspected with `lookup_secret_lease` without replaying renew/revoke. Generic issuance whose response is lost cannot be reconstructed from OpenBao lease APIs because no provider lease identity is locally known; automatic reconciliation therefore requires an external HeptaBao/provider idempotency-key plus status-lookup contract. Rotation invalidates dependent caches and cannot silently reuse a revoked generation.

## 5. Capacity and performance profile

Pilot metadata <= 16 KiB, one external operation per request, bounded TTL and renewals from policy. Separate secret-provider latency from metadata cache latency. Fail closed when the external authority or revocation frontier is unavailable.

Pilot ceilings are design targets, not measurements. Stricter canonical limits prevail. Bind actual schema/migration, host and measurements before composition; stateless modules prove absence rather than inventing state.

## 6. Concrete verification cases

- BAO-01: raw secret bytes are absent from logs, receipts, learning rows, exceptions and exports.
- BAO-02: key/lease rotation invalidates the previous generation across process restart.
- BAO-03: lost renew/revoke acknowledgement is quarantined and a known lease is queried without replaying the mutation; lost issuance acknowledgement remains indeterminate unless the provider supplies an operation-key status lookup, and no duplicate unrestricted lease is issued automatically.
- BAO-04: expired/revoked caller scope is rejected before the external API call.

These are required product test designs, not executed-test receipts. Each implementation supplies native test identity, exact input/output and independent oracle evidence.

## 7. Integration, rollback and capability ceiling

Run first against an isolated fake or enrolled non-production authority. Real authority use requires exact provider identity, consent and independent acceptance. Rollback preserves current revocations and cannot restore secret values from an old general-purpose backup.

Use all eighteen dossier receipt fields. Immediate revocation/stop remains effective across frozen snapshots. Preserve every applicable external gate; no generator self-acceptance, self-merge or self-release.

## 8. Current native implementation

- **Implemented entrypoints:** `consume_kv_v2` and `binding` in [codex-rs/hepta-bao-adapter/src/https_consumer.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer.rs); `secret_lease_binding`, `request_secret_lease`, `secret_lease_renew_binding`, `renew_secret_lease`, `secret_lease_revoke_binding`, `revoke_secret_lease`, `secret_lease_lookup_binding` and `lookup_secret_lease` in [codex-rs/hepta-bao-adapter/src/lease.rs](../../../codex-rs/hepta-bao-adapter/src/lease.rs).
- **State and recovery:** KV reads bind one exact version and expected digest. Dynamic lease operations retain the raw provider lease ID only in a non-Debug `SecretLeaseHandle`, publish a lease-ID digest, use zeroizing provider-response buffers, and classify mutation transport ambiguity as `Indeterminate`. A provider-issued lease whose final-use delivery is revoked after the response returns as `DeliveryBlocked` with its opaque handle so a trusted host can revoke/reconcile it rather than orphan it. Known leases have a non-replaying lookup path. There is still no durable local lease registry in this adapter; a process loss can therefore lose a newly observed handle before a host owner persists it.
- **Source tests:** [codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs) covers real loopback TLS for KV and dynamic issuance, including secret-only callback delivery and response-body timeout as indeterminate; [codex-rs/hepta-bao-adapter/src/lease.rs](../../../codex-rs/hepta-bao-adapter/src/lease.rs) contains pure binding/redaction tests; [codex-rs/hepta-bao-adapter/qa/real_service_smoke.py](../../../codex-rs/hepta-bao-adapter/qa/real_service_smoke.py) remains the earlier KV service fixture. These are test identities until exact-candidate CI records execution.
- **Implementation and operating references:** [codex-rs/hepta-bao-adapter/README.md](../../../codex-rs/hepta-bao-adapter/README.md).
- **Remaining work:** bind a durable lease registry/state owner before claiming crash-safe lease lifecycle recovery; add a HeptaBao/provider operation-id idempotency and status-lookup contract before automatically reconciling an issuance whose response was lost; qualify renew/revoke/lookup against the pinned external service; bind the real registered host consumer and current exact-head evidence. The callback and trust configuration remain trusted host inputs. Existing recorded KV tests are tied to their recorded candidates, not this documentation revision.
