use super::*;
use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalScopeV1;
use crate::LearningArtifactManifestV2;
use crate::ProvenanceModeV1;
use crate::StateChange;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).fixture("valid id")
}
fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn withdrawals() -> DatasetWithdrawalRegistry {
    DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("authority"),
        registry_id: id("datasets"),
        scope_id: id("tenant"),
    })
}
fn admission(
    name: &str,
    generation: u64,
    parents: &[&str],
    expires_at: u64,
) -> WithdrawalBoundArtifactAdmissionV3 {
    let withdrawals = withdrawals();
    admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        LearningArtifactManifestV2 {
            artifact_id: id(name),
            kind: ArtifactKind::Model,
            generation: Generation::new(generation).fixture("generation"),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![digest(name)],
            lineage_digests: vec![digest("lineage")],
            predecessor_ids: parents.iter().map(|name| id(name)).collect(),
            rollback_predecessor: None,
            bytes_digest: digest("payload"),
            encoded_size_bytes: 7,
            training_code_digest: digest("code"),
            runtime_tuple_digest: digest("runtime"),
            device_profile_digest: digest("device"),
            objective_class_digest: digest("objective"),
            compatibility_digest: digest("compatibility"),
            schema_profile_digest: digest("schema"),
            normalization_digest: digest("normalization"),
            producer_id: id("producer"),
            created_at: 10,
            expires_at,
        },
        /*now*/ 20,
    )
    .fixture("admit")
}
fn project(admission: &WithdrawalBoundArtifactAdmissionV3) -> ArtifactManifest {
    let full = &admission.validated_manifest.manifest;
    ArtifactManifest {
        artifact_id: full.artifact_id.clone(),
        kind: full.kind,
        generation: full.generation,
        predecessor_id: if full.predecessor_ids.len() == 1 {
            full.predecessor_ids.first().cloned()
        } else {
            None
        },
        content_digest: full.bytes_digest,
        objective_digest: full.objective_class_digest,
        support_digest: admission.validated_manifest.manifest_digest,
        producer_id: full.producer_id.clone(),
        compatibility_digest: full.compatibility_digest,
        encoded_size_bytes: full.encoded_size_bytes,
    }
}
fn registry(admissions: &[WithdrawalBoundArtifactAdmissionV3]) -> ArtifactRegistry {
    let mut registry = ArtifactRegistry::new();
    for admission in admissions {
        registry
            .append(ArtifactEvent::Register {
                event_id: id(&format!(
                    "register-{}",
                    admission.validated_manifest.manifest.artifact_id
                )),
                manifest: project(admission),
            })
            .fixture("register");
    }
    registry
}
fn join(
    registry: &ArtifactRegistry,
    admissions: &[WithdrawalBoundArtifactAdmissionV3],
    withdrawals: &DatasetWithdrawalRegistry,
    now: u64,
) -> BTreeSet<StableId> {
    eligible_admission_closure(registry, admissions, withdrawals, now).fixture("join full evidence")
}

#[test]
fn all_parents_and_their_expiry_control_derived_eligibility() {
    let admissions = vec![
        admission("a", 1, &[], 30),
        admission("b", 1, &[], 100),
        admission("child", 2, &["a", "b"], 100),
        admission("leaf", 3, &["child"], 100),
    ];
    let registry = registry(&admissions);
    assert_eq!(
        join(&registry, &admissions, &withdrawals(), 20),
        BTreeSet::from([id("a"), id("b"), id("child"), id("leaf")])
    );
    assert_eq!(
        join(&registry, &admissions, &withdrawals(), 31),
        BTreeSet::from([id("b")])
    );
}

#[test]
fn withdrawing_any_parent_source_denies_the_entire_descendant_closure() {
    let admissions = vec![
        admission("a", 1, &[], 100),
        admission("b", 1, &[], 100),
        admission("child", 2, &["a", "b"], 100),
        admission("leaf", 3, &["child"], 100),
    ];
    let registry = registry(&admissions);
    let mut withdrawals = withdrawals();
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("withdraw-b"),
            dataset_digest: digest("b"),
            source_tombstone_digest: digest("tombstone"),
            authority_id: id("authority"),
            credential_chain_digest: digest("credentials"),
            signing_key_digest: digest("key"),
            authority_epoch: 1,
            issued_at: 30,
        })
        .fixture("withdraw");
    assert_eq!(
        join(&registry, &admissions, &withdrawals, 30),
        BTreeSet::from([id("a")])
    );
}

#[test]
fn quarantining_the_unprojected_parent_denies_descendants() {
    let admissions = vec![
        admission("a", 1, &[], 100),
        admission("b", 1, &[], 100),
        admission("child", 2, &["a", "b"], 100),
    ];
    let mut registry = registry(&admissions);
    registry
        .append(ArtifactEvent::Quarantine(StateChange {
            event_id: id("quarantine-b"),
            artifact_id: id("b"),
            evaluator_id: id("evaluator"),
            reason_digest: digest("reason"),
        }))
        .fixture("quarantine");
    assert!(registry.is_eligible(&id("child")));
    assert_eq!(
        join(&registry, &admissions, &withdrawals(), 30),
        BTreeSet::from([id("a")])
    );
}

#[test]
fn missing_duplicate_extra_and_altered_sidecars_are_rejected() {
    let a = admission("a", 1, &[], 100);
    let registry = registry(std::slice::from_ref(&a));
    let withdrawals = withdrawals();
    assert_eq!(
        eligible_admission_closure(&registry, &[], &withdrawals, 20),
        Err(ArtifactAdmissionClosureError::MissingAdmission)
    );
    assert_eq!(
        eligible_admission_closure(&registry, &[a.clone(), a.clone()], &withdrawals, 20),
        Err(ArtifactAdmissionClosureError::DuplicateAdmission)
    );
    assert_eq!(
        eligible_admission_closure(
            &registry,
            &[a.clone(), admission("extra", 1, &[], 100)],
            &withdrawals,
            20
        ),
        Err(ArtifactAdmissionClosureError::ManifestMismatch)
    );
    let mut altered = a;
    altered.validated_manifest.manifest.expires_at += 1;
    assert_eq!(
        eligible_admission_closure(&registry, &[altered], &withdrawals, 20),
        Err(ArtifactAdmissionClosureError::InvalidAdmission)
    );
}

#[test]
fn unknown_future_and_nonadvancing_parents_are_rejected() {
    for admissions in [
        vec![admission("child", 2, &["missing", "also-missing"], 100)],
        vec![
            admission("child", 2, &["a", "b"], 100),
            admission("a", 1, &[], 100),
            admission("b", 1, &[], 100),
        ],
        vec![
            admission("a", 2, &[], 100),
            admission("b", 1, &[], 100),
            admission("child", 2, &["a", "b"], 100),
        ],
    ] {
        assert_eq!(
            eligible_admission_closure(&registry(&admissions), &admissions, &withdrawals(), 20),
            Err(ArtifactAdmissionClosureError::InvalidPredecessor)
        );
    }
}

#[test]
fn cached_full_admission_cannot_downgrade_to_a_compatibility_view() {
    use crate::CreateOnlyArtifactFile;
    use crate::PinnedCandidateLoadError;
    use crate::PinnedCandidateSpec;
    use crate::RevalidatingCandidate;
    use crate::VerifiedCurrentRegistryViewV1;
    use crate::load_pinned_candidate;
    use crate::write_candidate_payload;
    use crate::write_registry_snapshot;
    use std::fs;
    use std::fs::File;

    let directory = std::env::temp_dir().join(format!(
        "hepta-full-admission-downgrade-{}",
        std::process::id()
    ));
    fs::create_dir(&directory).fixture("create fixture");
    let admission = admission("a", 1, &[], 100);
    let registry = registry(std::slice::from_ref(&admission));
    let snapshot = directory.join("snapshot");
    let payload = directory.join("payload");
    let receipt = write_registry_snapshot(
        CreateOnlyArtifactFile::create(&snapshot).fixture("create snapshot"),
        &registry,
        digest("binding"),
    )
    .fixture("write snapshot");
    write_candidate_payload(
        CreateOnlyArtifactFile::create(&payload).fixture("create payload"),
        &registry,
        &id("a"),
        b"payload",
    )
    .fixture("write payload");
    let loaded = load_pinned_candidate(
        File::open(&snapshot).fixture("open snapshot"),
        File::open(&payload).fixture("open payload"),
        PinnedCandidateSpec {
            registry_receipt: receipt,
            manifest: project(&admission),
        },
    )
    .fixture("load");
    let mut cached = RevalidatingCandidate::new(loaded);
    let strict = VerifiedCurrentRegistryViewV1::new(
        receipt,
        registry.clone(),
        digest("witness"),
        digest("trust"),
    )
    .with_admission_closure(vec![admission], &withdrawals(), 20)
    .fixture("strict view");
    cached
        .with_current(strict, |_| ())
        .fixture("consume strict");
    let weak = VerifiedCurrentRegistryViewV1::new(
        receipt,
        registry.clone(),
        digest("witness"),
        digest("trust"),
    );
    assert_eq!(
        cached.with_current(weak, |_| panic!("compatibility view bypassed full closure")),
        Err::<(), _>(PinnedCandidateLoadError::Ineligible)
    );
    let weak =
        VerifiedCurrentRegistryViewV1::new(receipt, registry, digest("witness"), digest("trust"));
    assert_eq!(
        cached.with_current(weak, |_| ()),
        Err(PinnedCandidateLoadError::Unavailable)
    );
    fs::remove_dir_all(directory).fixture("remove fixture");
}
