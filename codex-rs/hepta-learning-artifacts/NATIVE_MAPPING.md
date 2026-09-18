# `learning.artifacts` native implementation mapping

This file maps immutable artifact storage, lineage, withdrawal and lifecycle
design to concrete Rust symbols. Candidate storage and evaluation eligibility
are not selection, activation, promotion or release.

## Compatibility and state ownership

The existing V1 `ArtifactRegistry`, create-only payload files, registry
snapshots and pinned loader remain unchanged. The additive V2 layer makes
provenance and control evidence explicit without reinterpreting historical V1
manifests.

Owned logical domains are:

- immutable candidate bytes and byte identity;
- append-only artifact registry and lineage;
- persistent dataset-withdrawal facts;
- registry-head witness validation;
- artifact lifecycle evidence.

The source modules do not own a signing key, selection route, production process
or filesystem namespace. Read-only orphan/admin inspection emits no mutation or
selection authority and cannot establish freshness of the supplied state. Those
capabilities remain host-owned.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| register/quarantine/revoke V1 candidate | `ArtifactRegistry::append` | `src/registry.rs` | retained |
| create immutable payload/snapshot | `CreateOnlyArtifactFile`, `write_candidate_payload`, `write_registry_snapshot` | `src/storage.rs` | retained |
| distribute and reload current head witness | `write_registry_head_witness`, `read_registry_head_witness` | `src/storage.rs` | implemented |
| read exact pinned candidate | `load_pinned_candidate` | `src/pinned.rs` | retained |
| prepare snapshot-local dataset revocation | `prepare_dataset_revocation` | `src/dataset_revocation.rs` | retained |
| validate complete V2 manifest | `validate_artifact_manifest_v2` | `src/closure_v2.rs` | implemented |
| persist dataset withdrawal frontier | `DatasetWithdrawalRegistry::append` | `src/closure_v2.rs` | implemented |
| deny future admission from withdrawn dataset | `DatasetWithdrawalRegistry::admit_manifest` | `src/closure_v2.rs` | implemented |
| validate latest-head/anti-rollback evidence | `validate_registry_head_witness` | `src/closure_v2.rs` | implemented |
| validate lifecycle transition | `validate_artifact_lifecycle_transition` | `src/closure_v2.rs` | implemented |
| bind withdrawal registry identity/scope | `WithdrawalRegistryBindingV1`, `DatasetWithdrawalRegistry::new_scoped` | `src/closure_v2.rs` | implemented |
| bind V3 admission to scoped withdrawal head | `admit_manifest_at_withdrawal_head_v3`, `validate_artifact_publication_v3` | `src/admission_v3.rs` | implemented |
| stage and revalidate V3 -> durable V1 publication | `prepare_artifact_publication_v3`, `revalidate_artifact_publication_v3` | `src/publication.rs` | implemented |
| persist/reopen withdrawal registry | `write_withdrawal_registry_snapshot`, `read_withdrawal_registry_snapshot` | `src/aux_storage.rs` | implemented |
| persist/reopen lifecycle journal | `write_lifecycle_journal_snapshot`, `read_lifecycle_journal_snapshot` | `src/aux_storage.rs` | implemented |
| record governed iteration transitions | `validate_iteration_transition`, `IterationLedgerV1::transition` | `src/iteration.rs`, `src/iteration_ledger.rs` | implemented |
| inspect suspected orphan without deletion authority | `inspect_orphan_candidate` | `src/storage.rs` | implemented |
| summarize supplied registry/withdrawal/lifecycle state | `inspect_artifact_admin_state` | `src/admin.rs` | implemented, DENY_ALL |

`LearningArtifactManifestV2` explicitly binds:

- every source dataset digest;
- additional lineage evidence digests;
- multiple predecessor IDs and an optional rollback predecessor;
- payload digest and exact byte count;
- training code, runtime tuple and device profile;
- objective class, schema, normalization and compatibility profiles;
- producer identity, creation time and expiry.

Dataset-derived and dataset-independent artifacts are different provenance
modes. A dataset-derived manifest without a source dataset, or a
dataset-independent manifest containing one, fails.

`DatasetWithdrawalRegistry` is append-only, digest-chained and replayable from a
snapshot. V3 publication requires a `WithdrawalRegistryBindingV1` so an equal
head digest from another registry or tenant scope cannot satisfy the admission.
`HEPTAW01` create-only snapshots persist the binding plus exact withdrawal
history and replay semantics. Exact notice retries are idempotent; changed
semantics under a reused notice ID conflict.

`RegistryHeadWitnessV1` binds registry identity, generation, predecessor head,
authority epoch, signer and expiry. Validation rejects generation rollback,
epoch rollback, predecessor mismatch and expired evidence. It validates the
bound fields but does not verify a cryptographic signature; the host must do
that before constructing the witness.

## Lifecycle ownership

The V2 evidence state machine is:

```text
proposed -> trained -> evaluated -> shadow -> canary
         -> operator_accepted -> selected -> retired
eligible states -> revoked
bounded early states -> quarantined
```

A producer may report training completion but cannot issue its own evaluation,
acceptance, selection, quarantine or revocation decision. State skips reject.
Snapshot recovery validates historical actor evidence at each event's immutable
occurrence time, while new appends validate actor evidence at the current write
time. `HEPTAL02` create-only snapshots prove durable reopen of that distinction.
The selector and route owner remain separate external authorities.

## Publication saga and host obligations

The product host must bind one durable saga:

1. reserve a create-only artifact identity;
2. write, synchronize and verify payload bytes;
3. check the current scoped withdrawal registry and issue V3 admission;
4. stage the exact V1 registry event against the expected predecessor head;
5. bind admission, withdrawal scope/head, event and resulting registry head into one publication transaction digest;
6. revalidate both mutable frontiers under the host writer fence;
7. durably publish the registry snapshot using the transaction digest as its binding;
8. publish an independently authenticated head witness;
9. acknowledge the producer only after the witness is durable.

The host also owns trusted directory traversal, containing-directory durability,
latest witness discovery, writer fencing, orphan collection, retention, backup
restore and actual process loading. The native head-witness file now provides a
bounded create-only distribution channel with independent receipt and
requirement revalidation; it does not discover the latest file or prove that a
self-consistent stale snapshot is current.

The stable V1 durable registry represents one predecessor and one support digest.
The V3 publication bridge rejects a V2 multi-predecessor manifest instead of
dropping lineage. Dataset-derived publication is likewise bridged only for one
source dataset so the V1 support digest remains the exact dataset digest used by
legacy `prepare_dataset_revocation`; multi-dataset publication fails closed until
a versioned durable format can represent every source explicitly. All
crate-owned durable histories share the 4096-record ceiling so accepted in-memory
state does not grow past the snapshot formats' representable bound.

Rollback requires a current authorized transition to a complete compatible
predecessor under the latest withdrawal and revocation frontier. An old backup
marker cannot reactivate a revoked candidate.

## Qualification mapping

Focused tests live in:

- `src/registry_tests.rs`;
- `src/storage_tests.rs` and storage budget tests;
- `src/pinned_tests.rs`;
- `src/dataset_revocation_tests.rs`;
- `src/closure_v2_tests.rs`;
- `src/admission_v3.rs` unit tests;
- `src/lifecycle_journal.rs` unit tests;
- `src/publication.rs` unit tests;
- `src/aux_storage.rs` unit tests;
- `src/iteration.rs` and `src/iteration_ledger.rs` unit tests.

Cross-crate composition is exercised by
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. Exact dossier IDs,
test functions and CI jobs are registered in
`../../qualification/lane-e/TEST_TRACEABILITY.json`.
