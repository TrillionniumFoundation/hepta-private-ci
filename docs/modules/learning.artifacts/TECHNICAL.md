# learning.artifacts technical development guide

**Module:** `learning.artifacts`  
**Owner:** `learning-platform`  
**Deputy:** `durability-kernel`  
**Source root:** `codex-rs/hepta-learning-artifacts`  
**Architecture role:** authoritative immutable learning-artifact registry and bounded governance bookkeeping  
**Current source state:** implemented candidate; product activation, operator acceptance, promotion and release remain external

This document is the current implementation guide for the native `learning.artifacts` crate. It describes the source that exists now, the durable boundaries it actually enforces, and the host obligations that remain outside the crate. It must not be read as an activation or release receipt.

## 1. Mission and authority boundary

`learning.artifacts` owns immutable artifact identity, lineage, registry eligibility, current withdrawal checks, lifecycle bookkeeping, bounded governed-iteration records, pinned artifact loading, and create-only persistence primitives.

The crate is deliberately **authority-free** with respect to selection, activation, promotion and release. Successful validation, persistence, replay, qualification or publication-plan sealing never grants those powers. Public receipt types that carry an `AuthorityPosture` use `DENY_ALL`.

The module does not authenticate signatures by itself. Hosts must authenticate signer/credential evidence before constructing typed inputs such as lifecycle actor evidence, withdrawal authority domains and current-head witnesses.

The module also does not own a product-global filesystem transaction. Where several immutable files participate in one generation, the host owns the independently authenticated current pointer and parent-directory durability. The crate supplies exact receipts and a fail-closed publication transaction contract so a partially durable generation cannot be represented as a committed publication.

## 2. Native source decomposition

| Source | Responsibility |
| --- | --- |
| `src/model.rs` | V1 artifact manifest, registry event and state types |
| `src/registry.rs` | append-only V1 artifact registry, lineage eligibility and exact replay |
| `src/closure_v2.rs` | complete V2 manifest validation, dataset withdrawal registry, current registry-head witness and lifecycle transition semantics |
| `src/admission_v3.rs` | V3 admission bound to exact withdrawal frontier **and** authenticated withdrawal authority domain |
| `src/lifecycle_journal.rs` | predecessor-bound lifecycle journal with actor-role separation and exact historical replay |
| `src/dataset_revocation.rs` | staged dataset-driven V1 registry revocation without mutating the caller's current registry |
| `src/storage.rs` | create-only V1 registry snapshots, current-head witness files and candidate payload IO |
| `src/durable_authority.rs` | create-only durable withdrawal/lifecycle snapshots with exact receipt and semantic replay |
| `src/publication.rs` | V2-admission-to-durable-generation publication plan/transaction/commit contract |
| `src/pinned.rs` | pinned candidate load and current revalidation boundary |
| `src/iteration.rs` | bounded, authority-free self-iteration envelope/candidate state machine |
| `src/iteration_ledger.rs` | bounded append-only iteration evidence bookkeeping and exact replay |
| `src/storage_hygiene.rs` | enrolled-root path containment, storage inspection and conservative zero-length orphan cleanup |
| `src/error.rs` | V1 registry error vocabulary |
| `src/lib.rs` | public source surface |

The crate currently has no production service daemon and no API that performs a product deployment. A product host composes these primitives under its own authenticated writer fence and current-generation pointer.

## 3. Core invariants

### 3.1 Immutable V1 registry

`ArtifactRegistry` is an append-only event chain. Registration, quarantine and revocation are new records; existing records are never rewritten. Event identity is idempotent only for identical semantics. Reusing an event identity with changed content fails closed.

Every record binds sequence, predecessor chain digest and event digest. Snapshot reconstruction replays the semantic events and checks that the reconstructed records and head match exactly.

Eligibility is lineage-sensitive. A candidate is eligible only while it and every predecessor remain in `Candidate`; quarantine or revocation of an ancestor therefore invalidates descendants without mutating descendant records.

### 3.2 Complete V2 manifest

`LearningArtifactManifestV2` keeps independent fields for artifact bytes, training code, runtime tuple, device profile, objective class, compatibility, schema profile, normalization, source datasets, lineage digests, predecessors and rollback predecessor.

Validation is bounded and canonicalizes sortable collections before computing the manifest digest. Dataset-derived manifests require explicit source dataset digests; dataset-independent manifests must not carry dataset provenance. Expiry is checked at the validation time.

V2 is richer than the stable V1 registry manifest. A V1 registry entry is therefore a durable registry projection, not a lossless replacement for the V2 manifest.

### 3.3 Withdrawal authority domain binding

A withdrawal frontier digest alone is not sufficient domain identity: two independent empty registries have the same zero head, and two independent registries can in principle share the same event history.

`WithdrawalAuthorityDomainV1` therefore binds:

- `registry_id`;
- `scope_digest`;
- `authority_id`;
- `authority_epoch`.

`WithdrawalBoundArtifactAdmissionV3` binds the validated V2 manifest to both the exact withdrawal head and the digest of this authority domain. Publication revalidation requires the same current domain and the same current head. A receipt produced under one domain cannot be replayed under another even when both heads are zero.

The domain digest is separated with `hepta.learning-artifacts.withdrawal-authority-domain.v1`; the admission digest is separated with `hepta.learning-artifacts.withdrawal-bound-admission.v3`.

### 3.4 Lifecycle historical recovery versus fresh authorization

Fresh lifecycle mutation requires actor evidence to be valid at `now`, and the event occurrence time must fall inside the actor's verified validity window.

Historical recovery has different semantics. A credential that was valid when a persisted event occurred does **not** make the historical event invalid merely because that credential has since expired. `ArtifactLifecycleJournalV2::from_snapshot` therefore reconstructs each immutable record at its recorded `event.occurred_at`, while fresh `append` continues to enforce current-time authorization.

This separation is a durability invariant: a service can restart after credential expiry and recover a valid historical journal, but the expired actor still cannot publish a new mutation.

### 3.5 Deny-all authority

The registry, admission, lifecycle, durable-authority and publication receipts do not grant selection, activation, promotion or release. These decisions require an independent control plane. Iteration states named `Selected`, `Promoted` and `Released` are bookkeeping states whose evidence must have been produced and authenticated externally; recording the state is not the source of the authority.

## 4. Registry and withdrawal state machines

### 4.1 Artifact registry

The stable registry accepts:

- `Register` with immutable manifest projection;
- `Quarantine` with independent evaluator and non-zero reason digest;
- `Revoke` with independent evaluator and non-zero reason digest.

Derived registration requires an existing eligible predecessor, strictly advanced generation, identical objective digest and identical artifact kind.

### 4.2 Dataset withdrawal registry

`DatasetWithdrawalRegistry` is a separate append-only digest chain. A notice binds notice identity, dataset digest, source tombstone digest, authority identity, credential-chain digest, signing-key digest, authority epoch and issue time.

Exact notice retry is idempotent; reused notice identity with changed semantics conflicts. Current admission checks every V2 source dataset against the current withdrawal registry and rejects any withdrawn source.

The registry is semantically replayable from `DatasetWithdrawalRegistrySnapshotV1`. Durable file placement is provided by `durable_authority.rs` and remains scoped by an externally authenticated `WithdrawalAuthorityDomainV1`.

## 5. Lifecycle journal

`ArtifactLifecycleJournalV2` records exact predecessor head, sequence, producer, actor evidence, event digest, chain digest and lifecycle event.

The journal checks:

1. exact expected current head;
2. actor evidence shape and time window for new mutations;
3. event/actor/credential/epoch binding;
4. stable lifecycle transition validity;
5. event identity conflict/idempotence;
6. current per-artifact predecessor state;
7. role separation for producer, evaluator, shadow/canary/human operators, selector, quarantine authority, revocation authority and retirement authority;
8. bounded record count;
9. exact snapshot replay and head equality.

Snapshot recovery intentionally validates historical records at their immutable event time rather than the service restart time. That rule is also used by durable lifecycle-file reconstruction.

## 6. Governed iteration and iteration ledger

`iteration.rs` provides bounded native records for self-iteration without granting execution or release authority.

`IterationEnvelopeV1` binds base commit/tree, objective, grammar and hard ceilings for files, diff bytes, candidate count and parallel sandboxes. `IterationCandidateV1` binds generator identity, semantic diff, test plan, rollback digest and exact predecessor.

The state machine is monotonic:

`Drafted -> StaticallyValidated -> SandboxTested -> IndependentlyEvaluated -> ReviewRequested -> AcceptedCandidate -> Selected -> Promoted -> Released`

At any non-terminal stage a candidate may instead become `Rejected`, `Quarantined` or `Superseded`. Terminal states cannot transition further.

`IterationLedgerV1` records typed external evidence for transitions. It does not execute a sandbox, evaluate code, select a winner or perform release. Evidence IDs are single-use; changed content under a reused evidence identity conflicts. Independent stages reject evidence supplied by the generator identity. Snapshot restoration rebuilds candidate state only by replaying the recorded events, preventing a snapshot from smuggling in an unreceipted state.

## 7. Durable storage formats

### 7.1 Stable artifact registry and payload storage

`storage.rs` owns create-only registry snapshots, current-head witness files and candidate payload files. Files are created with `create_new`; Unix files use mode `0600`. Reads are length-bounded, locked, digest-checked and semantically reconstructed.

The registry snapshot receipt independently carries binding, head digest, file digest, record count and encoded length. The caller must retain/authenticate the receipt independently of the suspect file.

Candidate payload loading requires a current authenticated registry snapshot and exact manifest digest/length match. A successful load does not grant execution or selection authority.

### 7.2 Withdrawal and lifecycle authority snapshots

`durable_authority.rs` adds equivalent create-only durability for authority state.

Current binary magics:

- withdrawal registry: `HPTWDR01`;
- lifecycle journal: `HPTLCJ02`.

Each file is bounded to 64 MiB and at most 1,000,000 records. `AuthoritySnapshotReceiptV1` independently binds kind, authority/scope binding digest, semantic head, file digest, record count and encoded length.

Readback requires exact file size and file digest, decodes bounded fields, reconstructs the semantic state using the normal validators, rejects trailing bytes, and requires the reconstructed head to equal the independently supplied receipt.

Withdrawal files are domain-bound. Lifecycle files preserve historical validity across actor credential expiry while still replaying the same transition/role/digest semantics.

### 7.3 Filesystem obligations left to the host

Create-only file creation proves the final path did not already exist at the open operation. It does not by itself make arbitrary ancestor directories immutable. The selected host must enroll/protect storage roots, own directory permissions and ensure containing-directory durability.

No code in this crate claims a cross-filesystem transaction.

## 8. V2 admission to durable publication contract

`publication.rs` makes the previously implicit host composition explicit.

`prepare_artifact_publication_v1` requires:

1. a current V3 admission whose withdrawal authority domain and head still match;
2. a currently eligible V1 registry projection for the same artifact;
3. exact equality for V2/V1 fields that the V1 projection can represent: artifact identity, kind, generation, bytes digest, objective digest, producer, compatibility and encoded size;
4. exact registry snapshot head/count and external registry binding;
5. exact withdrawal domain binding/head/count;
6. exact lifecycle binding/head/count;
7. publication scope, generation and predecessor publication digest.

The resulting `ArtifactPublicationPlanV1` hashes all these facts into a plan digest.

`ArtifactPublicationTransactionV1` then accepts durable receipts for exactly three immutable state files:

- the V1 artifact registry snapshot;
- the withdrawal registry snapshot;
- the lifecycle journal snapshot.

A receipt whose binding, head, kind or record count differs from the plan is rejected. `seal()` fails with `DurabilityIncomplete` until all three exact durable receipts have been acknowledged.

Once complete, `ArtifactPublicationCommitV1` binds the plan digest plus the three file bindings, semantic heads, file digests, record counts and lengths into one commit digest.

### Required host publication sequence

A product host MUST use the following order under one exclusive writer fence:

1. authenticate all external authority evidence;
2. obtain/revalidate V3 admission against the current withdrawal domain/head;
3. stage the V1 registry successor and lifecycle/withdrawal states;
4. prepare the publication plan against those exact states;
5. create, write and `fsync` the registry snapshot;
6. create, write and `fsync` the withdrawal snapshot;
7. create, write and `fsync` the lifecycle snapshot;
8. acknowledge the three exact receipts in the publication transaction;
9. seal and verify the publication commit;
10. persist that commit in the host's generation record and make it durable;
11. only then atomically publish the independently authenticated current-generation pointer;
12. sync the containing directory as required by the selected host filesystem contract.

Dropping or crashing an incomplete transaction produces **no sealed publication commit**. Orphan immutable files may remain, but the old authenticated current pointer remains authoritative. The host must never infer publication from the mere presence of one or more generation files.

This is a hard composition contract, not a claim that Rust can atomically commit independent filesystem files.

## 9. Read, pinned-load and recovery boundary

Read selection is external and authenticated. The crate validates the supplied current-head witness and snapshot receipt; it does not silently search older snapshots or choose a fallback generation.

Pinned loading binds exact artifact identity/content and revalidates current registry eligibility. Current withdrawal/lifecycle checks remain separate freshness authorities where required by the caller. Restoring an older but internally valid file is insufficient when the host's independent current-generation witness requires a newer predecessor/generation.

Recovery rules are fail-closed:

- corrupt/truncated/digest-mismatched files are rejected;
- semantic replay mismatch is rejected;
- current-head rollback or predecessor mismatch is rejected;
- stale V3 withdrawal head/domain is rejected;
- incomplete publication transactions cannot seal;
- lifecycle recovery survives normal expiry of credentials that were valid at event time.

## 10. Storage path and orphan hardening

`ArtifactStorageAdminV1` is a narrow administration helper around an enrolled canonical root.

It accepts only relative paths composed of normal path components. Absolute paths, `.`/`..`, platform prefixes and root components are rejected. The existing parent directory is canonicalized and must remain beneath the enrolled root before a target leaf is resolved.

The host must still prevent concurrent replacement of enrolled ancestor directories; without an OS-specific descriptor-walking API this crate does not claim to close that race universally.

`cleanup_zero_length_orphan` is intentionally conservative. It may remove only an existing regular, non-symlink, zero-length file and syncs the containing directory afterward. Non-empty files, directories, symbolic links and special files are left untouched. There is no recursive or pattern-based delete API.

## 11. Dataset-driven revocation

`prepare_dataset_revocation` is a staging operation. It clones the current V1 registry, verifies the expected predecessor head, finds directly dataset-bound registrations, applies stable revoke events to the clone and returns a `PreparedDatasetRevocation` plus summary.

The caller's current registry is not mutated. The host must durably publish the prepared successor under the same generation/publication discipline before acknowledging completion. Existing lineage eligibility propagates ancestor revocation to descendants.

## 12. Test and fault matrix

The focused crate tests now cover at least the following closure properties:

- `art_05_admission_binds_exact_withdrawal_head_and_domain`;
- `art_05_cross_domain_zero_head_is_rejected`;
- `art_05_withdrawal_race_invalidates_admission`;
- `art_06_lifecycle_journal_enforces_head_state_and_role`;
- `art_06_lifecycle_journal_replays_exact_snapshot`;
- `art_06_historical_replay_survives_actor_expiry_but_new_append_does_not`;
- `art_07_withdrawal_registry_durable_roundtrip_rebuilds_exact_head`;
- `art_07_lifecycle_durable_roundtrip_survives_actor_expiry`;
- `art_08_publication_transaction_is_unsealable_after_partial_durability`;
- `art_08_publication_commit_binds_all_durable_receipts`;
- `art_09_storage_admin_rejects_parent_escape`;
- `art_09_storage_admin_removes_only_zero_length_orphan`;
- iteration candidate predecessor/budget/state tests;
- iteration-ledger external-evidence, actor separation, duplicate evidence and snapshot replay tests;
- existing registry, storage, pinned-load, closure V2 and dataset-revocation suites.

From `codex-rs`, the focused crate command is:

```bash
just test --locked -p codex-hepta-learning-artifacts
```

Compilation and lint qualification must use the workspace-pinned toolchain and lockfile.

## 13. Lane E exact-head and synthetic-merge qualification

`.github/workflows/hepta-lane-e-gap-closure.yml` separates two different proofs:

- `rust-closure` qualifies the exact PR head (and remains valid on a `main` push);
- `synthetic-merge` qualifies the ordered base+source merge candidate and therefore runs only for `pull_request`, where GitHub supplies an exact PR base SHA.

The workflow checks closed-world inventory, locked all-target compilation, owner regression tests, cross-crate causal closure, cross-language wire/fault tests, strict `clippy -D warnings`, formatting and a clean source/index.

A green source test alone is not module closure. The candidate is source-qualified only when the exact-head and PR synthetic-merge evidence for that same candidate are current and green.

## 14. Host/service boundary

Repository source now contains the durable primitives and transaction contract needed to compose a product writer, but it still does not establish a product production writer by itself.

The selected product host must own and qualify:

- authenticated writer fencing;
- signer/credential authentication;
- enrolled/protected storage directories;
- generation naming and retention;
- durable publication-commit placement;
- authenticated atomic current-pointer publication;
- reconciliation of unreferenced immutable files after crashes;
- observability and bounded operational tooling;
- activation, canary, rollback, operator acceptance and release policy.

Those responsibilities must not be silently moved into a library call that lacks the required authority context.

## 15. Completion and claim boundary

The native crate now has source implementations for:

- immutable V1 registry and lineage;
- V2 manifest validation;
- withdrawal registry and V3 authority-domain/head-bound admission;
- lifecycle journal with historical replay semantics;
- durable withdrawal/lifecycle snapshots;
- pinned candidate loading;
- dataset-driven staged revocation;
- governed iteration and append-only iteration evidence ledger;
- publication plan/transaction/commit contract joining V2 admission to durable state;
- enrolled-root storage path validation and conservative orphan cleanup.

The correct repository claim is therefore **source implemented, product composition/activation not established**. Completion of this source package requires current exact-head and synthetic-merge CI evidence. Product execution, independent semantic acceptance, activation, promotion and release remain separate external gates.

### Work-package status

- `ART-1-LEARNING-ARTIFACT-REGISTRY`: `source_implemented_qualification_pending` until the current exact-head and synthetic-merge candidate are green.
- `ART-2-NEXT-SNAPSHOT-RELOAD-ROLLBACK`: native source primitives implemented; product current-pointer/reload/rollback composition remains host qualification work.
- `HBO-1-OPERATOR-SENSOR-CORE`: remains a separate cross-module/product-composition work package; nothing in this crate claims its activation.

## 16. Related references

- `codex-rs/hepta-learning-artifacts/STORAGE.md`
- `codex-rs/hepta-learning-artifacts/READ_BOUNDARY.md`
- `codex-rs/hepta-learning-artifacts/PINNED_LOAD.md`
- `codex-rs/hepta-learning-artifacts/DATASET_REVOCATION.md`
- `codex-rs/hepta-learning-artifacts/NATIVE_MAPPING.md`
- `qualification/module-execution-dossiers/detail/learning.artifacts.md`
- `docs/lane-e/END_TO_END_LEARNING_SEQUENCE.md`

When these references conflict with the native source, the discrepancy is a documentation defect; do not reinterpret a stale document as implementation authority.
