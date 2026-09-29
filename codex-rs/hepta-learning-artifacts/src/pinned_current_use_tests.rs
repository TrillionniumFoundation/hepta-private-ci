use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

use super::*;
use crate::ArtifactEvent;
use crate::ArtifactKind;
use crate::DatasetWithdrawalRegistry;
use crate::DatasetWithdrawalScopeV1;
use crate::LearningArtifactManifestV2;
use crate::ProvenanceModeV1;
use crate::VerifiedCurrentArtifactUseV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).fixture("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn scope() -> DatasetWithdrawalScopeV1 {
    DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"),
        registry_id: id("withdrawals"),
        scope_id: id("scope"),
    }
}

fn manifest(training_code: &str) -> LearningArtifactManifestV2 {
    LearningArtifactManifestV2 {
        artifact_id: id("candidate"),
        kind: ArtifactKind::Policy,
        generation: Generation::new(1).fixture("generation"),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![digest("dataset")],
        lineage_digests: vec![digest("lineage")],
        predecessor_ids: Vec::new(),
        rollback_predecessor: None,
        bytes_digest: digest("payload"),
        encoded_size_bytes: 7,
        training_code_digest: digest(training_code),
        runtime_tuple_digest: digest("runtime"),
        device_profile_digest: digest("device"),
        objective_class_digest: digest("objective"),
        compatibility_digest: digest("compatibility"),
        schema_profile_digest: digest("schema"),
        normalization_digest: digest("normalization"),
        producer_id: id("trainer"),
        created_at: 10,
        expires_at: 1_000,
    }
}

fn fixture(
    training_code: &str,
) -> (
    WithdrawalBoundArtifactAdmissionV3,
    ArtifactRegistry,
    RegistrySnapshotReceipt,
    ArtifactManifest,
) {
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest(training_code),
        20,
    )
    .fixture("admission");
    let v2 = &admission.validated_manifest;
    let selected = ArtifactManifest {
        artifact_id: v2.manifest.artifact_id.clone(),
        kind: v2.manifest.kind,
        generation: v2.manifest.generation,
        predecessor_id: None,
        content_digest: v2.manifest.bytes_digest,
        objective_digest: v2.manifest.objective_class_digest,
        support_digest: v2.manifest_digest,
        producer_id: v2.manifest.producer_id.clone(),
        compatibility_digest: v2.manifest.compatibility_digest,
        encoded_size_bytes: v2.manifest.encoded_size_bytes,
    };
    let mut registry = ArtifactRegistry::new();
    registry
        .append(ArtifactEvent::Register {
            event_id: id("register"),
            manifest: selected.clone(),
        })
        .fixture("registry append");
    let receipt = RegistrySnapshotReceipt {
        binding: digest("binding"),
        head_digest: registry.snapshot().head_digest,
        file_digest: digest("file"),
        records: registry.records().len(),
        encoded_bytes: 1,
    };
    (admission, registry, receipt, selected)
}

fn loaded(receipt: RegistrySnapshotReceipt, selected: ArtifactManifest) -> LoadedPinnedCandidate {
    LoadedPinnedCandidate {
        spec: PinnedCandidateSpec {
            registry_receipt: receipt,
            manifest: selected,
        },
        bytes: b"payload".to_vec(),
    }
}

#[test]
fn final_use_view_allows_exact_complete_admission() {
    let (admission, registry, receipt, selected) = fixture("code-v1");
    let current = VerifiedCurrentRegistryViewV1::new(
        receipt,
        registry,
        digest("witness"),
        digest("trust"),
    );
    let current_use = VerifiedCurrentArtifactUseV1::new(current, admission);
    let mut candidate = RevalidatingCandidate::new(loaded(receipt, selected));
    assert_eq!(
        candidate
            .with_current_use(current_use, <[u8]>::to_vec)
            .fixture("final use"),
        b"payload"
    );
}

#[test]
fn substituted_complete_admission_closes_the_cached_consumer() {
    let (_original, registry, receipt, selected) = fixture("code-v1");
    let (substituted, _, _, _) = fixture("code-v2");
    let current = VerifiedCurrentRegistryViewV1::new(
        receipt,
        registry,
        digest("witness"),
        digest("trust"),
    );
    let current_use = VerifiedCurrentArtifactUseV1::new(current, substituted);
    let mut candidate = RevalidatingCandidate::new(loaded(receipt, selected));
    assert_eq!(
        candidate.with_current_use(current_use, |_| panic!("substituted admission consumed")),
        Err::<(), _>(PinnedCandidateLoadError::PinMismatch)
    );
    assert_eq!(
        candidate.with_verified_registry(
            receipt,
            ArtifactRegistry::new(),
            |_| panic!("closed consumer revived")
        ),
        Err::<(), _>(PinnedCandidateLoadError::Unavailable)
    );
}
