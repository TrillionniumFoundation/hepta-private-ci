# secrets.heptabao: implementation design

Parent: `docs/modules/secrets.heptabao/TECHNICAL.md`. Lane: `LANE-A-FOUNDATION`.
Status: specified target, not implemented or independently accepted. Common requirements: `../EXECUTION_SEMANTICS.md` and `../TECHNICAL.md`. Canonical ownership and package predecessors are unchanged.

## 1. Source and work envelope

Roots: `external/HeptaBao`, `codex-rs/hepta-bao-adapter`.
Packages: `HEPTABAO-1-SECRET-BOUNDARY`.

Operation signatures below are design contracts, not assertions of existing native symbols. Bind each to an existing or planned symbol and consumer inside the owner envelope. Preserve existing stores and APIs; do not create another authority or execution spine.

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
