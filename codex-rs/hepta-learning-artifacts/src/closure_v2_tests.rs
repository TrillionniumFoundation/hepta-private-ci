use super::*;

fn id(value: &str) -> StableId {
    match StableId::new(value.to_owned()) {
        Ok(value) => value,
        Err(error) => panic!("invalid test id {value}: {error}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn generation(value: u64) -> Generation {
    match Generation::new(value) {
        Ok(value) => value,
        Err(error) => panic!("invalid test generation {value}: {error}"),
    }
}

fn manifest(dataset: Digest32) -> LearningArtifactManifestV2 {
    LearningArtifactManifestV2 {
        artifact_id: id("artifact-2"),
        kind: ArtifactKind::Model,
        generation: generation(2),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![dataset],
        lineage_digests: vec![digest("evaluation"), digest("support")],
        predecessor_ids: vec![id("artifact-1")],
        rollback_predecessor: Some(id("artifact-1")),
        bytes_digest: digest("artifact-bytes"),
        encoded_size_bytes: 1024,
        training_code_digest: digest("training-code"),
        runtime_tuple_digest: digest("runtime-tuple"),
        device_profile_digest: digest("device-profile"),
        objective_class_digest: digest("objective-class"),
        compatibility_digest: digest("compatibility"),
        schema_profile_digest: digest("schema-profile"),
        normalization_digest: digest("normalization"),
        producer_id: id("producer"),
        created_at: 10,
        expires_at: 100,
    }
}

fn notice(dataset: Digest32) -> DatasetWithdrawalNoticeV1 {
    DatasetWithdrawalNoticeV1 {
        notice_id: id("withdrawal-1"),
        dataset_digest: dataset,
        source_tombstone_digest: digest("source-tombstone"),
        authority_id: id("dataset-owner"),
        credential_chain_digest: digest("withdrawal-credential"),
        signing_key_digest: digest("withdrawal-key"),
        authority_epoch: 9,
        issued_at: 20,
    }
}

#[test]
fn art_01_manifest_v2_normalizes_complete_lineage() {
    let dataset = digest("dataset");
    let mut value = manifest(dataset);
    value.lineage_digests.reverse();
    let validated = match validate_artifact_manifest_v2(value, 50) {
        Ok(validated) => validated,
        Err(error) => panic!("valid V2 manifest failed: {error}"),
    };
    assert_eq!(validated.manifest.source_dataset_digests, vec![dataset]);
    assert!(!validated.manifest_digest.is_zero());
    assert!(!validated.authority.grants_any());
}

#[test]
fn art_02_persistent_withdrawal_blocks_future_admission_and_replays() {
    let dataset = digest("dataset");
    let mut registry = DatasetWithdrawalRegistry::new();
    let first = match registry.append(notice(dataset)) {
        Ok(receipt) => receipt,
        Err(error) => panic!("valid withdrawal failed: {error}"),
    };
    assert_eq!(first.disposition, WithdrawalAppendDispositionV1::Appended);
    assert!(registry.is_withdrawn(dataset));
    assert_eq!(
        registry.admit_manifest(manifest(dataset), 50),
        Err(ArtifactClosureError::WithdrawnDataset)
    );

    let snapshot = registry.snapshot();
    let restored = match DatasetWithdrawalRegistry::from_snapshot(snapshot.clone()) {
        Ok(registry) => registry,
        Err(error) => panic!("withdrawal snapshot replay failed: {error}"),
    };
    assert!(restored.is_withdrawn(dataset));
    assert_eq!(restored.snapshot(), snapshot);
}

#[test]
fn art_03_registry_head_witness_rejects_rollback() {
    let witness = RegistryHeadWitnessV1 {
        registry_id: id("learning-artifacts"),
        generation: generation(4),
        head_digest: digest("head-4"),
        predecessor_head_digest: digest("head-3"),
        authority_epoch: 12,
        signer_id: id("registry-witness"),
        signing_key_digest: digest("registry-key"),
        issued_at: 40,
        expires_at: 60,
    };
    let requirement = RegistryHeadRequirementV1 {
        registry_id: id("learning-artifacts"),
        minimum_generation: generation(4),
        expected_predecessor_head_digest: digest("head-3"),
        minimum_authority_epoch: 12,
        now: 50,
    };
    let receipt = match validate_registry_head_witness(&witness, &requirement) {
        Ok(receipt) => receipt,
        Err(error) => panic!("valid head witness failed: {error}"),
    };
    assert!(!receipt.witness_digest.is_zero());

    let mut stale = witness;
    stale.generation = generation(3);
    assert_eq!(
        validate_registry_head_witness(&stale, &requirement),
        Err(ArtifactClosureError::RegistryGenerationRollback)
    );
}

#[test]
fn art_04_lifecycle_forbids_self_selection_and_state_skips() {
    let producer = id("producer");
    let self_selected = ArtifactLifecycleEventV1 {
        event_id: id("event-select"),
        artifact_id: id("artifact-2"),
        prior_state: ArtifactLifecycleStateV1::OperatorAccepted,
        next_state: ArtifactLifecycleStateV1::Selected,
        actor_id: producer.clone(),
        actor_credential_digest: digest("producer-credential"),
        evidence_digest: digest("selection-evidence"),
        authority_epoch: 3,
        occurred_at: 50,
    };
    assert_eq!(
        validate_artifact_lifecycle_transition(&producer, &self_selected),
        Err(ArtifactClosureError::ProducerSelfDecision)
    );

    let skipped = ArtifactLifecycleEventV1 {
        actor_id: id("independent-selector"),
        prior_state: ArtifactLifecycleStateV1::Evaluated,
        next_state: ArtifactLifecycleStateV1::Selected,
        ..self_selected
    };
    assert_eq!(
        validate_artifact_lifecycle_transition(&producer, &skipped),
        Err(ArtifactClosureError::InvalidLifecycleTransition)
    );
}

#[test]
fn artifact_manifest_rejects_duplicate_lineage_and_missing_rollback_parent() {
    let dataset = digest("dataset");
    let mut duplicate = manifest(dataset);
    duplicate.lineage_digests = vec![digest("same"), digest("same")];
    assert_eq!(
        validate_artifact_manifest_v2(duplicate, 50),
        Err(ArtifactClosureError::DuplicateLineage)
    );

    let mut missing = manifest(dataset);
    missing.rollback_predecessor = Some(id("not-a-parent"));
    assert_eq!(
        validate_artifact_manifest_v2(missing, 50),
        Err(ArtifactClosureError::RollbackPredecessorMissing)
    );
}
