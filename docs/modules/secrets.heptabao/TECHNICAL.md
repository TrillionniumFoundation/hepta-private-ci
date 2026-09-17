# secrets.heptabao technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `secrets.heptabao`

**Owner:** `secrets-platform`

**Deputy:** `security-authority`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `HEPTABAO-1-SECRET-BOUNDARY`

This stable document is the implementation guide for `secrets.heptabao`. Normative identity, ownership, contract, data-authority and delivery facts remain in the canonical JSON registries. This guide explains how those facts are implemented and operated. Documentation readiness is not source implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Bridge governed secret leases and metadata to the external HeptaBao authority without returning raw secrets in receipts.

The primary owner `secrets-platform` controls changes inside the declared target roots and is accountable for correctness, backward compatibility, test evidence and rollback. The deputy `security-authority` independently reviews public contracts, authority checks, persistence, migrations, concurrency, resource limits and activation behavior. A work package may narrow this scope but may not widen it. Cross-owner changes require an explicit co-owner or a separate integration package.

Plane `external_control`, kind `service`, state model `stateful_external` and architecture role `authoritative_store` define placement. The module may optimize locally, but cannot claim global optimality or absorb another module's durable facts.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `external/HeptaBao`
- `codex-rs/hepta-bao-adapter`

Existing declared roots at this exact source snapshot:

- `external/HeptaBao`
- `codex-rs/hepta-bao-adapter`

Non-authoritative implementation evidence roots:

None.

Declared roots not yet present:

None.

`existing_bound` is a source-location fact: the declared roots exist. The source and test references below identify what can be inspected and invoked; only exact-candidate execution receipts establish that the checks passed. This status does not establish runtime composition, operator acceptance, selection, promotion or release. Any source move updates `MODULES.json`, `SOURCE_BINDINGS.json` and this guide together.

### Native source and scope

The original exact-version KV source remains [codex-rs/hepta-bao-adapter/src/https_consumer.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer.rs), including `BaoToken`, `BaoReadRequest`, `BaoSecretReceipt`, `BaoClient`, `binding` and `consume_kv_v2`.

The SecretLease lifecycle implementation is split across:

- [codex-rs/hepta-bao-adapter/src/lease_client.rs](../../../codex-rs/hepta-bao-adapter/src/lease_client.rs): `request_secret_lease`, `renew_secret_lease`, `revoke_secret_lease`, `reconcile_secret_lease`, `resolve_unknown_secret_issue` and deterministic binding helpers;
- [codex-rs/hepta-bao-adapter/src/lease_registry.rs](../../../codex-rs/hepta-bao-adapter/src/lease_registry.rs): durable operation/lease metadata and uncertainty fencing;
- [codex-rs/hepta-bao-adapter/src/lease_types.rs](../../../codex-rs/hepta-bao-adapter/src/lease_types.rs): public lifecycle request/state types and non-serializable dynamic secret callback values;
- [codex-rs/hepta-bao-adapter/SECRET_LEASES.md](../../../codex-rs/hepta-bao-adapter/SECRET_LEASES.md): executable state-machine, failure and recovery contract.

These are source navigation bindings, not proof that a candidate passed validation or that production composition/acceptance exists. Read the [current native implementation](../../../qualification/module-execution-dossiers/detail/secrets.heptabao.md#8-current-native-implementation) alongside the implementation design for exact candidate status and remaining production work.

## 3. Boundary, responsibilities and non-goals

Direct dependencies:

- `kernel.authority`
- `auth.authbus`

Authoritative write domains:

- `secret_metadata`
- `secret_lease`

Explicitly denied capabilities:

- `raw_secret_receipt`
- `self_issued_operator_acceptance`

The module accepts only registered, bounded, versioned inputs. It rejects unknown critical fields and treats missing authority, stale revisions, scope mismatch and digest mismatch as hard failures. It never directly writes another owner's store. Cross-owner mutation follows local transaction, durable intent, outbox, destination deduplication, acknowledgement and fenced reconciliation.

Dynamic secret values may cross only the dedicated trusted final-consumer callback. They never enter ordinary receipts or lease registry records. The application-owned response and selected secret buffers use zeroizing containers, but TLS/HTTP/parser/allocator internals may create transient plaintext copies; this module does not claim locked-memory secrecy.

Non-goals include becoming a general state store, bypassing the Codex execution spine, interpreting model prose as authority, minting an authority consumed by the same component, converting qualification evidence into deployment authority, or pretending the local pilot registry is a distributed active-active authority. A façade may sequence modules but may not own their facts.

## 4. Internal architecture and component decomposition

The bounded components are:

- typed ingress;
- independent final-use binding/admission;
- provider adapter;
- durable lease/operation registry;
- trusted secret consumer boundary;
- reconciliation path;
- bounded metadata projection.

Ingress validates identity, version, size, scope and operation identity before domain logic. The deterministic core receives typed values and is testable without provider network activity. State-bearing components use one durable mutation boundary per local admission/observation transition.

For provider operations that can create, renew or revoke a lease, the local operation record is durably moved to `OutcomeUnknown` before network dispatch. A terminal provider result then advances the record to a terminal state. Transport uncertainty, timeout, malformed success, or non-definitive provider failure never becomes an implicit retry permission.

Adapters translate one registered contract, verify final payload and grant immediately before the boundary, invoke one downstream capability, and map the observed terminal outcome. Queue acceptance or handler completion is never inferred as external success. Component interfaces support deterministic fixtures and fault injection.

Configuration is immutable for one process generation. Changes affecting authority, schema, compatibility, provider identity or resource policy create a new revision or generation. Hidden mutable singletons, unbounded queues and implicit store fallback are prohibited.

## 5. Contracts, ports and compatibility

Produced contracts:

- `DomainRead::secret_leaseV1`
- `DomainRead::secret_metadataV1`

Consumed contracts:

- `DomainRead::auth_policyV1`
- `DomainRead::authority_leaseV1`
- `DomainRead::capability_revocationV1`
- `DomainRead::quota_registryV1`
- `DomainRead::quota_reservationV1`
- `ModulePort::auth.authbus::secrets.heptabao`
- `ModulePort::kernel.authority::secrets.heptabao`

Critical protocol schemas:

None.

Current Rust lifecycle operations are:

- `request_secret_lease(request, authority, signed_grant, trusted_consumer) -> SecretLeaseMetadata`;
- `renew_secret_lease(request, authority, signed_grant) -> SecretLeaseMetadata`;
- `revoke_secret_lease(request, authority, signed_grant) -> RevocationObservation`;
- `reconcile_secret_lease(request, authority, signed_grant) -> SecretLeaseMetadata`;
- `resolve_unknown_secret_issue(request, authority, signed_grant) -> Option<SecretLeaseMetadata>`.

Each has a deterministic binding helper so the independent issuer can review the exact operation. Existing KV `consume_kv_v2` and legacy metadata-only `resolve`/`assess_secret_boundary_v1` remain compatibility surfaces and are not silently widened.

Every producer validates output before publication and binds semantic fields into the declared digest scope. Every consumer validates version, bounds, producer identity, scope and digest before use. Compatibility is additive only where registered; unknown critical fields are rejected. Contract identifiers, meaning and authority interpretation cannot change in place.

## 6. Data authority, persistence and migrations

Owned authoritative or rebuildable domains:

- `secret_lease`
- `secret_metadata`

Read-only data dependencies:

- `auth_policy`
- `authority_lease`
- `capability_revocation`
- `quota_registry`
- `quota_reservation`

The external HeptaBao/OpenBao authority remains authoritative for actual dynamic secret values and provider lease existence. The local `SecretLeaseRegistry` is authoritative for Hepta's operation-admission history, consumer/scope binding, locally observed provider lease metadata, reconciliation state and generation.

The local registry stores no provider token, no raw dynamic secret value and no long-lived unkeyed fingerprint of a dynamic secret value. Current files are `lease-registry.lock`, `lease-registry.json` and `lease-registry.next`. The pilot Unix backend uses an owner-private directory/file mode, one process lock, file sync, atomic replacement and directory sync; corruption or persistence failure fails closed rather than reinitializing history.

Mutations are operation-ID bound and idempotent only for identical recorded semantics. Reusing an identity with different semantics conflicts. Rotation/reconciliation advances `rotation_generation`; terminal provider absence/revocation cannot be rolled back into an earlier locally active generation by ordinary API use.

Migrations remain deterministic and checksum-bound. Store open verifies schema and bounded state before reads or writes. Rollback across a schema boundary must preserve unresolved operation tombstones and compatible lease-generation state.

## 7. Runtime, concurrency and transaction model

`SecretLeaseRegistry` is the current lifecycle state owner. Before a mutating provider request is sent, it persists the exact operation as `OutcomeUnknown` and, for known leases, transitions the lease to `RenewOutcomeUnknown` or `RevokeOutcomeUnknown`. Persistence success is a precondition for dispatch.

Dynamic issuance then performs one provider read, validates returned lease metadata and exact requested string fields, persists the observed lease metadata, and only then enters `FinalUseAuthority::with_verified_use` for secret delivery. A final-use revocation or consumer-indeterminate result fences the observed provider lease as `RevokeRequired`.

Known-lease renew/revoke uncertainty is reconciled through `/sys/leases/lookup`, not by repeating the mutation. Issuance uncertainty without a locally observed provider lease ID requires independent provider/audit reconciliation. An independently discovered orphan is recorded only as `RevokeRequired` because its generated values were not durably delivered through the authorized callback.

The pilot registry lock is single-active. It does not provide active-active or NFS/distributed consistency. Shared concurrency and transaction requirements remain mandatory at any production state-owner replacement boundary.

## 8. Failure semantics, recovery and rollback

The lifecycle distinguishes rejected, unavailable, timed out, indeterminate, reconciliation-required and terminal outcomes.

- definitive pre-effect validation/authority rejection: no provider call;
- definitive provider client rejection: operation becomes terminal `Rejected`; known-lease local in-flight state is restored;
- timeout/transport loss/non-definitive server outcome after mutation admission: operation remains `OutcomeUnknown`; no automatic retry;
- renew/revoke unknown: use a fresh independently signed lookup reconciliation operation;
- issuance unknown without lease ID: require independent provider/audit inspection, then submit a signed `UnknownIssueResolutionRequest`;
- independently discovered orphan issuance: adopt only as `RevokeRequired`, then revoke under a new signed operation;
- provider lookup/revoke proving absence: `ProviderAbsent` terminal state;
- callback failure after secret delivery entry: `ConsumerIndeterminate`, treat effect as uncertain and fence the lease for revocation.

Rollback preserves revocation, `ProviderAbsent`, generations and unresolved operation records. Missing/corrupt state may not be repaired by silently creating an empty registry.

## 9. Security, privacy and threat controls

Owned threat entries:

- `secret_value_in_receipt`

The posture is least authority, bounded input, typed contracts, digest binding, independent issuer and evidence. Credentials never enter general logs, learning datasets, prompt factors, registry state or cross-module receipts. Dynamic secret values are selected by an explicit field allowlist and are non-serializable callback-only objects whose `Debug` output is redacted.

Authority is operation-bound, final-payload-bound, short-lived and revocation-aware. Mutating external operations consume a one-time grant before dispatch. Issuance performs a second live authority check at final secret delivery.

Negative tests cover denied capabilities, stale/revoked grants, replay/operation drift, unknown outcomes, duplicate operation IDs, response bounds, scope escape and secret/provider leakage. Security review remains mandatory for new effect boundaries, persistence, network, model invocation or authority semantics.

## 10. Performance, capacity and hot-path policy

Current native HTTP response cap remains 1 MiB. Dynamic lifecycle request bounds include at most 32 selected secret fields, provider lease IDs up to 4096 bytes, bounded operation IDs and a one-year absolute implementation ceiling on requested/provider TTL before stricter local policy is applied.

The pilot registry explicitly caps at 4,096 lease records, 8,192 operation records and 8 MiB serialized state. Each mutation currently performs a complete local snapshot replacement plus sync. These are deliberate fail-closed pilot limits, not a claim of high-throughput production storage. Active-active/distributed lease ownership and replacement of snapshot O(N) persistence remain separate production architecture work.

The existing final-use authority's independent 16,384 nonce-per-epoch bound also remains in force and is not changed by the SecretLease lifecycle implementation.

Shared performance and capacity requirements define the measurement/overload obligations for a selected host.

## 11. Observability and operations

Use the host-enrolled `BaoClient` behind a registered trusted consumer. Exact KV semantics remain documented in [codex-rs/hepta-bao-adapter/README.md](../../../codex-rs/hepta-bao-adapter/README.md); executable dynamic issuance/renew/revoke/reconciliation semantics are documented in [codex-rs/hepta-bao-adapter/SECRET_LEASES.md](../../../codex-rs/hepta-bao-adapter/SECRET_LEASES.md).

Configure CA, provider token, issuer, epoch, final-use state and a separate owner-private lease registry directory through protected host configuration. Do not place secret material, provider token or dynamic values in operation IDs, filenames, logs or receipts.

Operational alerts distinguish provider denial, registry unavailable/corrupt, `OutcomeUnknown`, `RevokeRequired`, lease TTL policy violations and terminal provider absence. An unknown mutation is not an ordinary retryable failure. Operators/reconcilers must resolve it before allowing another mutation of the same logical operation.

Current operating and state-format references:

- [codex-rs/hepta-bao-adapter/README.md](../../../codex-rs/hepta-bao-adapter/README.md);
- [codex-rs/hepta-bao-adapter/SECRET_LEASES.md](../../../codex-rs/hepta-bao-adapter/SECRET_LEASES.md);
- [codex-rs/hepta-contracts/FINAL_USE.md](../../../codex-rs/hepta-contracts/FINAL_USE.md);
- [external/HeptaBao/README.md](../../../external/HeptaBao/README.md).

## 12. Verification and qualification

Current focused source tests (source references, not pass receipts):

- [codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs](../../../codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs): exact KV TLS/final-use behavior;
- [codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs](../../../codex-rs/hepta-bao-adapter/src/lease_lifecycle_tests.rs): dynamic issuance, requested-field-only delivery, persistent no-secret registry, timeout uncertainty fencing, renew/revoke endpoints, lookup reconciliation and orphan lost-ack resolution;
- [codex-rs/hepta-bao-adapter/src/lib_tests.rs](../../../codex-rs/hepta-bao-adapter/src/lib_tests.rs): legacy metadata-only boundary.

In `codex-rs`, run `just test -p codex-hepta-bao-adapter -p codex-hepta-contracts`, plus package all-target compile/Clippy and repository document/integrity gates. The command list is not a stored result. Only exact-candidate CI/evidence establishes passes, failures and skips.

The existing real-service fixture is KV-focused. Production dynamic-secret composition requires a current real-service dynamic-engine qualification fixture/receipt; source lifecycle tests must not be reported as that independent provider acceptance.

## 13. Implementation sequence and work packages

Applicable work packages:

- `HEPTABAO-1-SECRET-BOUNDARY`

The canonical bootstrap package remains `HEPTABAO-1-SECRET-BOUNDARY`. Its registry lifecycle label does not by itself mean the current source lacks the implemented lifecycle entrypoints. Development, activation and evidence predecessor graphs are distinct and all are enforced.

Current source candidate work closes the previously target-only provider-native operations and ambiguous-outcome state machine while preserving the exact KV and legacy metadata APIs. Remaining production packages may still cover named caller composition, dynamic-engine real-service qualification, distributed/HA state ownership, final-use replay-store scaling and release evidence.

Each PR records its bounded contracts, domains, denied authorities, resources, rollback and stop conditions. A coordinator-issued envelope is required only at the coordination boundary that consumes it; it is not additional permission for ordinary authorized repository work.

Source implementation completes only when the declared target root exists, public surfaces match registries, tests pass and exact-head plus merge-candidate evidence is current. Later planned production/activation packages may remain without converting implemented source APIs back into target-only prose.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies authority, configuration, resource and failure behavior. Shadow and qualification callers are not production callers. Source-complete modules remain inactive until activation predecessors and evidence gates pass.

Compatibility adapters are temporary. Retirement requires all named callers migrated, no old-path use, oracle parity where required, rehearsed rollback and independent acceptance. Retirement preserves historical evidence and durable-record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, exact registry references and closed-world validation. Source completion requires code in the declared root and candidate tests. Composition requires a named caller. Qualification requires current exact-candidate evidence. Acceptance, selection, promotion and release are separate externally governed states.

For `secrets.heptabao`, this document grants no runtime, production, model, provider, tool, network, filesystem, secret, Matrix, fleet, acceptance, promotion or release authority.

### Work-package execution envelopes

#### `HEPTABAO-1-SECRET-BOUNDARY`

- State: `planned` in the canonical work-package registry; this label is not an assertion that every source entrypoint described above is absent.
- Priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `secrets-platform` / `security-authority`.
- Allowed write paths:
  - `codex-rs/hepta-bao-adapter/**`
- Development predecessors:
  - `AUTHBUS-P1.3-V12`
  - `P0.7B-B3-BOUNDARIES`
- Activation predecessors:
  - `AUTHBUS-P1.3-V12`
  - `P0.7B-B3-BOUNDARIES`
- Required deliverables:
  - `exact_source_identity`
  - `static_verification`
  - `focused_tests`
  - `clean_worktree`
- Stop conditions:
  - `authority_violation`
  - `base_drift`
  - `claim_evidence_mismatch`
  - `cross_owner_write`
  - `unbounded_resource_or_retry`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `secrets.heptabao` to primary lane `LANE-A-FOUNDATION`. The following implementation-level specifications are mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)

Owned readiness protocols:

- None.

Consumed readiness protocols:

- None.

Ordinary authorized coding identifies the Git baseline, relevant contracts, owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime coordinator admitting an envelope still verifies its current `CanonicalSourceReceiptV1`, frozen contract/readiness digest, expiry and zero authority delta; manually issuing an envelope is not a separate permission gate for ordinary repository work. This overlay does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The source-location obligation for `secrets.heptabao` remains bound to:

- `external/HeptaBao`;
- `codex-rs/hepta-bao-adapter`.

The current SecretLease source candidate adds executable lifecycle code, focused source tests and implementation documentation under the registered adapter root. Exact-head source qualification is established only by the CI/receipt for the candidate SHA; this paragraph must not be interpreted as self-acceptance or an all-green claim before those checks complete.

Repository workflows including `.github/workflows/hepta-consolidated-source.yml`, Lane A qualification, OpenBao compatibility, development-doc and repository-integrity gates remain the evidence path. A passing source candidate still grants no runtime composition, production-writer authority, independent acceptance, selection, promotion, merge or release authority.
