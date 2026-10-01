use super::tests::*;
use super::*;

use crate::ArtifactEvent;

use crate::ArtifactKind;
use crate::ArtifactManifest;
use crate::test_support::FixtureValue;
use pretty_assertions::assert_eq;

#[test]
fn raw_transaction_and_snapshot_recovery_reject_multiple_predecessors() {
    let withdrawals = withdrawal_registry();
    let mut manifest = v2_manifest();
    manifest.predecessor_ids = vec![id("parent-a"), id("parent-b")];
    let admission = crate::admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest,
        20,
    )
    .fixture("admission retains V2 multi-parent representation");
    assert!(matches!(
        ArtifactPublicationTransactionV1::begin(
            id("operation"),
            admission.clone(),
            &withdrawals,
            &ArtifactRegistry::new(),
            Digest32::ZERO,
            20
        ),
        Err(ArtifactPublicationError::UnsupportedMultiPredecessorLineage)
    ));
    let mut snapshot = prepared().snapshot();
    snapshot.intent.admission = admission;
    snapshot.intent.intent_digest = digest_intent(
        &snapshot.intent.operation_id,
        &snapshot.intent.admission,
        snapshot.intent.expected_registry_predecessor_head,
    );
    snapshot.state_digest = digest_state(&snapshot.intent, snapshot.phase, None, None, None);
    assert!(matches!(
        ArtifactPublicationTransactionV1::from_snapshot(snapshot),
        Err(ArtifactPublicationError::UnsupportedMultiPredecessorLineage)
    ));
}

#[test]
fn registry_projection_binds_objective_and_complete_manifest_support() {
    for altered_field in ["objective", "support"] {
        let mut transaction = prepared();
        transaction
            .record_payload_durable(digest("payload"), 7)
            .fixture("payload");
        let mut projection = ArtifactManifest {
            artifact_id: id("artifact-v2"),
            kind: ArtifactKind::Model,
            generation: generation(2),
            predecessor_id: None,
            content_digest: digest("payload"),
            objective_digest: digest("objective"),
            support_digest: transaction
                .intent()
                .admission
                .validated_manifest
                .manifest_digest,
            producer_id: id("producer"),
            compatibility_digest: digest("compatibility"),
            encoded_size_bytes: 7,
        };
        match altered_field {
            "objective" => projection.objective_digest = digest("different-objective"),
            "support" => projection.support_digest = digest("different-manifest"),
            _ => unreachable!(),
        }
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("registration"),
                manifest: projection,
            })
            .fixture("registration");
        assert_eq!(
            transaction.record_registry_durable(
                &registry,
                snapshot_receipt(&registry),
                &withdrawal_registry(),
                20
            ),
            Err(ArtifactPublicationError::RegistryProjectionMismatch)
        );
        assert_eq!(
            transaction.phase(),
            ArtifactPublicationPhaseV1::PayloadDurable
        );
    }
}
