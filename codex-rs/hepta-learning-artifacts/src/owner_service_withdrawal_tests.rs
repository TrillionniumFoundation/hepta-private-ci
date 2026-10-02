use super::tests::*;
use super::*;
use crate::ArtifactState;
use crate::DatasetRevocationError;
use crate::DatasetRevocationRequest;
use crate::DatasetWithdrawalNoticeV1;
use crate::LearningArtifactManifestV2;
use crate::ProvenanceModeV1;
use crate::RegistryHeadWitnessV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::prepare_dataset_revocation;
use crate::test_support::FixtureValue;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

fn publication(
    service: &LearningArtifactOwnerService,
    key: &SigningKey,
    operation: &str,
    manifest: LearningArtifactManifestV2,
    changes: &[ArtifactEvent],
) -> LearningArtifactPublishRequestV1 {
    let admission = admit_manifest_at_withdrawal_head_v3(
        service.withdrawal_registry(),
        service.withdrawal_registry().head_digest(),
        manifest,
        /*now*/ 20,
    )
    .fixture("current actual admission");
    let preview = service
        .preview_publication_with_state_changes(id(operation), admission.clone(), changes, 20)
        .fixture("complete exact head preview");
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: service
            .withdrawal_registry()
            .scope_digest()
            .fixture("scope"),
        binding: digest("binding"),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("learning-artifacts"),
            generation: preview.generation,
            head_digest: preview.head_digest,
            predecessor_head_digest: preview.predecessor,
            authority_epoch: 1,
            signer_id: id("owner-authority"),
            signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
            issued_at: 20,
            expires_at: 1_000,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    LearningArtifactPublishRequestV1 {
        operation_id: id(operation),
        admission,
        payload: b"payload".to_vec(),
        signed_current_head: signed,
        expected_registry_predecessor_head: preview.predecessor,
        now: 20,
    }
}

#[test]
fn v2_membership_full_suffix_preview_and_partial_withdrawal_keep_delivery_closed() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let mut config = LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, withdrawals.scope_digest().fixture("scope")),
        writer_lease: lease(&key, withdrawals.scope_digest().fixture("scope")),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    };
    let mut service = LearningArtifactOwnerService::open(config.clone()).fixture("sole writer");
    let source = publication(&service, &key, "source", manifest(), &[]);
    service.publish(source).fixture("real source ACK");
    let mut derived = manifest();
    derived.artifact_id = id("derived");
    derived.generation = Generation::new(2).fixture("derived generation");
    derived.predecessor_ids = vec![id("candidate")];
    let child = publication(&service, &key, "derived", derived, &[]);
    service.publish(child.clone()).fixture("real child ACK");
    let original_records = service.registry().records().to_vec();
    let notice = DatasetRevocationRequest {
        operation_id: id("withdraw-original-dataset"),
        dataset_digest: digest("dataset"),
        source_revocation_digest: digest("fixture-authenticated-source-unlearning"),
        evaluator_id: id("independent-withdrawal-authority"),
    };
    assert!(matches!(
        prepare_dataset_revocation(
            service.registry(),
            service.registry().head_digest(),
            &notice
        ),
        Err(DatasetRevocationError::NoMatchingArtifacts)
    ));
    let prepared = service
        .prepare_dataset_revocation_from_current(&notice, 20)
        .fixture("exact complete V2 dataset membership");
    assert_eq!(
        prepared.summary().direct_artifacts,
        vec![id("candidate"), id("derived")]
    );
    assert_eq!(service.registry().records(), original_records.as_slice());
    assert!(!prepared.summary().authority.grants_any());
    let changes: Vec<_> = prepared.registry().records()[original_records.len()..]
        .iter()
        .map(|record| record.event.clone())
        .collect();
    let mut next_withdrawals = withdrawals;
    next_withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: notice.operation_id.clone(),
            dataset_digest: notice.dataset_digest,
            source_tombstone_digest: notice.source_revocation_digest,
            authority_id: notice.evaluator_id.clone(),
            credential_chain_digest: digest("fixture-admitted-independent-credential"),
            signing_key_digest: digest("fixture-admitted-independent-key"),
            authority_epoch: 1,
            issued_at: 20,
        })
        .fixture("already authenticated host notice");
    service
        .install_withdrawal_frontier(next_withdrawals.clone())
        .fixture("monotonic withdrawal fence");
    let before_ack = service
        .current_registry_view(20)
        .fixture("partial fail-closed current");
    assert!(!before_ack.is_eligible(&id("candidate")));
    assert!(!before_ack.is_eligible(&id("derived")));
    assert_eq!(service.registry().records(), original_records.as_slice());

    let mut clean = manifest();
    clean.artifact_id = id("actual-clean-replacement");
    clean.provenance_mode = ProvenanceModeV1::DatasetIndependent;
    clean.source_dataset_digests.clear();
    let request = publication(
        &service,
        &key,
        "clean-replacement-and-withdrawal",
        clean,
        &changes,
    );
    assert_eq!(
        service
            .publication_status(&request)
            .fixture("preview is read-only"),
        None
    );
    let registration_only = service
        .preview_registered_head(request.operation_id.clone(), request.admission.clone(), 20)
        .fixture("old registration preview");
    assert_ne!(
        registration_only.head_digest,
        request.signed_current_head.witness.head_digest
    );
    let mut damaged = request.clone();
    damaged.payload[0] ^= 1;
    assert!(
        service
            .publish_with_state_changes(damaged, &changes)
            .is_err()
    );
    assert_eq!(service.registry().records(), original_records.as_slice());
    assert!(
        !service
            .current_registry_view(20)
            .fixture("failed write keeps withdrawal")
            .is_eligible(&id("candidate"))
    );
    drop(service);
    config.required_current_head = Some(child.signed_current_head);
    config.withdrawal_registry = next_withdrawals.clone();
    let mut service = LearningArtifactOwnerService::open(config.clone())
        .fixture("cold partial recovery from original notice");
    let partial = service
        .current_registry_view(20)
        .fixture("cold partial delivery fence");
    assert!(!partial.is_eligible(&id("candidate")));
    assert!(!partial.is_eligible(&id("derived")));
    let resumed_plan = service
        .prepare_dataset_revocation_from_current(&notice, 20)
        .fixture("cold withdrawn membership remains provenance, never delivery");
    assert_eq!(
        resumed_plan.registry().records(),
        prepared.registry().records()
    );
    let receipt = service
        .publish_with_state_changes(request.clone(), &changes)
        .fixture("original full suffix ACK");
    assert_eq!(
        service.registry().state(&id("candidate")),
        Some(ArtifactState::Revoked)
    );
    assert_eq!(
        service.registry().state(&id("derived")),
        Some(ArtifactState::Revoked)
    );
    let current = service
        .current_registry_view(20)
        .fixture("fully acknowledged current");
    assert!(!current.is_eligible(&id("candidate")));
    assert!(!current.is_eligible(&id("derived")));
    assert!(current.is_eligible(&id("actual-clean-replacement")));
    assert_eq!(
        service
            .publish_with_state_changes(request.clone(), &changes)
            .fixture("exact ACK retry"),
        receipt
    );
    assert!(service.publish(request.clone()).is_err());
    drop(service);
    config.required_current_head = Some(request.signed_current_head.clone());
    config.withdrawal_registry = next_withdrawals;
    let mut reopened =
        LearningArtifactOwnerService::open(config).fixture("original owner cold reopen");
    assert_eq!(
        reopened
            .publish_with_state_changes(request, &changes)
            .fixture("cold exact ACK"),
        receipt
    );
    let current = reopened.current_registry_view(20).fixture("cold current");
    assert!(!current.is_eligible(&id("candidate")));
    assert!(!current.is_eligible(&id("derived")));
}
