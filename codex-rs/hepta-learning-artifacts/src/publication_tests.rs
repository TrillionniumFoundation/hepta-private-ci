use super::*;

use codex_hepta_types::Generation;

use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalScopeV1;
use crate::LearningArtifactManifestV2;
use crate::ProvenanceModeV1;
use crate::admit_manifest_at_withdrawal_head_v3;

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
        Err(error) => panic!("invalid generation {value}: {error}"),
    }
}

fn withdrawal_registry() -> DatasetWithdrawalRegistry {
    DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"),
        registry_id: id("withdrawal-registry"),
        scope_id: id("tenant-a"),
    })
}

fn v2_manifest() -> LearningArtifactManifestV2 {
    LearningArtifactManifestV2 {
        artifact_id: id("artifact-v2"),
        kind: ArtifactKind::Model,
        generation: generation(2),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![digest("dataset-a"), digest("dataset-b")],
        lineage_digests: vec![digest("lineage-a"), digest("lineage-b")],
        predecessor_ids: vec![id("artifact-parent-a"), id("artifact-parent-b")],
        rollback_predecessor: Some(id("artifact-parent-a")),
        bytes_digest: digest("payload"),
        encoded_size_bytes: 7,
        training_code_digest: digest("training"),
        runtime_tuple_digest: digest("runtime"),
        device_profile_digest: digest("device"),
        objective_class_digest: digest("objective"),
        compatibility_digest: digest("compatibility"),
        schema_profile_digest: digest("schema"),
        normalization_digest: digest("normalization"),
        producer_id: id("producer"),
        created_at: 10,
        expires_at: 100,
    }
}

fn registry_with_candidate(predecessor_head: Digest32) -> ArtifactRegistry {
    let mut registry = ArtifactRegistry::new();
    if !predecessor_head.is_zero() {
        panic!("fixture only supports genesis registry publication");
    }
    let event = ArtifactEvent::Register {
        event_id: id("register-v2"),
        manifest: ArtifactManifest {
            artifact_id: id("artifact-v2"),
            kind: ArtifactKind::Model,
            generation: generation(2),
            predecessor_id: None,
            content_digest: digest("payload"),
            objective_digest: digest("objective-index"),
            support_digest: digest("support-index"),
            producer_id: id("producer"),
            compatibility_digest: digest("compatibility"),
            encoded_size_bytes: 7,
        },
    };
    if let Err(error) = registry.append(event) {
        panic!("registry fixture append failed: {error}");
    }
    registry
}

fn snapshot_receipt(registry: &ArtifactRegistry) -> RegistrySnapshotReceipt {
    RegistrySnapshotReceipt {
        binding: digest("publication-scope"),
        head_digest: registry.head_digest(),
        file_digest: digest("registry-file"),
        records: registry.records().len(),
        encoded_bytes: 128,
    }
}

fn head_witness(registry: &ArtifactRegistry) -> RegistryHeadWitnessV1 {
    RegistryHeadWitnessV1 {
        registry_id: id("artifact-registry"),
        generation: generation(2),
        head_digest: registry.head_digest(),
        predecessor_head_digest: Digest32::ZERO,
        authority_epoch: 5,
        signer_id: id("registry-signer"),
        signing_key_digest: digest("registry-key"),
        issued_at: 20,
        expires_at: 100,
    }
}

fn head_requirement() -> RegistryHeadRequirementV1 {
    RegistryHeadRequirementV1 {
        registry_id: id("artifact-registry"),
        minimum_generation: generation(2),
        expected_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 5,
        now: 20,
    }
}

fn witness_receipt(witness: &RegistryHeadWitnessV1) -> RegistryHeadWitnessReceipt {
    let validated = match validate_registry_head_witness(witness, &head_requirement()) {
        Ok(value) => value,
        Err(error) => panic!("valid witness fixture failed: {error}"),
    };
    RegistryHeadWitnessReceipt {
        binding: digest("publication-scope"),
        witness_digest: validated.witness_digest,
        file_digest: digest("witness-file"),
        encoded_bytes: 128,
    }
}

fn prepared() -> ArtifactPublicationTransactionV1 {
    let withdrawal = withdrawal_registry();
    let admission = match admit_manifest_at_withdrawal_head_v3(
        &withdrawal,
        withdrawal.head_digest(),
        v2_manifest(),
        20,
    ) {
        Ok(value) => value,
        Err(error) => panic!("valid admission fixture failed: {error}"),
    };
    let registry = ArtifactRegistry::new();
    match ArtifactPublicationTransactionV1::begin(
        id("publication-op"),
        admission,
        &withdrawal,
        &registry,
        Digest32::ZERO,
        20,
    ) {
        Ok(value) => value,
        Err(error) => panic!("publication preparation failed: {error}"),
    }
}

#[test]
fn art_07_publication_requires_ordered_durable_phases_before_ack() {
    let mut transaction = prepared();
    assert_eq!(
        transaction.acknowledge(&withdrawal_registry(), 20),
        Err(ArtifactPublicationError::InvalidPhase)
    );
    if let Err(error) = transaction.record_payload_durable(digest("payload"), 7) {
        panic!("payload durability failed: {error}");
    }
    assert_eq!(
        transaction.acknowledge(&withdrawal_registry(), 20),
        Err(ArtifactPublicationError::InvalidPhase)
    );

    let registry = registry_with_candidate(Digest32::ZERO);
    let registry_receipt = snapshot_receipt(&registry);
    if let Err(error) = transaction.record_registry_durable(
        &registry,
        registry_receipt,
        &withdrawal_registry(),
        20,
    ) {
        panic!("registry durability failed: {error}");
    }
    assert_eq!(
        transaction.acknowledge(&withdrawal_registry(), 20),
        Err(ArtifactPublicationError::InvalidPhase)
    );

    let witness = head_witness(&registry);
    if let Err(error) = transaction.record_witness_durable(
        &witness,
        &head_requirement(),
        witness_receipt(&witness),
        &withdrawal_registry(),
        20,
    ) {
        panic!("witness durability failed: {error}");
    }
    let receipt = match transaction.acknowledge(&withdrawal_registry(), 21) {
        Ok(value) => value,
        Err(error) => panic!("acknowledgement failed: {error}"),
    };
    assert_eq!(
        transaction.phase(),
        ArtifactPublicationPhaseV1::Acknowledged
    );
    assert!(!receipt.authority.grants_any());
    let status = transaction.status();
    assert_eq!(status.phase, ArtifactPublicationPhaseV1::Acknowledged);
    assert_eq!(
        status.registry_head_digest,
        Some(receipt.registry_head_digest)
    );
    assert_eq!(status.witness_digest, Some(receipt.witness_digest));
    assert!(!status.authority.grants_any());
}

#[test]
fn art_07_crash_snapshots_never_promote_partial_publication() {
    let mut transaction = prepared();
    let prepared = match ArtifactPublicationTransactionV1::from_snapshot(transaction.snapshot())
    {
        Ok(value) => value,
        Err(error) => panic!("prepared recovery failed: {error}"),
    };
    assert_eq!(prepared.phase(), ArtifactPublicationPhaseV1::Prepared);

    if let Err(error) = transaction.record_payload_durable(digest("payload"), 7) {
        panic!("payload durability failed: {error}");
    }
    let mut recovered =
        match ArtifactPublicationTransactionV1::from_snapshot(transaction.snapshot()) {
            Ok(value) => value,
            Err(error) => panic!("payload recovery failed: {error}"),
        };
    assert_eq!(
        recovered.acknowledge(&withdrawal_registry(), 20),
        Err(ArtifactPublicationError::InvalidPhase)
    );

    let registry = registry_with_candidate(Digest32::ZERO);
    if let Err(error) = transaction.record_registry_durable(
        &registry,
        snapshot_receipt(&registry),
        &withdrawal_registry(),
        20,
    ) {
        panic!("registry durability failed: {error}");
    }
    let mut recovered =
        match ArtifactPublicationTransactionV1::from_snapshot(transaction.snapshot()) {
            Ok(value) => value,
            Err(error) => panic!("registry recovery failed: {error}"),
        };
    assert_eq!(
        recovered.acknowledge(&withdrawal_registry(), 20),
        Err(ArtifactPublicationError::InvalidPhase)
    );

    let witness = head_witness(&registry);
    if let Err(error) = transaction.record_witness_durable(
        &witness,
        &head_requirement(),
        witness_receipt(&witness),
        &withdrawal_registry(),
        20,
    ) {
        panic!("witness durability failed: {error}");
    }
    let mut recovered =
        match ArtifactPublicationTransactionV1::from_snapshot(transaction.snapshot()) {
            Ok(value) => value,
            Err(error) => panic!("witness recovery failed: {error}"),
        };
    assert!(recovered.acknowledge(&withdrawal_registry(), 21).is_ok());
}

#[test]
fn art_07_withdrawal_advance_blocks_recovered_publication() {
    let mut transaction = prepared();
    if let Err(error) = transaction.record_payload_durable(digest("payload"), 7) {
        panic!("payload durability failed: {error}");
    }

    let registry = registry_with_candidate(Digest32::ZERO);
    let mut withdrawal = withdrawal_registry();
    if let Err(error) = withdrawal.append(DatasetWithdrawalNoticeV1 {
        notice_id: id("withdraw-after-admission"),
        dataset_digest: digest("dataset-a"),
        source_tombstone_digest: digest("dataset-a-tombstone"),
        authority_id: id("dataset-authority"),
        credential_chain_digest: digest("withdrawal-credential"),
        signing_key_digest: digest("withdrawal-key"),
        authority_epoch: 2,
        issued_at: 21,
    }) {
        panic!("withdrawal fixture failed: {error}");
    }

    assert!(matches!(
        transaction.record_registry_durable(
            &registry,
            snapshot_receipt(&registry),
            &withdrawal,
            21,
        ),
        Err(ArtifactPublicationError::Admission(
            ArtifactAdmissionError::WithdrawalHeadChanged
        ))
    ));
    assert_eq!(
        transaction.phase(),
        ArtifactPublicationPhaseV1::PayloadDurable
    );
}

#[test]
fn art_07_registry_projection_cannot_swap_payload_or_identity() {
    let mut transaction = prepared();
    if let Err(error) = transaction.record_payload_durable(digest("payload"), 7) {
        panic!("payload durability failed: {error}");
    }
    let mut registry = ArtifactRegistry::new();
    if let Err(error) = registry.append(ArtifactEvent::Register {
        event_id: id("register-wrong"),
        manifest: ArtifactManifest {
            artifact_id: id("artifact-v2"),
            kind: ArtifactKind::Model,
            generation: generation(2),
            predecessor_id: None,
            content_digest: digest("wrong-payload"),
            objective_digest: digest("objective-index"),
            support_digest: digest("support-index"),
            producer_id: id("producer"),
            compatibility_digest: digest("compatibility"),
            encoded_size_bytes: 7,
        },
    }) {
        panic!("wrong registry fixture append failed: {error}");
    }
    assert_eq!(
        transaction.record_registry_durable(
            &registry,
            snapshot_receipt(&registry),
            &withdrawal_registry(),
            20,
        ),
        Err(ArtifactPublicationError::RegistryProjectionMismatch)
    );
}
