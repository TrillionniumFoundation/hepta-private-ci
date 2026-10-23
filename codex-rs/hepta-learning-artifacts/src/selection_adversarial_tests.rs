use super::tests::current_view;
use super::tests::id;
use super::tests::manifest;
use super::tests::must;
use super::tests::owner_trust;
use super::tests::signed_selection;
use super::tests::trust;
use super::*;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

#[test]
fn verified_selection_preserves_selector_expiry_and_revocation_boundaries() {
    let key = SigningKey::from_bytes(&[44; 32]);
    let owner_key = SigningKey::from_bytes(&[13; 32]);
    let owner_trust = owner_trust(&owner_key);
    let producer = id("producer");
    let manifest = manifest(producer.clone());
    let current = current_view(&manifest, &owner_trust);
    for revoked_at in [None, Some(40)] {
        let mut trust = trust(&key, id("selector"));
        trust.selectors[0].expires_at = 40;
        trust.selectors[0].revoked_at = revoked_at;
        let verifier = must(ArtifactSelectionVerifierV1::new(trust, &owner_trust));
        let signed = signed_selection(&key, id("selector"), &manifest, &current);
        let verified = must(verifier.verify(&signed, &current, 30));
        let mut journal = ArtifactLifecycleJournalV2::new();
        assert!(matches!(
            record_verified_selection(
                &mut journal,
                Digest32::ZERO,
                &producer,
                &verified,
                id("selection-event"),
                if revoked_at.is_some() { 40 } else { 41 },
            ),
            Err(ArtifactSelectionError::SelectionContext)
        ));
        assert!(journal.records().is_empty());
    }
}

#[test]
fn verified_selection_cannot_be_recorded_with_a_substitute_producer() {
    let key = SigningKey::from_bytes(&[45; 32]);
    let owner_key = SigningKey::from_bytes(&[13; 32]);
    let owner_trust = owner_trust(&owner_key);
    let manifest = manifest(id("producer"));
    let current = current_view(&manifest, &owner_trust);
    let verifier = must(ArtifactSelectionVerifierV1::new(
        trust(&key, id("selector")),
        &owner_trust,
    ));
    let signed = signed_selection(&key, id("selector"), &manifest, &current);
    let verified = must(verifier.verify(&signed, &current, 30));
    let mut journal = ArtifactLifecycleJournalV2::new();
    assert!(matches!(
        record_verified_selection(
            &mut journal,
            Digest32::ZERO,
            &id("substitute-producer"),
            &verified,
            id("selection-event"),
            30,
        ),
        Err(ArtifactSelectionError::ManifestMismatch)
    ));
}

#[test]
fn selected_loader_preserves_its_verified_owner_trust_before_first_use() {
    use crate::ArtifactEvent;
    use crate::ArtifactRegistry;
    use crate::CreateOnlyArtifactFile;
    use crate::DatasetWithdrawalRegistry;
    use crate::DatasetWithdrawalScopeV1;
    use crate::LearningArtifactManifestV2;
    use crate::ProvenanceModeV1;
    use crate::admit_manifest_at_withdrawal_head_v3;
    use crate::write_candidate_payload;
    use crate::write_registry_snapshot;
    use ed25519_dalek::Signer;

    let key = SigningKey::from_bytes(&[46; 32]);
    let owner_key = SigningKey::from_bytes(&[13; 32]);
    let mut owner_trust = owner_trust(&owner_key);
    let mut manifest = manifest(id("producer"));
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"),
        registry_id: id("withdrawals"),
        scope_id: id("scope"),
    });
    owner_trust.withdrawal_scope_digest = must(withdrawals.scope_digest().ok_or("scope"));
    let owner_verifier = must(ArtifactOwnerVerifierV1::new(owner_trust.clone()));
    let full = LearningArtifactManifestV2 {
        artifact_id: manifest.artifact_id.clone(),
        kind: manifest.kind,
        generation: manifest.generation,
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![manifest.support_digest],
        lineage_digests: vec![Digest32::of_bytes(b"lineage")],
        predecessor_ids: Vec::new(),
        rollback_predecessor: None,
        bytes_digest: manifest.content_digest,
        encoded_size_bytes: manifest.encoded_size_bytes,
        training_code_digest: Digest32::of_bytes(b"code"),
        runtime_tuple_digest: Digest32::of_bytes(b"runtime"),
        device_profile_digest: Digest32::of_bytes(b"device"),
        objective_class_digest: manifest.objective_digest,
        compatibility_digest: manifest.compatibility_digest,
        schema_profile_digest: Digest32::of_bytes(b"schema"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
        producer_id: manifest.producer_id.clone(),
        created_at: 10,
        expires_at: 100,
    };
    let admission = must(admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        full,
        20,
    ));
    manifest.support_digest = admission.validated_manifest.manifest_digest;
    let mut registry = ArtifactRegistry::new();
    must(registry.append(ArtifactEvent::Register {
        event_id: id("register"),
        manifest: manifest.clone(),
    }));
    let directory = std::env::temp_dir().join(format!(
        "hepta-selected-trust-substitution-{}",
        std::process::id()
    ));
    must(std::fs::create_dir(&directory));
    let snapshot_path = directory.join("snapshot");
    let payload_path = directory.join("payload");
    let receipt = must(write_registry_snapshot(
        must(CreateOnlyArtifactFile::create(&snapshot_path)),
        &registry,
        Digest32::of_bytes(b"binding"),
    ));
    must(write_candidate_payload(
        must(CreateOnlyArtifactFile::create(&payload_path)),
        &registry,
        &manifest.artifact_id,
        b"payload",
    ));
    let current = must(
        VerifiedCurrentRegistryViewV1::new(
            receipt,
            registry.clone(),
            Digest32::of_bytes(b"witness"),
            owner_verifier.trust_digest(),
        )
        .with_admission_closure(vec![admission], &withdrawals, 30),
    );
    let mut selector_trust = trust(&key, id("selector"));
    selector_trust.withdrawal_scope_digest = owner_trust.withdrawal_scope_digest;
    let verifier = must(ArtifactSelectionVerifierV1::new(
        selector_trust,
        &owner_trust,
    ));
    let mut signed = signed_selection(&key, id("selector"), &manifest, &current);
    signed.withdrawal_scope_digest = owner_trust.withdrawal_scope_digest;
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    assert!(matches!(
        verifier.verify(&signed, &current, 31),
        Err(ArtifactSelectionError::CurrentHeadMismatch)
    ));
    let selection = must(verifier.verify(&signed, &current, 30));
    let mut journal = ArtifactLifecycleJournalV2::new();
    assert!(matches!(
        record_verified_selection(
            &mut journal,
            Digest32::ZERO,
            &manifest.producer_id,
            &selection,
            id("stale-selection-event"),
            31,
        ),
        Err(ArtifactSelectionError::SelectionContext)
    ));
    let mut cached = must(load_selected_candidate(
        must(File::open(snapshot_path)),
        must(File::open(payload_path)),
        selection,
    ));
    let foreign = VerifiedCurrentRegistryViewV1::new(
        receipt,
        registry,
        Digest32::of_bytes(b"foreign-witness"),
        Digest32::of_bytes(b"foreign-owner-trust"),
    );
    assert_eq!(
        cached.with_current(foreign, |_| panic!(
            "foreign owner reached selected consumer"
        )),
        Err::<(), _>(PinnedCandidateLoadError::FrontierMismatch)
    );
    let selection = must(verifier.verify(&signed, &current, 30));
    let mut cached = must(load_selected_candidate(
        must(File::open(directory.join("snapshot"))),
        must(File::open(directory.join("payload"))),
        selection,
    ));
    let weak = VerifiedCurrentRegistryViewV1::new(
        receipt,
        current.registry().clone(),
        current.witness_digest(),
        owner_verifier.trust_digest(),
    );
    assert!(
        cached
            .with_current(weak, |_| panic!("legacy view stripped selected V2 closure"))
            .is_err()
    );
    must(std::fs::remove_dir_all(directory));
}
