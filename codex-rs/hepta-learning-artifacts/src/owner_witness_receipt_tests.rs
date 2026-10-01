use super::tests::*;
use super::*;

use pretty_assertions::assert_eq;

use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::LearningArtifactPublishRequestV1;
use crate::test_support::FixtureValue;

#[test]
fn coherent_witness_receipt_metadata_drift_cannot_survive_current_or_terminal_retry() {
    for fault in ["file-digest", "encoded-bytes"] {
        let directory = TestDir::new();
        let key = signer();
        let scope = withdrawal_scope();
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
        let owner = LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, scope.digest()),
            lease(&key, scope.digest()),
            /*now*/ 20,
        )
        .fixture("owner");
        let (registry, mut transaction) =
            deterministic_publication(&owner, &withdrawals, /*now*/ 20);
        owner
            .ensure_payload_durable(&mut transaction, &registry, b"payload", /*now*/ 20)
            .fixture("payload");
        owner
            .ensure_registry_durable(
                &mut transaction,
                &registry,
                &withdrawals,
                digest("binding"),
                /*now*/ 20,
            )
            .fixture("registry");
        let signed = signed_head(&key, scope.digest(), registry.snapshot().head_digest);
        owner
            .ensure_witness_durable(&mut transaction, &signed, &withdrawals, /*now*/ 20)
            .fixture("witness");
        let receipt = owner
            .acknowledge(&mut transaction, &withdrawals, /*now*/ 20)
            .fixture("acknowledge");
        let request = LearningArtifactPublishRequestV1 {
            operation_id: transaction.intent().operation_id.clone(),
            admission: transaction.intent().admission.clone(),
            payload: b"payload".to_vec(),
            signed_current_head: signed.clone(),
            expected_registry_predecessor_head: Digest32::ZERO,
            now: 21,
        };
        let original = transaction.snapshot();
        let mut altered = ArtifactPublicationTransactionV1::begin(
            original.intent.operation_id.clone(),
            original.intent.admission.clone(),
            &withdrawals,
            &ArtifactRegistry::new(),
            Digest32::ZERO,
            /*now*/ 20,
        )
        .fixture("same pure intent");
        altered
            .record_payload_durable(digest("payload"), /*encoded_bytes*/ 7)
            .fixture("same payload phase");
        altered
            .record_registry_durable(
                &registry,
                original.registry_receipt.fixture("registry receipt"),
                &withdrawals,
                /*now*/ 20,
            )
            .fixture("same registry phase");
        let mut witness_receipt = original.witness_receipt.fixture("witness receipt");
        match fault {
            "file-digest" => witness_receipt.file_digest = digest("never-persisted-witness"),
            "encoded-bytes" => witness_receipt.encoded_bytes += 1,
            _ => unreachable!("fixed receipt faults"),
        }
        let requirement = RegistryHeadRequirementV1 {
            registry_id: signed.witness.registry_id.clone(),
            minimum_generation: signed.witness.generation,
            expected_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            now: 20,
        };
        altered
            .record_witness_durable(
                &signed.witness,
                &requirement,
                witness_receipt,
                &withdrawals,
                /*now*/ 20,
            )
            .fixture("generic transaction permits opaque receipt metadata");
        ArtifactPublicationTransactionV1::from_snapshot(altered.snapshot())
            .fixture("coherent altered witness state");
        let witness_checkpoint =
            checkpoint_from_snapshot(&altered.snapshot(), owner.writer_lease_digest());
        let witness_path = owner.checkpoint_path(
            &witness_checkpoint.operation_id,
            ArtifactPublicationPhaseV1::WitnessDurable,
        );
        altered
            .acknowledge(&withdrawals, /*now*/ 20)
            .fixture("coherently rehash terminal state");
        ArtifactPublicationTransactionV1::from_snapshot(altered.snapshot())
            .fixture("coherent altered terminal state");
        let terminal_checkpoint =
            checkpoint_from_snapshot(&altered.snapshot(), owner.writer_lease_digest());
        let terminal_path = owner.checkpoint_path(
            &terminal_checkpoint.operation_id,
            ArtifactPublicationPhaseV1::Acknowledged,
        );
        drop(owner);
        let config = LearningArtifactOwnerServiceConfigV1 {
            root: directory.0.clone(),
            trust: trust(&key, scope.digest()),
            writer_lease: lease(&key, scope.digest()),
            required_current_head: Some(signed),
            withdrawal_registry: withdrawals,
            storage_binding: digest("binding"),
            now: 21,
        };
        let mut service = LearningArtifactOwnerService::open(config.clone()).fixture("service");
        assert_eq!(
            service.publish(request.clone()).fixture("exact retry"),
            receipt
        );
        fs::write(witness_path, encode_checkpoint(&witness_checkpoint))
            .fixture("coherently alter witness checkpoint");
        fs::write(terminal_path, encode_checkpoint(&terminal_checkpoint))
            .fixture("coherently alter terminal checkpoint");
        assert!(service.current_registry_view(21).is_err());
        assert!(service.publish(request.clone()).is_err());
        assert_eq!(service.recovery_required(), Some(&request.operation_id));
        drop(service);
        assert!(LearningArtifactOwnerService::open(config).is_err());
    }
}
