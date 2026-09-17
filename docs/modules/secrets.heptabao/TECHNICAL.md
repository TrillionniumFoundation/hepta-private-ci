# secrets.heptabao technical development guide

**Plan:** `HEPTA-GLOBAL-MODULAR-DEVELOPMENT-PLAN` v8.0.0

**Module:** `secrets.heptabao`

**Owner:** `secrets-platform`

**Deputy:** `security-authority`

**Lifecycle:** `existing`

**Source status:** `existing_bound`

**Bootstrap work package:** `HEPTABAO-1-SECRET-BOUNDARY`

> **Current-source status.** Exact KV v2 consumption and the native dynamic
> SecretLease issue/renew/revoke/reconciliation state machine are implemented in
> source. This is **not** a production-activation claim. Product composition,
> target-host qualification, independent acceptance, promotion and release are
> still separate gates. For exact current symbols, persistence formats, failure
> semantics and capability ceilings, read
> [`CURRENT_IMPLEMENTATION.md`](CURRENT_IMPLEMENTATION.md). Where a mature target
> described below is broader than current source, that current-implementation
> document controls source-status claims.

This stable document is the implementation guide for `secrets.heptabao`.
Normative identity, ownership, contract, data-authority and delivery facts remain
in the canonical JSON registries. Documentation readiness is not source
implementation, activation, operator acceptance, promotion or release.

## 1. Identity, mission and ownership

Bridge governed secret leases and metadata to the external HeptaBao authority
without returning raw secrets in ordinary receipts.

The primary owner `secrets-platform` controls changes inside the declared target
roots and is accountable for correctness, backward compatibility, test evidence
and rollback. The deputy `security-authority` independently reviews public
contracts, authority checks, persistence, migrations, concurrency, resource
limits and activation behavior. Cross-owner changes require an explicit co-owner
or a separately reviewable integration change; this module must not create a
second authority spine.

Plane `external_control`, kind `service`, state model `stateful_external` and
architecture role `authoritative_store` define placement. External HeptaBao
remains authoritative for provider secret values and provider lease truth; this
module owns only its registered local secret metadata/lease control records.

## 2. Source binding and implementation status

Declared exclusive target roots:

- `external/HeptaBao`
- `codex-rs/hepta-bao-adapter`

Existing declared roots at this exact source snapshot:

- `external/HeptaBao`
- `codex-rs/hepta-bao-adapter`

Shared consumed implementation:

- `codex-rs/hepta-contracts/src/final_use.rs`
- `codex-rs/hepta-contracts/src/final_use_store.rs`

Declared roots not yet present: none.

`existing_bound` is a source-location fact. Exact-candidate execution receipts,
not this label, establish whether the retained source passed tests. This status
does not establish runtime composition, operator acceptance, selection,
promotion or release.

### Native source and scope

The exact KV path is implemented in
[`codex-rs/hepta-bao-adapter/src/https_consumer.rs`](../../../codex-rs/hepta-bao-adapter/src/https_consumer.rs)
with `BaoToken`, `BaoReadRequest`, `BaoSecretReceipt`, `BaoClient`, `binding` and
`consume_kv_v2`.

The dynamic SecretLease lifecycle is implemented in
[`codex-rs/hepta-bao-adapter/src/lease.rs`](../../../codex-rs/hepta-bao-adapter/src/lease.rs)
with `BaoLeaseManager`, `request_secret_lease`, `renew_secret_lease`,
`revoke_secret_lease`, `reconcile_secret_lease` and
`reconcile_indeterminate_issue`. Durable local metadata is implemented by
[`lease_store.rs`](../../../codex-rs/hepta-bao-adapter/src/lease_store.rs).

Shared kernel final-use replay/revocation persistence remains owned by
`kernel.authority`; this module consumes it. The current implementation and
remaining capability ceilings are enumerated in
[`CURRENT_IMPLEMENTATION.md`](CURRENT_IMPLEMENTATION.md) and the
[module execution dossier](../../../qualification/module-execution-dossiers/detail/secrets.heptabao.md).

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

The module accepts only bounded, versioned inputs. Missing authority, stale or
revoked grants, scope mismatch and malformed provider output are hard failures.
Dynamic secret values are not durable local facts and never become learning,
prompt, general log or ordinary receipt fields.

The module must not become a general HeptaBao control API. Dynamic issuance
explicitly rejects reserved `sys`, `auth`, `identity` and `cubbyhole` mounts;
lease lookup/renew/revoke system calls exist only as narrow internal lifecycle
operations.

Non-goals include bypassing the Codex execution spine, interpreting model prose
as authority, minting the authority consumed by the same effect adapter,
claiming local state is a generic distributed multi-writer database, or
converting qualification evidence into deployment authority.

## 4. Internal architecture and component decomposition

The bounded components are:

- typed ingress and operation-specific binding builders;
- kernel final-use admission/replay/revocation dependency;
- pinned direct HTTPS provider adapter;
- durable metadata-only lease lifecycle journal;
- enrolled final-use consumer boundary;
- bounded provider reconciliation path;
- machine-verifiable exact-candidate evidence emitter.

Ingress validates identity, version, size, scope and operation identity before
domain logic. External mutation intent is durably recorded before dispatch.
Provider dispatch occurs at most once per admitted mutation attempt; a timeout or
unknown response is never converted into permission for an automatic retry.

Configuration is immutable for one process generation. Authority, destination,
CA and local state paths are host-enrolled inputs. A replica destination identity
is part of the final-use binding so grants are non-portable across authority
shards.

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

The dynamic native API uses typed Rust request/state/metadata values. The
external lease endpoint semantics follow the reviewed OpenBao-compatible
HeptaBao source pin. Compatibility changes that alter request digest/scope
meaning require a new signing domain/version; the replica-aware KV binding is
therefore versioned independently from the former unsharded binding.

Unknown critical local fields are rejected. Error mapping distinguishes denied,
definite provider rejection, unavailable, timed out, indeterminate,
reconciliation-required and terminal states.

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

External HeptaBao remains authoritative for actual secret values, provider lease
existence, provider TTL and provider renewability. Local lifecycle events bind
source identity, consumer scope, operation identity, provider path, lease ID,
expiry, generation and state; they do not contain provider tokens or raw dynamic
secret fields.

The native lease store is a private local Unix directory with an exclusive lock,
a destination-bound schema record and an append-only fsynced event journal.
Corrupt sequence/digest/destination data fails closed.

Kernel final-use replay persistence uses a separate fixed-width append-only
claim journal. Revocation/trust metadata remains a small atomic snapshot. Legacy
schema-1 nonce snapshots are migrated to the journal on open; migration failure
must not reset replay history.

Rollback preserves unresolved `Indeterminate*` states, current revocations and
replay claims. Missing/corrupt durable state is never interpreted as an empty
registry.

## 7. Runtime, concurrency and transaction model

One local lease state directory and one local final-use authority state directory
have one active process owner each. The OS lock is deliberately not a distributed
lock.

For active-active operation, the implemented composition is authority sharding:
each active replica is enrolled with a distinct destination such as
`provider:heptabao:node-a`, has private replay/lease state, and receives grants
signed for that exact destination. A grant bound to one replica fails binding
validation at another replica.

A deployment that requires concurrent writers sharing one authority identity
still requires a separately qualified strongly consistent shared backend. The
current local implementation makes no active-active multi-writer claim for a
single authority ID.

External mutations follow:

1. validate and bind request;
2. fsync local pending lifecycle state;
3. claim/burn final-use nonce;
4. dispatch exactly one provider request;
5. record confirmed state or an explicit indeterminate state;
6. reconcile unknown outcomes from provider truth where the provider exposes a
   safe lookup.

Dynamic secret callback entry occurs only after confirmed issue metadata is
persisted and after live final-use authority is revalidated.

## 8. Failure semantics, recovery and rollback

The state model includes `IssuePending`, `Active`, `RenewPending`,
`RevokePending`, `IndeterminateIssue`, `IndeterminateRenew`,
`IndeterminateRevoke`, `Orphaned`, `Revoked`, `Expired` and `Rejected`.

Renew/revoke uncertainty is reconciled by provider lease lookup. Provider 404 is
a terminal observation that the lease is no longer live.

Generic OpenBao-compatible issuance does not expose a universal operation-key
lookup for arbitrary dynamic secret plugins. A lost issue acknowledgement is
therefore **not** automatically retried. It remains `IndeterminateIssue` until a
provider-specific recovery mechanism or an externally observed candidate lease
ID is supplied. A verified candidate is adopted as `Orphaned`: the lease can be
managed/revoked, but lost credential bytes are never reconstructed.

A provider effect confirmed externally but not durably recorded locally is
reported as `StatePersistenceIndeterminate`, requiring reconciliation rather
than blind retry.

## 9. Security, privacy and threat controls

Owned threat entries:

- `secret_value_in_receipt`

Posture is least authority, bounded input, exact digest/scope binding,
independent signing, durable replay prevention and final-use revalidation.

`EnrolledSecretConsumer` makes the trusted callback identity explicit for the
dynamic lease API. It is not a sandbox: already trusted in-process code can copy
bytes through side effects. Only audited host consumers may be enrolled; untrusted
plugins need an out-of-process/sandbox boundary.

`BaoSecretReceipt` keeps response/secret SHA-256 values available for local
integrity decisions but excludes them from ordinary serialization and redacts
them in `Debug`, preventing routine evidence/logs from becoming a low-entropy
fingerprint oracle. Exporting a secret-derived digest is a separate security
contract and requires retention/threat analysis; keyed digests are preferred
where stable public correlation is unnecessary.

Application-owned provider tokens, bounded response bodies and decoded secret
strings are zeroized on drop. This is not a claim that plaintext never exists in
RAM: TLS/HTTP/parser/allocator internals, kernel buffers and trusted consumer
code can create transient copies outside adapter ownership.

## 10. Performance, capacity and hot-path policy

Dynamic request metadata is bounded to 16 KiB. Dynamic secret response fields
are bounded by field count/per-field limits and the existing 1 MiB response
ceiling. There is no automatic provider retry loop.

Final-use claims append one fixed 40-byte `(epoch, nonce)` record plus
`sync_data`, rather than serializing the complete nonce set. The former 16,384
claim/epoch semantic capacity stop and O(N) full-JSON rewrite are removed from
the steady-state path. A bounded journal-size guard remains a resource ceiling
and fails closed on exhaustion/corruption.

Performance measurements remain target-host evidence, not inferred guarantees.

## 11. Observability and operations

Use host-enrolled `BaoClient`/`BaoLeaseManager` instances. Configure endpoint,
CA, provider token, authority trust, destination identity and private persistent
state through protected host configuration.

Safe observability contains operation IDs, destination, lifecycle state,
provider path metadata, generation and timing/error class. Raw secret fields,
provider tokens and stable secret-derived fingerprints are excluded from
ordinary logs/receipts.

Operators must surface `IndeterminateIssue`, `IndeterminateRenew`,
`IndeterminateRevoke`, `Orphaned`, state-storage failures and replay-store
resource pressure as explicit reconciliation alerts. They must not respond by
deleting the state directory or reissuing the same effect blindly.

Current operating references:

- [`CURRENT_IMPLEMENTATION.md`](CURRENT_IMPLEMENTATION.md)
- [adapter README](../../../codex-rs/hepta-bao-adapter/README.md)
- [final-use authority guide](../../../codex-rs/hepta-contracts/FINAL_USE.md)
- [external HeptaBao source pin](../../../external/HeptaBao/README.md)

## 12. Verification and qualification

Focused test sources include:

- [`https_consumer_tests.rs`](../../../codex-rs/hepta-bao-adapter/src/https_consumer_tests.rs)
- [`lease_tests.rs`](../../../codex-rs/hepta-bao-adapter/src/lease_tests.rs)
- [`final_use_tests.rs`](../../../codex-rs/hepta-contracts/src/final_use_tests.rs)
- [`real_service_smoke.py`](../../../codex-rs/hepta-bao-adapter/qa/real_service_smoke.py)

The source-candidate gate is
[`.github/workflows/heptabao-lease-qualification.yml`](../../../.github/workflows/heptabao-lease-qualification.yml).
It binds the checked-out SHA, runs package format/tests/strict Clippy and emits a
machine-verifiable receipt through
[`emit_verification_receipt.py`](../../../codex-rs/hepta-bao-adapter/qa/emit_verification_receipt.py).
The receipt binds source/tested SHA, tree, external HeptaBao pin and SHA-256 of
the executed command records. It contains no secret material and explicitly
does not claim production activation or release.

In `codex-rs`, focused local invocation remains:

```text
just test --locked -p codex-hepta-contracts -p codex-hepta-bao-adapter
cargo clippy --locked -p codex-hepta-contracts -p codex-hepta-bao-adapter --all-targets -- -D warnings
```

Commands are not receipts until their exact-candidate outputs are retained.

## 13. Implementation sequence and work packages

Applicable work packages:

- `HEPTABAO-1-SECRET-BOUNDARY`

The bootstrap package is `HEPTABAO-1-SECRET-BOUNDARY`. The native source now
contains the exact KV boundary and dynamic lease lifecycle described above.
Remaining composition/qualification work is not relabeled as missing source API.

Development, activation and evidence predecessor graphs remain distinct.
Contract-first work may run in parallel only with non-overlapping write paths and
frozen semantics. Each change records bounded contracts, domains, denied
authorities, resources, rollback and stop conditions.

## 14. Activation, compatibility and retirement

Activation composes a named product caller through registered ports and verifies
authority, configuration, state-directory ownership, destination sharding,
resource and reconciliation behavior. Shadow and qualification callers are not
production callers.

Compatibility adapters are temporary. Retirement requires all named callers
migrated, no old-path use, oracle parity where required, rehearsed rollback and
independent acceptance. Retirement preserves historical evidence and durable
record interpretability.

## 15. Definition of module completion

Documentation completion requires this guide, the exact current implementation
reference, registry references and closed-world validation. Source completion of
a particular operation requires code plus exact-candidate tests. Composition
requires a named caller. Qualification requires current evidence. Acceptance,
selection, promotion and release are separately governed states.

For `secrets.heptabao`, this document grants no runtime, production, model,
provider, tool, network, filesystem, secret, fleet, acceptance, promotion or
release authority by itself.

### Work-package execution envelopes

#### `HEPTABAO-1-SECRET-BOUNDARY`

- State: `source_implemented_not_product_composed`; priority: `2`; parallel class: `contract_coordinated`.
- Owner/deputy: `secrets-platform` / `security-authority`.
- Primary allowed write paths:
  - `codex-rs/hepta-bao-adapter/**`
- Shared reviewed dependency path for final-use replay hardening:
  - `codex-rs/hepta-contracts/src/final_use.rs`
  - `codex-rs/hepta-contracts/src/final_use_store.rs`
  - `codex-rs/hepta-contracts/src/final_use_tests.rs`
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
  - `exact_candidate_receipt`
- Stop conditions:
  - `authority_violation`
  - `base_drift`
  - `claim_evidence_mismatch`
  - `cross_owner_write_without_review`
  - `unbounded_resource_or_retry`
  - `unreconciled_provider_effect_reported_as_failure`

## 16. V8.2 pre-coding implementation-readiness overlay

The canonical readiness overlay binds `secrets.heptabao` to primary lane
`LANE-A-FOUNDATION`. The following implementation-level specifications remain
mandatory alongside Sections 1–15:

- [`RDY-SRC`](../../readiness/SOURCE_BASELINE_AND_BRANCH_POLICY.md)
- [`RDY-PAR`](../../readiness/PARALLEL_DEVELOPMENT.md)

Owned readiness protocols: none.

Consumed readiness protocols: none.

Ordinary authorized coding identifies the Git baseline, relevant contracts,
owned paths, mandatory fixtures, deterministic fallback and rollback. A runtime
coordinator admitting an envelope still verifies current canonical source,
frozen contract/readiness digest, expiry and zero authority delta. This overlay
does not change activation, acceptance, selection, promotion or release.

## 17. Source implementation receipt

The source-location obligation for `secrets.heptabao` is implemented in:

- `external/HeptaBao`
- `codex-rs/hepta-bao-adapter`

Shared final-use replay hardening is implemented in the consumed
`codex-rs/hepta-contracts` authority boundary rather than copied into the adapter.

The exact-candidate package receipt is generated by
`.github/workflows/heptabao-lease-qualification.yml`. The wider
`.github/workflows/hepta-consolidated-source.yml` continues to provide
repository/lane qualification. These receipts are source evidence only and grant
no production-writer, external-effect, independent-acceptance, selection,
promotion, merge or release authority.
