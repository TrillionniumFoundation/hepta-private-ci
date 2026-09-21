# learning.artifacts: implementation design

Parent: `docs/modules/learning.artifacts/TECHNICAL.md`. Lane: `LANE-E-LEARNING`.
Status: V1 compatibility registry retained; complete V2 manifest, scoped V3
withdrawal admission, crash-recoverable publication contract, durable
withdrawal/lifecycle snapshots, pinned read boundary and governed iteration
source are implemented. Exact-head and synthetic-merge CI determine source
qualification; product activation, independent selection and release remain
separate external gates.

## 1. Source and work envelope

Roots: `codex-rs/hepta-learning-artifacts`.
Packages: `ART-1-LEARNING-ARTIFACT-REGISTRY`,
`ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`.

Concrete source mappings are recorded in
`../../../codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md` and
`../../../docs/lane-e/LANE_E_IMPLEMENTATION_MATRIX.json`. Preserve the stable
V1 registry/payload formats; additive V2/V3 state must not reinterpret old V1
files or create a second selection authority.

## 2. Public operations and contract details

Retained V1/store operations include
`ArtifactRegistry::append`, `write/read_registry_snapshot`,
`write/read_registry_head_witness`, `write/read_candidate_payload` and
`load_pinned_candidate`.

New/hardened operations include:

- `validate_artifact_manifest_v2`;
- `DatasetWithdrawalRegistry::new_scoped`, `append` and `admit_manifest`;
- `admit_manifest_at_withdrawal_head_v3`,
  `verify_artifact_admission_v3` and `validate_artifact_publication_v3`;
- `ArtifactPublicationTransactionV1::{begin, record_payload_durable,
  record_registry_durable, record_witness_durable, acknowledge, status, snapshot,
  from_snapshot}`;
- `ArtifactLifecycleJournalV2::{append, snapshot, from_snapshot}`;
- `write/read_dataset_withdrawal_snapshot` and
  `write/read_artifact_lifecycle_snapshot`;
- contained validation-before-create writers ending in `_beneath`;
- `validate_iteration_transition` and
  `IterationLedgerV1::{append_candidate, transition, snapshot, from_snapshot}`.
- `ArtifactSelectionVerifierV1::verify`, `record_verified_selection` and `load_selected_candidate`; selector trust is bound to the artifact-owner trust snapshot but uses a disjoint selector key set.

Candidate registration or admission is not selection. A successful read is not
execution or activation. Iteration records do not run a sandbox, merge source,
promote or release.

## 3. State records and transaction design

`LearningArtifactManifestV2` binds payload digest/length, every source dataset,
complete lineage digests, multiple predecessors, rollback predecessor, training
code, runtime, device, objective class, schema, normalization, compatibility,
producer, creation time and expiry.

`DatasetWithdrawalScopeV1` binds `authority_domain_id + registry_id + scope_id`.
A scoped registry has a scope-specific genesis/head; V3 admission additionally
binds that scope digest and withdrawal head. Unscoped registries cannot issue
V3 admissions.

The stable V1 registry is a compatibility index and cannot represent all V2
lineage. The implementation therefore does not collapse multiple V2
predecessors or datasets into one V1 field. `ArtifactPublicationTransactionV1`
retains the complete V3 admission as the authoritative V2 sidecar and verifies
that the final V1 registration agrees only on faithfully representable fields:
identity, kind, generation, payload digest, producer, compatibility digest and
exact byte length.

Publication is an ordered durability protocol:

```text
Prepared
  -> PayloadDurable
  -> RegistryDurable
  -> WitnessDurable
  -> Acknowledged
```

Each phase is digest-bound and replayable. Registry durability, witness durability
and final acknowledgement revalidate the live scoped withdrawal frontier; an
intervening withdrawal therefore stops an older admission from completing.
Acknowledgement before durable current-head witness evidence is rejected. The
host must persist the transaction snapshot under its writer fence before treating
a phase as durable; this is a hard host transaction contract, not a false claim
of atomic multi-file fsync.

## 4. Deterministic algorithm and scheduling

1. Authenticate the host-side actor/notice/witness before constructing typed
   source values.
2. Validate the complete V2 manifest and current scoped withdrawal frontier.
3. Create a V3 admission bound to exact withdrawal scope/head.
4. Begin a publication transaction at the exact current V1 predecessor head.
5. Validate payload and synchronize immutable bytes.
6. Append the V1 compatibility registration and durably publish its exact
   snapshot receipt.
7. Validate and durably publish the independently authenticated current-head
   witness.
8. Persist the transaction phase and acknowledge only after witness durability.
9. Verify a separately signed selector receipt against the exact authenticated CURRENT view and full artifact identity. The verifier produces only DENY_ALL load eligibility; it does not mint selector authority.
10. Record the verified selector digest as the `OperatorAccepted -> Selected` lifecycle evidence and, when requested by a qualification/product host, load that exact immutable candidate. Canary, promotion and release remain separate authorities.

The lifecycle evidence path is
`proposed -> trained -> evaluated -> shadow -> canary -> operator_accepted ->
selected -> retired`, with bounded quarantine/revocation edges. New mutations
validate the actor at current time. Historical recovery validates actor evidence
at the event's immutable `occurred_at`, so credential expiry after a valid
append cannot make the journal unrecoverable.

## 5. Persistence, capacity and path safety

V1 registry, scoped withdrawal and lifecycle state all have canonical
create-only durable snapshots with independently retained receipts. Withdrawal
receipts bind scope digest; lifecycle replay verifies every historical event.

`MAX_DURABLE_ARTIFACT_RECORDS = 4096` is shared by artifact-registry,
withdrawal and lifecycle state, closing the prior mismatch where an in-memory
registry could accept more records than the durable snapshot format.

Candidate payloads are bounded at 64 MiB; V1/auxiliary snapshots are bounded.
V2 manifests bound datasets, lineage and predecessor vectors. Iteration
envelopes separately cap candidates, files, semantic diff bytes and named
parallel sandboxes.

For new path-based host integration, use the `*_beneath` writers. They validate
before final-path creation and reject absolute paths, `..`, non-normal
components and symlink ancestors below a canonical trusted root. The host still
owns protection against concurrent hostile ancestor replacement, parent
directory sync, writer fencing and indeterminate I/O reconciliation.

## 6. Concrete verification cases

The canonical Lane E case IDs are:

- **ART-01:** create-only ID reuse with different bytes conflicts; identical
  retry remains bounded/idempotent where specified.
- **ART-02:** crash after bytes sync but before completed publication yields a
  partial/orphan candidate, never an acknowledged or selected artifact.
- **ART-03:** corrupt/incomplete/mixed-generation payload is refused by a new
  loading process.
- **ART-04:** rollback to a revoked or incompatible predecessor fails safely
  even if an old backup once marked it selected.
- **ART-05:** scoped V3 admission binds authority-domain, registry, scope and
  exact withdrawal head; a concurrent withdrawal invalidates the old admission.
- **ART-06:** lifecycle state is append-only and role-separated; historical
  replay survives later actor expiry while new expired-actor mutation fails.
- **ART-07:** publication follows only `Prepared -> PayloadDurable ->
  RegistryDurable -> WitnessDurable -> Acknowledged`; crash recovery or a
  withdrawal race cannot skip phases.
- **ART-08:** scoped withdrawal and lifecycle auxiliary histories round-trip
  through exact create-only durable snapshots and reject mismatched receipts.
- **ART-09:** sensor cores are first-class `ArtifactKind::SensorCore` records in
  the one physical `ArtifactRegistry`; the typed sensor-core read domain is
  rebuilt from that head and reflects revocation without a second writer.
- **ART-10:** iteration bookkeeping is bounded, replayable and monotonic and
  cannot turn proposal/evidence records into selection, merge, promotion or
  release authority.
- **ART-11:** the named `LearningArtifactOwnerService` is the unique registered
  product caller of the fenced `LearningArtifactOwnerHost`; it executes the
  complete durable publication saga, returns stable terminal retries, reopens
  only from independently authenticated CURRENT, rejects restored old heads and
  stale signer epochs, and process-kill recovery never promotes an
  uncheckpointed publication phase. Read consumers receive only opaque
  `VerifiedCurrentRegistryViewV1` values issued after signed CURRENT + exact
  snapshot verification; a bare `File + RegistrySnapshotReceipt` is not a
  product currentness interface.
- **ART-12:** selector verification is a separate Ed25519 trust domain bound to
  the exact artifact-owner trust snapshot; selector keys may not equal
  writer/head authority keys or the artifact producer identity. The signed
  selection binds exact CURRENT witness/trust/head plus artifact kind,
  generation, predecessor, payload/objective/support/compatibility digests and
  byte length. Verified selection records only the
  `OperatorAccepted -> Selected` lifecycle transition with DENY_ALL authority.
  The cross-process tabular qualification then loads generation 2, reloads the
  exact compatible generation-1 predecessor in another process, and proves that
  fresh signed selection attempts at the post-revocation CURRENT head fail
  before payload use.

Contained-write/path-escape and V1-projection swap tests remain supplemental
hardening cases rather than separate authority claims.

Every canonical Lane E case remains mapped in
`../../lane-e/TEST_TRACEABILITY.json`. Source test identity is not an execution
receipt.

## 7. Integration, rollback and capability ceiling

`RevalidatingCandidate::with_current` guards cached consumption with a
monotonic current registry prefix and exact lineage eligibility. Any failed
refresh closes the consumer. A valid old snapshot cannot be substituted to
resurrect a revoked candidate.

The persistent scoped withdrawal registry closes future admission of withdrawn
datasets. Snapshot-local `prepare_dataset_revocation` remains the batch that
stages direct artifact revocations; it is not the persistent tombstone store.

The crate intentionally provides no mutable admin override, force-select,
force-promote, force-release or force-repair API. Product/admin tooling can use
`ArtifactPublicationTransactionV1::status` as a deny-all read-only projection of
publication state, then perform any external repair only through a separately
authenticated and fenced host operation.

## 8. Current native implementation

Authenticated CURRENT discovery supports bounded signer rotation: historical pre-revocation heads remain replayable, while the newest head requires a currently valid signer and non-regressing authority epoch.

`ArtifactOwnerVerifierV1::verify_current_registry_view` and
`LearningArtifactOwnerHost::current_registry_view` issue the same opaque
`VerifiedCurrentRegistryViewV1`. `RevalidatingCandidate::with_current` accepts
only that type, and Agentd's `CurrentCognitiveRegistry` surface returns it
instead of a caller-constructible file/receipt pair.

- **Compatibility registry/storage:** `registry.rs`, `storage.rs`,
  `pinned.rs`.
- **V2/V3 closure:** `closure_v2.rs`, `admission_v3.rs`.
- **Publication transaction:** `publication.rs`.
- **Lifecycle and persistent withdrawal durability:**
  `lifecycle_journal.rs`, `durable_snapshots.rs`.
- **Revocation preparation:** `dataset_revocation.rs`.
- **Sensor-core physical ownership/read domain:** `model.rs`,
  `sensor_core_registry.rs`; first-class sensor-core records share the
  ArtifactRegistry physical writer and durable snapshot.
- **Governed self-iteration bookkeeping:** `iteration.rs`,
  `iteration_ledger.rs`.
- **Independent selection verification/load:** `selection.rs`; the source owns verification and exact load eligibility, not selector private keys or canary/promotion authority.
- **Operating references:** `STORAGE.md`, `READ_BOUNDARY.md`,
  `PINNED_LOAD.md`, `DATASET_REVOCATION.md`, `NATIVE_MAPPING.md`.

The repository-controlled source gap is now primarily exact-candidate
qualification, not missing core data structures. Current CI must still prove the
exact head and actual-base synthetic merge.

## 9. Native closure and remaining evidence

Repository-controlled source coverage is checked by
`../../../scripts/hepta-lane-e-closure.py`; exact-head and ordered-parent
synthetic-merge execution are defined in
`.github/workflows/hepta-lane-e-gap-closure.yml`.

The workflow compiles all targets, runs owner and cross-crate tests, strict
Clippy and rustfmt. Push synthetic merge resolves its predecessor from
`github.event.before`; PR synthetic merge uses the pull-request base.

External evidence intentionally remains open. The repository cannot self-provision a trusted production filesystem namespace, artifact-owner or selector private keys, prove parent-directory durability on every target, operate the external newest-head distribution service, prove external-cache/physical-erasure behavior, or issue live operator acceptance, canary, promotion or release. Repository tests can verify signed selection/load/revoke/rollback semantics but are not production selection or rollout receipts.
