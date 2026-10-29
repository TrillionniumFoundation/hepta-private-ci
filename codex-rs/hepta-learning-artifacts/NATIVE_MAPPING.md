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

The crate owns no product signing key, selector private key, sandbox executor,
merge authority or release authority. It does own bounded verification of an
independently signed selector receipt plus local authenticated CURRENT
discovery/recovery. External head distribution, selector enrollment and private
signing authorities remain outside the crate. Public receipts use `AuthorityPosture::DENY_ALL` where an authority
posture is returned.

The `operator_sensor_core_registry` has no second writer. Sensor cores are first-class `ArtifactKind::SensorCore` records in the same append-only `ArtifactRegistry`; `project_operator_sensor_core_registry_v1` is a deterministic typed read view bound to the source registry head. Revocation/quarantine is therefore inherited from the physical artifact history rather than copied into another journal.

The V1 registry is a compatibility index. It cannot encode every V2 lineage
field, particularly multiple datasets and predecessors. Full V2 closure remains
bound by the V3 admission and publication transaction; it is never silently
flattened into one V1 predecessor.

## Design operation to Rust symbol

| Design operation | Native symbol | Source | Status |
|---|---|---|---|
| register/quarantine/revoke V1 candidate | `ArtifactRegistry::append` | `src/registry.rs` | retained |
| own sensor-core physical records in the same immutable registry | `ArtifactKind::SensorCore` | `src/model.rs` / `src/storage.rs` | implemented |
| expose typed sensor-core registry read domain | `project_operator_sensor_core_registry_v1` | `src/sensor_core_registry.rs` | implemented |
| create immutable payload/snapshot/head file | `CreateOnlyArtifactFile` | `src/storage.rs` | retained |
| contained create under trusted root | `CreateOnlyArtifactFile::create_beneath_trusted_root` | `src/storage.rs` | implemented |
| validate-before-create candidate write | `write_candidate_payload_beneath` | `src/storage.rs` | implemented |
| validate-before-create registry snapshot | `write_registry_snapshot_beneath` | `src/storage.rs` | implemented |
| validate-before-create current-head witness | `write_registry_head_witness_beneath` | `src/storage.rs` | implemented |
| read exact pinned candidate | `load_pinned_candidate` | `src/pinned.rs` | retained |
| revalidate cached consumer at a newer head | `RevalidatingCandidate::with_current` | `src/pinned.rs` | retained |
| issue opaque authenticated CURRENT registry view | `ArtifactOwnerVerifierV1::verify_current_registry_view` / `LearningArtifactOwnerHost::current_registry_view` | `src/owner_host.rs` | implemented |
| named product CURRENT/publication service | `LearningArtifactOwnerService::current_registry_view` / `publish` | `src/owner_service.rs` | product-composed source |
| verify selector trust independently of artifact-owner keys | `ArtifactSelectionVerifierV1::verify` | `src/selection.rs` | implemented |
| bind verified selector evidence to selected lifecycle transition | `record_verified_selection` | `src/selection.rs` | implemented |
| load exact independently selected immutable candidate | `load_selected_candidate` | `src/selection.rs` | qualification-composed source |
| verify the fixed initial SmolLM positive-zero material profile after original selector admission | private `initial_smollm_genesis` consumer in `load_selected_candidate` | `src/initial_smollm_genesis.rs` | non-installing selected-byte prerequisite; main-weight load NOT_OBSERVED |
| consume an original verified selection into opaque initial material; revalidate each read | `VerifiedArtifactSelectionV1::load_initial_smollm_material` / `SelectedInitialSmolLmMaterialV1::with_current` | `src/selected_initial_smollm.rs` | selected-byte prerequisite only; no installation or ordinary neural route |
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

### Initial neural baseline material prerequisite

The additive `hepta.learning-artifacts.smollm2-initial-positive-zero.v1`
namespace belongs to `learning.artifacts`. Its sole consumer is the original
`load_selected_candidate`, after independent `ArtifactSelectionVerifierV1`
admission. It accepts only a Parameters Genesis manifest at generation 1 and
one fixed, canonical safetensors encoding of all 120 F32 A/B factors: all
230,400 values must have the positive-zero bit pattern. The immutable profile
commits the upstream revision/file identity, expected backbone/tokenizer roots,
target contract, exact shapes and adapter expression. These expectations come
from code-owned profile bytes, never the supplied tensor header.

The compatibility commitment is
`561414aec8b51f2a18ae3948dd44a321f924b1e12961a8e0139774b42387fcf0`:
SHA-256 of the exact [profile bytes](profiles/smollm2-initial-positive-zero-v1.profile).
The fixed [canonical header](profiles/smollm2-initial-positive-zero-v1.safetensors.header)
is 12,056 bytes; its preceding little-endian length and the following 921,600
positive-zero factor bytes are exact. Manifest bounds are checked before the
original payload reader allocates the selected bytes. The header is compiled
as data in Cargo and Bazel; no untrusted header supplies a shape or expectation.

Only this new compatibility commitment invokes the additional validation.
Existing trained contracts, stored registry schemas, CURRENT and eligibility
semantics remain unchanged. Header aliases, duplicate/unknown keys, changed
shapes/offsets, non-F32 values, negative zero and trailing data are outside this
single canonical encoding and fail closed. There is no new parser dependency,
unqualified material factory, signing key, model constructor or state journal.
The generic selected loader retains its existing return type. Its additional
consumer, `VerifiedArtifactSelectionV1::load_initial_smollm_material`, consumes
only an original opaque verified selection, requires this exact fixed profile,
and verifies the actual selected bytes through that original loader. It returns
`SelectedInitialSmolLmMaterialV1` with private fields and no Clone, serialization
or external constructor. An old trained profile cannot enter this typed path.

The wrapper retains the original selector verification time, minimum signed/
trusted-selector expiry, known selector revocation and original owner-trust
identity. Loading and each bounded read consume an authenticated CURRENT view
from the original owner, enforce the immutable selection window and monotonic
consumer clock, and delegate current history/eligibility checks to the original
`RevalidatingCandidate`. Any failed read permanently closes that object. Cold
reopening re-verifies the same signed selection and actual files; it cannot
renew its expiry. CURRENT acquisition/distribution and the trusted clock remain
host responsibilities. The wrapper supplies no installation, evaluation, reward,
FinalUse, resource grant, main-weight measurement or neural route authority.

The next host composition prerequisite separates the private physical SmolLM
identity (selected parameter digest/generation and executable family/profile)
from Agentd's evaluated pin. `smollm_runtime_identity.rs` in the existing worker
host derives that identity only from the read port's unchanged complete pin. The
original qualified constructor, compatibility domain and FinalUse scope remain
unchanged. This factoring supplies no initial constructor, invented dataset or
objective, selected-material conversion, new profile or additional authority.

This check observes the selected adapter bytes, not the main upstream weight
bytes. The expected backbone/tokenizer identities are commitments rather than
actual-load observations. It grants no efficacy, installation, route, FinalUse,
resource, reward or selection authority. A later separately reviewed initial
baseline host path still needs original independent selection, authenticated
CURRENT, real upstream loading, resource/FinalUse owners and ordinary-task
readback. The existing SystemLongitudinal upgrade gate is unchanged; neither
Qualification evidence nor a learned gen2 artifact can impersonate that parent.

The initial-only host producer is `prepare_selected_initial_smollm_v1` in
`hepta-infer-worker-host/src/smollm_initial_host.rs`. Its single private Prepared
owner consumes the original Agentd config, selected material and concrete
`ArtifactOwnerCurrentReaderV1`; no port/config/session extraction or ordinary
task route is exposed. It loads through the original control/resource/Unix
FinalUse owners under `hepta.smollm.selected-initial-runtime.v1`, containing no
evaluation dataset/objective claim. Fresh CURRENT and the immutable selector
window bracket actual selected-byte, gen1, fixed backbone/tokenizer/contract,
Ready and settled-load-ID matching. Failed observations close material use;
post-load errors retain the same private original session for explicit cleanup.
The direct upstream model-file hash remains absent from Ready. The original
evaluated/SystemLongitudinal child constructor and all eligibility stay intact;
ordinary-task readback and the three-round product target remain open.

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

The owner host now performs bounded signed CURRENT discovery and exclusive writer
fencing. The deployment host still owns concurrent hostile ancestor protection,
parent-directory sync, external newest-head distribution, retention, backup
restore policy, indeterminate-write reconciliation and actual process loading.
Standard-library path checks are not an `openat2` directory capability.

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
- `src/sensor_core_registry.rs` tests, including single-physical-owner and revocation projection;
- `src/iteration.rs` and `src/iteration_ledger.rs` tests.

Cross-crate Lane E composition remains in
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. The exact
candidate is qualified only by the corresponding GitHub workflow execution;
source files and this mapping are not pass receipts.

The initial-material controls use actual temporary payload and registry files,
the original signed CURRENT verifier and independent selector factory. They
exercise cold byte reopening, nonzero/negative-zero/nonfinite factors, header
aliases, shapes/ranges, selector/profile/head/role/expiry conflicts and a newer
revocation. Test keys exercise signature separation only; they do not establish
production enrollment, model efficacy or a selected ordinary neural route.
