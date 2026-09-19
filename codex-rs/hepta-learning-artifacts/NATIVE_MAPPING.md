# `learning.artifacts` native implementation mapping

This file maps the current immutable artifact, admission, publication, withdrawal,
lifecycle and governed-iteration implementation to concrete Rust symbols.
Candidate storage and qualification evidence are not selection, activation,
promotion or release authority.

## Compatibility and authority boundary

The stable V1 `ArtifactRegistry`, payload files, registry snapshots and pinned
loader remain readable. The additive V2/V3 layers make complete provenance,
withdrawal scope and publication ordering explicit without reinterpreting
historical V1 files.

The crate owns no product signing key, newest-head discovery service, production
route, sandbox executor, selector, merge authority or release authority. Public
receipts use `AuthorityPosture::DENY_ALL` where an authority posture is
returned.

The V1 registry is a compatibility index. It cannot encode every V2 lineage
field, particularly multiple datasets and predecessors. Full V2 closure remains
bound by the V3 admission and publication transaction; it is never silently
flattened into one V1 predecessor.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| register/quarantine/revoke V1 candidate | `ArtifactRegistry::append` | `src/registry.rs` | retained |
| create immutable payload/snapshot/head file | `CreateOnlyArtifactFile` | `src/storage.rs` | retained |
| contained create under trusted root | `CreateOnlyArtifactFile::create_beneath_trusted_root` | `src/storage.rs` | implemented |
| validate-before-create candidate write | `write_candidate_payload_beneath` | `src/storage.rs` | implemented |
| validate-before-create registry snapshot | `write_registry_snapshot_beneath` | `src/storage.rs` | implemented |
| validate-before-create current-head witness | `write_registry_head_witness_beneath` | `src/storage.rs` | implemented |
| read exact pinned candidate | `load_pinned_candidate` | `src/pinned.rs` | retained |
| revalidate cached consumer at a newer head | `RevalidatingCandidate::with_current` | `src/pinned.rs` | retained |
| prepare snapshot-local dataset revocation | `prepare_dataset_revocation` | `src/dataset_revocation.rs` | retained |
| validate complete V2 manifest | `validate_artifact_manifest_v2` | `src/closure_v2.rs` | implemented |
| persist dataset withdrawal frontier in memory | `DatasetWithdrawalRegistry::append` | `src/closure_v2.rs` | implemented |
| domain/registry/scope-bind withdrawal state | `DatasetWithdrawalRegistry::new_scoped` | `src/closure_v2.rs` | implemented |
| deny future admission from withdrawn dataset | `DatasetWithdrawalRegistry::admit_manifest` | `src/closure_v2.rs` | implemented |
| persist scoped withdrawal snapshot | `write_dataset_withdrawal_snapshot` / `read_dataset_withdrawal_snapshot` | `src/durable_snapshots.rs` | implemented |
| contained scoped withdrawal snapshot write | `write_dataset_withdrawal_snapshot_beneath` | `src/durable_snapshots.rs` | implemented |
| validate latest-head/anti-rollback evidence | `validate_registry_head_witness` | `src/closure_v2.rs` | implemented |
| create scoped V3 admission | `admit_manifest_at_withdrawal_head_v3` | `src/admission_v3.rs` | implemented |
| revalidate V3 admission at publication | `validate_artifact_publication_v3` | `src/admission_v3.rs` | implemented |
| enforce publication durability order | `ArtifactPublicationTransactionV1` | `src/publication.rs` | implemented |
| validate lifecycle transition | `validate_artifact_lifecycle_transition` | `src/closure_v2.rs` | implemented |
| append/replay lifecycle journal | `ArtifactLifecycleJournalV2::append` / `from_snapshot` | `src/lifecycle_journal.rs` | implemented |
| persist lifecycle snapshot | `write_artifact_lifecycle_snapshot` / `read_artifact_lifecycle_snapshot` | `src/durable_snapshots.rs` | implemented |
| contained lifecycle snapshot write | `write_artifact_lifecycle_snapshot_beneath` | `src/durable_snapshots.rs` | implemented |
| validate governed iteration transition | `validate_iteration_transition` | `src/iteration.rs` | implemented |
| record externally evidenced iteration state | `IterationLedgerV1::append_candidate` / `transition` / `from_snapshot` | `src/iteration_ledger.rs` | implemented |

## V2/V3 manifest and withdrawal binding

`LearningArtifactManifestV2` binds every source dataset digest, additional
lineage evidence, multiple predecessor IDs, optional rollback predecessor,
payload digest and byte count, training code, runtime tuple, device profile,
objective class, schema, normalization, compatibility, producer, creation time
and expiry.

`DatasetWithdrawalScopeV1` binds:

- `authority_domain_id`;
- `registry_id`;
- `scope_id`.

A scoped registry derives a scope-specific non-zero genesis head and
scope-separated chain digests. `WithdrawalBoundArtifactAdmissionV3` includes
the scope digest and withdrawal head in the admission digest. V3 admission from
an unscoped registry fails closed; publication under another scope is rejected.

The host authenticates the real authority/signature before constructing typed
notice or witness values. These source types bind and validate evidence; they do
not own private signing keys.

## Publication transaction and V1 compatibility projection

`ArtifactPublicationTransactionV1` is the hard host transaction contract:

`Prepared -> PayloadDurable -> RegistryDurable -> WitnessDurable -> Acknowledged`.

It stores the complete V3 admission as the authoritative V2 sidecar. When the
V1 registry becomes durable, the transaction verifies only fields that V1 can
faithfully represent: artifact identity, kind, generation, payload digest,
producer, compatibility digest and exact byte count. Multiple V2 datasets,
lineage digests and predecessor IDs are **not** collapsed into V1 fields.

The exact V1 registry snapshot receipt and independently validated head-witness
receipt are then bound into the transaction state digest. Registry durability,
witness durability and acknowledgement revalidate the live scoped withdrawal
frontier, so an intervening withdrawal blocks completion. Acknowledgement before
witness durability fails. Snapshot replay rejects shape/digest drift and
revalidates the embedded admission. `status()` exposes the current transaction
state as a deny-all observation surface for service/admin tooling.

The host must durably persist each transaction snapshot under its writer fence
before treating that phase as durable. This is an ordered crash-recovery
protocol, not a claim of a cross-file atomic filesystem transaction.

## Lifecycle recovery

The lifecycle evidence state machine remains:

```text
proposed -> trained -> evaluated -> shadow -> canary
         -> operator_accepted -> selected -> retired
eligible states -> revoked
bounded early states -> quarantined
```

New mutations validate actor credentials at the host-supplied current time.
Historical journal replay validates the credential at the event's immutable
`occurred_at`. Therefore a restart after credential expiry can still recover
history that was valid when appended, while the same expired actor cannot create
a new mutation.

Canonical create-only lifecycle snapshots bind host storage scope, file digest,
record count and chain head and replay every event before returning state.

## Governed iteration

`iteration.rs` and `iteration_ledger.rs` make the documented iteration
boundary executable without adding execution authority. The envelope caps files,
diff bytes, candidates and parallel sandboxes. The iteration ledger only records
externally supplied typed evidence and monotonic state transitions. Independent
states reject generator-self evidence where required. It does not run a sandbox,
perform evaluation, choose a winner, merge source, promote or release.

## Storage, capacity and path boundary

Artifact-registry, withdrawal and lifecycle state machines share
`MAX_DURABLE_ARTIFACT_RECORDS = 4096`. This aligns logical record acceptance
with the supported bounded snapshot adapters. Candidate payloads remain bounded
at 64 MiB; the V1 registry and auxiliary canonical snapshots are bounded.

The contained writer APIs reject absolute paths, `..`, non-normal components
and symlink ancestors below a canonical host-designated trusted root. They also
perform semantic validation before final-path creation, preventing ordinary
validation failures from leaving zero-length final-path orphans.

The host still owns concurrent hostile ancestor protection, parent-directory
sync, newest-file discovery, writer fencing, retention, backup restore,
indeterminate-write reconciliation and actual process loading. Standard-library
path checks are not an `openat2` directory capability.

## Qualification mapping

Focused coverage includes:

- `src/registry_tests.rs`;
- `src/storage_tests.rs`, `src/storage_lock_tests.rs` and storage budget tests;
- `src/pinned_tests.rs`;
- `src/dataset_revocation_tests.rs`;
- `src/closure_v2_tests.rs`;
- `src/admission_v3.rs` tests;
- `src/lifecycle_journal.rs` tests;
- `src/durable_snapshots.rs` tests;
- `src/publication.rs` tests;
- `src/iteration.rs` and `src/iteration_ledger.rs` tests.

Cross-crate Lane E composition remains in
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. The exact
candidate is qualified only by the corresponding GitHub workflow execution;
source files and this mapping are not pass receipts.
