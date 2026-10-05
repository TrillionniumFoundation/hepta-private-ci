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

The service-to-host caller set is closed by `CALLERS.toml`; it proves a source
library seam, not executable startup. The normal Agentd entry point currently
does not construct `LearningArtifactOwnerService`, install a
`CurrentCognitiveRegistry` implementation or attach a selected
`PinnedCognitiveRanker`. Read attachment and independent selected loading remain
explicit embedding/qualification surfaces. See [`OWNER_SERVICE.md`](OWNER_SERVICE.md)
for configuration, trust roles, anchored restart, checkpoint recovery and the
remaining deployment evidence.

Agentd also provides an explicit descriptor-based plasticity bootstrap. It loads
a receipt-pinned V1 compatibility snapshot for Model/Parameters/Topology
baselines and policy evidence; its retained `ArtifactRegistry::is_eligible`
checks do not acquire a newer CURRENT or enforce full V2 manifest expiry/source
withdrawals. That consumer needs an explicit provenance profile and complete
current-view migration. A V1 support digest alone cannot identify which source
semantics it commits. The Owner/ranker bootstrap gap does not erase this already
implemented, narrower snapshot-consumer seam.

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
| bind exact eligible manifest to model/evaluation dataset | `VerifiedCurrentRegistryViewV1::supports_dataset` | `src/pinned.rs` | implemented full service provenance; explicit legacy V1 fallback |
| issue opaque authenticated V1 CURRENT registry view | `ArtifactOwnerVerifierV1::verify_current_registry_view` / `LearningArtifactOwnerHost::current_registry_view` | `src/owner_host.rs` | implemented compatibility view; full V2 service guard is separate |
| named CURRENT/publication library service | `LearningArtifactOwnerService::current_registry_view` / `publish` | `src/owner_service.rs` | source service seam; executable bootstrap absent |
| verify selector trust independently of artifact-owner keys | `ArtifactSelectionVerifierV1::verify` | `src/selection.rs` | implemented |
| bind verified selector evidence to selected lifecycle transition | `record_verified_selection` | `src/selection.rs` | implemented |
| load exact independently selected immutable candidate | `load_selected_candidate` | `src/selection.rs` | qualification-composed source |
| prepare snapshot-local dataset revocation | `prepare_dataset_revocation` | `src/dataset_revocation.rs` | retained |
| validate complete V2 manifest | `validate_artifact_manifest_v2` | `src/closure_v2.rs` | implemented |
| persist dataset withdrawal frontier in memory | `DatasetWithdrawalRegistry::append` | `src/closure_v2.rs` | implemented |
| domain/registry/scope-bind withdrawal state | `DatasetWithdrawalRegistry::new_scoped` | `src/closure_v2.rs` | implemented |
| deny future admission from withdrawn dataset | `DatasetWithdrawalRegistry::admit_manifest` | `src/closure_v2.rs` | implemented |
| persist scoped withdrawal snapshot | `write_dataset_withdrawal_snapshot` / `read_dataset_withdrawal_snapshot` | `src/durable_snapshots.rs` | implemented |
| contained scoped withdrawal snapshot write | `write_dataset_withdrawal_snapshot_beneath` | `src/durable_snapshots.rs` | implemented |
| validate latest-head/anti-rollback evidence | `validate_registry_head_witness` | `src/closure_v2.rs` | implemented |
| create scoped V3 admission | `admit_manifest_at_withdrawal_head_v3` | `src/admission_v3.rs` | implemented |
| persist/recover complete canonical V3 admission | `write_artifact_admission_beneath` / `read_artifact_admission` | `src/admission_storage.rs` | implemented; durable owner sidecar before Prepared |
| recover checkpoint/parent-committed full admission | `read_artifact_admission_by_digest` / `read_artifact_admission_by_manifest_digest` | `src/admission_storage.rs` | implemented; independent semantic digest required |
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

The owner atomically persists the complete canonical V3 admission as an
authoritative V2 sidecar before Prepared durability, and retains an immutable
manifest-digest index for inherited parent provenance. Recovery verifies the
sidecar against its independently retained checkpoint commitment. When the
V1 registry becomes durable, the transaction verifies the exact compatibility
projection: artifact identity, kind, generation, sole predecessor, payload
digest, producer, objective digest, complete manifest support commitment,
compatibility digest and exact byte count. Multiple V2 datasets, lineage digests
and predecessor IDs are **not** collapsed into V1 component fields.

The owner publication's V1 projection binds objective digest to the V2
objective-class digest and support digest to the complete validated V2 manifest
digest. Its sole predecessor is projected when there is exactly one. The owner
publication path rejects multiple predecessors before Prepared durability;
V2/V3 validation/admission retains that expressive shape for a future
multi-parent registry and final-use reader. Admission retention alone cannot
provide V1 multi-parent revocation enforcement. That support
commitment does not claim equality to any component source dataset digest.

The exact V1 registry snapshot receipt and independently validated head-witness
receipt are then bound into the transaction state digest. Registry durability,
witness durability and acknowledgement revalidate the live scoped withdrawal
frontier, so an intervening withdrawal blocks completion. Acknowledgement before
witness durability fails. Snapshot replay rejects shape/digest drift and
revalidates the embedded admission. `status()` exposes the current transaction
state as a deny-all observation surface for service/admin tooling.

The service current-view read guard checks all eligible full V2 admissions for
expiry, current withdrawal and inherited parent provenance. An internal
read-eligibility overlay excludes expired/withdrawn artifacts and single-parent
descendants while retaining valid unrelated consumers and the original signed V1
history. Missing/corrupt provenance closes acquisition. Selector verification and
cached consumption honor the overlay; durable quarantine/revocation remains
separately authorized. Low-level signed V1 current-view verification remains a
compatibility surface and does not replace this full V2 final-use boundary.
`supports_dataset` binds owner-published rankers to retained V2 source membership
rather than comparing the full-manifest support commitment to a dataset digest.
Selected consumers carry the verified owner trust and provenance requirement;
other pinned consumers bind their first accepted trust. Complete provenance
cannot later be downgraded to a same-trust raw V1 view. Either trust substitution
or provenance downgrade closes the consumer and requires explicit re-admission.

Pre-sidecar owner checkpoints do not transparently reopen under the new service.
Upgrade needs an independently authenticated full original admission and trusted
backfill/reprovisioning before restart; unavailable provenance fails closed.
V1 fields must never be used to invent omitted V2 closure.

The host must durably persist each transaction snapshot under its writer fence
before treating that phase as durable. This is an ordered crash-recovery
protocol, not a claim of a cross-file atomic filesystem transaction.

Every public Owner phase mutation and `resume_publication` additionally binds
the transaction to the latest complete durable checkpoint and the current
writer lease's producer/scope before effects. Public authority-free transaction
values cannot skip Prepared durability or restore an older phase. Authorized
lease rotation retains the original checkpoint lease commitment.

New operations bind Prepared to the discovered CURRENT/trusted genesis; exact
recovery preserves the original predecessor after uncertain head publication.
Canonical owner registration uses `artifact-publication:<intent_digest>` so
signed history binds checkpoint operation identity, full admission and
predecessor. Owner replay/current reads reject self-consistent local checkpoint
renaming that disagrees with that event. Current inventory checks the signed
prefix and at most one unfinished RegistryDurable snapshot; it does not reopen
all historical snapshots. Phase checkpoints precede in-memory advancement.
Exact terminal retries reverify and synchronize their existing Acknowledged
checkpoint and Unix parent directory before returning the original receipt.

V1 lineage eligibility has a private, replay-derived cache and child index.
Quarantine/revocation iteratively excludes descendants without changing immutable
records, event/chain digests or snapshot bytes. The index cannot grant selection
or override the complete V2 service eligibility overlay.

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

The owner host performs bounded signed CURRENT discovery, exclusive writer
fencing and owner-publication directory synchronization on Unix. Lower-level storage
callers retain their directory-sync obligation. The deployment host still owns
concurrent hostile ancestor protection, external newest-head distribution, retention, backup
restore policy, indeterminate-write reconciliation and actual process loading.
Standard-library path checks are not an `openat2` directory capability.

Read handles are independently opened and initially unlocked; Linux
cloned/inherited descriptors may share open-description lock state. Hosts drop
cached candidates on current-view acquisition errors and do not reuse an old
opaque view. Failed candidate revalidation also requires explicit re-admission.

## Qualification mapping

Focused coverage includes:

- `src/registry_tests.rs`;
- `src/storage_tests.rs`, `src/storage_lock_tests.rs` and storage budget tests;
- `src/pinned_tests.rs`;
- `src/dataset_revocation_tests.rs`;
- `src/closure_v2_tests.rs`;
- `src/admission_v3.rs` tests;
- `src/admission_storage_tests.rs`, including full canonical admission recovery,
  independent pins and malformed/oversized input rejection;
- `src/lifecycle_journal.rs` tests;
- `src/durable_snapshots.rs` tests;
- `src/publication.rs` tests;
- `src/publication_adversarial_tests.rs`;
- `src/owner_host_adversarial_tests.rs` and
  `src/owner_service_adversarial_tests.rs`, including trust floors, rejected
  witnesses, partial records, stable retry identity and anchored restart;
- `src/owner_admissions_tests.rs`, including complete durable recovery,
  inherited source closure and per-artifact expiry/withdrawal exclusions;
- `src/owner_checkpoint_tests.rs`, including canonical semantic replay, exact
  receipt progression, terminal corruption and historical withdrawal recovery;
- `src/owner_transaction_binding_tests.rs`, including detached/stale pure
  transactions, cross-producer/scope resume rejection before effects and a real
  checkpoint-write size fault that preserves the proven in-memory phase;
- `src/owner_generation_tests.rs`, including maximum-generation CURRENT
  publication/acknowledgement, read/reopen and extension rejection;
- `src/owner_registry_replay_tests.rs`, including canonical registration intent
  binding and coherent checkpoint rename rejection at recovery/startup/retry;
- `src/owner_rotation_tests.rs`, including live-only global floors, retained
  signed history and original per-key epoch/signature checks;
- `src/owner_atomic_storage_tests.rs`, including pre-publication rejection and
  interruption before final-name creation;
- `src/sensor_core_registry.rs` tests, including single-physical-owner and revocation projection;
- `src/registry_cache_tests.rs`, including deep iterative descendant exclusion,
  unchanged snapshots, clone/replay and overlapping invalidation;
- `src/iteration.rs` and `src/iteration_ledger.rs` tests.
- `src/iteration_ledger_capacity_tests.rs`, including snapshot capacity rejection
  before candidate-state allocation or event replay.

Cross-crate Lane E composition remains in
`../hepta-shadow-qualification/src/lane_e_closure_tests.rs`. The exact
candidate is qualified only by the corresponding GitHub workflow execution;
source files and this mapping are not pass receipts.
Agentd's `../hepta-agentd/src/cognitive_ranker_owner_tests.rs` additionally loads
a real owner-published ranker through full source membership, rejects a dataset
outside that provenance and closes cached use after withdrawal.
