use super::super::tests::*;
use super::*;

use pretty_assertions::assert_eq;

use crate::CreateOnlyArtifactFile;
use crate::DatasetWithdrawalNoticeV1;
use crate::LearningArtifactManifestV2;
use crate::PinnedCandidateLoadError;
use crate::PinnedCandidateSpec;
use crate::ProvenanceModeV1;
use crate::RevalidatingCandidate;
use crate::VerifiedCurrentRegistryViewV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::load_pinned_candidate;
use crate::test_support::FixtureValue;
use crate::write_candidate_payload;
use crate::write_registry_snapshot;

fn register_manifest(
    owner: &LearningArtifactOwnerHost,
    registry: &mut ArtifactRegistry,
    withdrawals: &DatasetWithdrawalRegistry,
    value: LearningArtifactManifestV2,
    operation: &str,
) -> ArtifactPublicationTransactionV1 {
    let admission = admit_manifest_at_withdrawal_head_v3(
        withdrawals,
        withdrawals.head_digest(),
        value,
        /*now*/ 20,
    )
    .fixture("valid admission");
    let transaction = owner
        .begin_publication(
            id(operation),
            admission,
            withdrawals,
            registry,
            registry.snapshot().head_digest,
            /*now*/ 20,
        )
        .fixture("valid owner publication");
    owner
        .stage_compatibility_registration(&transaction, registry, /*now*/ 20)
        .fixture("valid compatibility registration");
    transaction
}

fn child_of(parent: &str, name: &str, dataset: Digest32) -> LearningArtifactManifestV2 {
    let mut child = manifest();
    child.artifact_id = id(name);
    child.generation = Generation::new(2).fixture("child generation");
    child.predecessor_ids = vec![id(parent)];
    child.rollback_predecessor = Some(id(parent));
    child.source_dataset_digests = vec![dataset];
    child
}

#[test]
fn prepared_checkpoint_recovers_the_complete_durable_admission() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let scope_digest = scope.digest();
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        /*now*/ 20,
    )
    .fixture("owner opens");
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest(),
        /*now*/ 20,
    )
    .fixture("admission");
    let registry = ArtifactRegistry::new();
    let transaction = owner
        .begin_publication(
            id("prepared"),
            admission.clone(),
            &withdrawals,
            &registry,
            Digest32::ZERO,
            /*now*/ 20,
        )
        .fixture("prepared publication");
    let admission_path = directory
        .0
        .join("admissions")
        .join(format!("{}.bin", admission.admission_digest));
    let manifest_path = directory.0.join("admissions").join(format!(
        "{}.manifest",
        admission.validated_manifest.manifest_digest
    ));
    assert_eq!(
        read_artifact_admission_by_digest(
            File::open(&admission_path).fixture("durable admission exists"),
            admission.admission_digest
        )
        .fixture("full admission is preserved"),
        admission
    );
    assert_eq!(
        read_artifact_admission_by_manifest_digest(
            File::open(manifest_path).fixture("manifest index exists"),
            admission.validated_manifest.manifest_digest
        )
        .fixture("manifest index binds full admission"),
        admission
    );
    assert!(
        owner
            .checkpoint_path(&id("prepared"), ArtifactPublicationPhaseV1::Prepared)
            .exists()
    );
    let snapshot = transaction.snapshot();
    drop(owner);
    let reopened = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        /*now*/ 21,
    )
    .fixture("owner restarts");
    let recovery = reopened
        .recover_publication(&id("prepared"))
        .fixture("complete sidecar recovery succeeds")
        .fixture("prepared checkpoint exists");
    assert_eq!(
        recovery.checkpoint.phase,
        ArtifactPublicationPhaseV1::Prepared
    );
    assert_eq!(
        reopened
            .resume_publication(snapshot.clone(), /*now*/ 21)
            .fixture("exact prepared transaction resumes")
            .snapshot(),
        snapshot
    );
}

#[test]
fn missing_or_corrupt_admission_sidecars_fail_checkpoint_recovery() {
    for fault in [
        "missing-admission",
        "missing-manifest-index",
        "corrupt-admission",
    ] {
        let directory = TestDir::new();
        let key = signer();
        let scope = withdrawal_scope();
        let scope_digest = scope.digest();
        let owner = LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, scope_digest),
            lease(&key, scope_digest),
            /*now*/ 20,
        )
        .fixture("owner opens");
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
        let admission = admit_manifest_at_withdrawal_head_v3(
            &withdrawals,
            withdrawals.head_digest(),
            manifest(),
            /*now*/ 20,
        )
        .fixture("admission");
        owner
            .begin_publication(
                id("prepared"),
                admission.clone(),
                &withdrawals,
                &ArtifactRegistry::new(),
                Digest32::ZERO,
                /*now*/ 20,
            )
            .fixture("publication begins");
        let admission_path = directory
            .0
            .join("admissions")
            .join(format!("{}.bin", admission.admission_digest));
        let manifest_path = directory.0.join("admissions").join(format!(
            "{}.manifest",
            admission.validated_manifest.manifest_digest
        ));
        drop(owner);
        match fault {
            "missing-admission" => fs::remove_file(admission_path).fixture("remove admission"),
            "missing-manifest-index" => {
                fs::remove_file(manifest_path).fixture("remove manifest index")
            }
            "corrupt-admission" => {
                fs::write(admission_path, b"corrupt").fixture("corrupt admission")
            }
            _ => unreachable!("fixed fault fixture"),
        }
        let reopened = LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, scope_digest),
            lease(&key, scope_digest),
            /*now*/ 21,
        )
        .fixture("owner restarts");
        assert!(
            reopened.recover_publication(&id("prepared")).is_err(),
            "{fault} must not recover"
        );
    }
}

#[test]
fn dataset_independent_child_cannot_erase_parent_provenance_before_checkpoint() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let scope_digest = scope.digest();
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        /*now*/ 20,
    )
    .fixture("owner opens");
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let mut registry = ArtifactRegistry::new();
    register_manifest(
        &owner,
        &mut registry,
        &withdrawals,
        manifest(),
        "parent-operation",
    );
    let mut child = child_of("candidate", "independent-child", digest("dataset"));
    child.provenance_mode = ProvenanceModeV1::DatasetIndependent;
    child.source_dataset_digests.clear();
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        child,
        /*now*/ 20,
    )
    .fixture("standalone independent manifest is shape-valid");
    let admission_path = directory
        .0
        .join("admissions")
        .join(format!("{}.bin", admission.admission_digest));
    let before = registry.snapshot();
    assert!(matches!(
        owner.begin_publication(
            id("independent-child-operation"),
            admission,
            &withdrawals,
            &registry,
            registry.snapshot().head_digest,
            /*now*/ 20
        ),
        Err(ArtifactOwnerHostError::ProvenanceMismatch)
    ));
    assert_eq!(registry.snapshot(), before);
    assert!(!admission_path.exists());
    assert!(
        !owner
            .checkpoint_path(
                &id("independent-child-operation"),
                ArtifactPublicationPhaseV1::Prepared
            )
            .exists()
    );
    assert_eq!(
        owner
            .recover_publication(&id("independent-child-operation"))
            .fixture("no failed publication recovery"),
        None
    );
}

#[test]
fn current_provenance_excludes_withdrawn_expired_artifacts_and_descendants() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let scope_digest = scope.digest();
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        /*now*/ 20,
    )
    .fixture("owner opens");
    let mut withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let mut registry = ArtifactRegistry::new();
    register_manifest(
        &owner,
        &mut registry,
        &withdrawals,
        manifest(),
        "withdrawn-parent-operation",
    );
    register_manifest(
        &owner,
        &mut registry,
        &withdrawals,
        child_of("candidate", "withdrawn-child", digest("dataset")),
        "withdrawn-child-operation",
    );
    let mut expired = manifest();
    expired.artifact_id = id("expired-parent");
    expired.source_dataset_digests = vec![digest("expiry-dataset")];
    expired.expires_at = 30;
    register_manifest(
        &owner,
        &mut registry,
        &withdrawals,
        expired,
        "expired-parent-operation",
    );
    register_manifest(
        &owner,
        &mut registry,
        &withdrawals,
        child_of("expired-parent", "expired-child", digest("expiry-dataset")),
        "expired-child-operation",
    );
    let mut clean = manifest();
    clean.artifact_id = id("clean");
    clean.source_dataset_digests = vec![digest("clean-dataset")];
    register_manifest(
        &owner,
        &mut registry,
        &withdrawals,
        clean,
        "clean-operation",
    );
    assert!(
        owner
            .current_provenance(&registry, &withdrawals, /*now*/ 20)
            .fixture("valid inherited provenance")
            .ineligible
            .is_empty()
    );
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("withdrawal"),
            dataset_digest: digest("dataset"),
            source_tombstone_digest: digest("tombstone"),
            authority_id: id("dataset-authority"),
            credential_chain_digest: digest("credential"),
            signing_key_digest: digest("key"),
            authority_epoch: 1,
            issued_at: 25,
        })
        .fixture("dataset withdrawal");
    let provenance = owner
        .current_provenance(&registry, &withdrawals, /*now*/ 31)
        .fixture("current exclusions");
    assert_eq!(
        provenance.ineligible,
        BTreeSet::from([
            id("candidate"),
            id("withdrawn-child"),
            id("expired-parent"),
            id("expired-child")
        ])
    );
    let receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(directory.0.join("overlay.snapshot"))
            .fixture("snapshot file"),
        &registry,
        digest("binding"),
    )
    .fixture("registry snapshot");
    write_candidate_payload(
        CreateOnlyArtifactFile::create(directory.0.join("overlay.payload")).fixture("payload file"),
        &registry,
        &id("expired-child"),
        b"payload",
    )
    .fixture("candidate bytes");
    let loaded = load_pinned_candidate(
        File::open(directory.0.join("overlay.snapshot")).fixture("open snapshot"),
        File::open(directory.0.join("overlay.payload")).fixture("open payload"),
        PinnedCandidateSpec {
            registry_receipt: receipt,
            manifest: registry
                .manifest(&id("expired-child"))
                .fixture("registered child")
                .clone(),
        },
    )
    .fixture("historical candidate loads");
    let mut view = VerifiedCurrentRegistryViewV1::new(
        receipt,
        registry.clone(),
        digest("witness"),
        digest("trust"),
    );
    view.restrict_eligibility(provenance.ineligible);
    view.bind_source_datasets(provenance.source_datasets);
    assert!(view.is_eligible(&id("clean")));
    assert!(!view.is_eligible(&id("expired-child")));
    let clean_manifest = registry.manifest(&id("clean")).fixture("clean manifest");
    assert!(view.supports_dataset(clean_manifest, digest("clean-dataset")));
    assert!(!view.supports_dataset(clean_manifest, clean_manifest.support_digest));
    assert!(
        !view.supports_dataset(
            registry
                .manifest(&id("withdrawn-child"))
                .fixture("withdrawn child"),
            digest("dataset"),
        )
    );
    let consumed = std::cell::Cell::new(false);
    let mut cached = RevalidatingCandidate::new(loaded);
    assert_eq!(
        cached.with_current(view, |_| consumed.set(true)),
        Err(PinnedCandidateLoadError::Ineligible)
    );
    assert!(!consumed.get());
}
