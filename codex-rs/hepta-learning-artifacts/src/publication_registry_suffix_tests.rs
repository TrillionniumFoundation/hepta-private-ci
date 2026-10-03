use super::*;
use crate::ArtifactEvent;
use crate::StateChange;
use crate::publication_registry_suffix::stage_state_changes;
use crate::publication_registry_suffix::validate_registry_suffix;

fn prepared_suffix() -> (
    ArtifactPublicationTransactionV1,
    ArtifactRegistry,
    StateChange,
) {
    let event = registry_with_candidate(Digest32::ZERO).records()[0]
        .event
        .clone();
    let ArtifactEvent::Register { mut manifest, .. } = event.clone() else {
        unreachable!()
    };
    manifest.artifact_id = id("old-artifact");
    manifest.generation = generation(1);
    let mut registry = ArtifactRegistry::new();
    registry
        .append(ArtifactEvent::Register {
            event_id: id("old-register"),
            manifest,
        })
        .expect("old registry candidate");
    let admission = prepared().intent().admission.clone();
    let mut transaction = ArtifactPublicationTransactionV1::begin(
        id("suffix-operation"),
        admission,
        &withdrawal_registry(),
        &registry,
        registry.head_digest(),
        20,
    )
    .expect("native anchored publication intent");
    transaction
        .record_payload_durable(digest("payload"), 7)
        .expect("payload receipt");
    registry.append(event).expect("exact native projection");
    (
        transaction,
        registry,
        StateChange {
            event_id: id("old-revoke"),
            artifact_id: id("old-artifact"),
            evaluator_id: id("fixed-evaluator"),
            reason_digest: digest("actual-rejection"),
        },
    )
}

#[test]
fn original_candidate_and_old_artifact_revocation_remain_exact_on_native_resume() {
    let (mut transaction, mut registry, change) = prepared_suffix();
    stage_state_changes(
        transaction.intent(),
        &mut registry,
        &[ArtifactEvent::Revoke(change)],
    )
    .expect("bounded old-artifact revocation");
    transaction
        .record_registry_durable(
            &registry,
            snapshot_receipt(&registry),
            &withdrawal_registry(),
            20,
        )
        .expect("complete native suffix receipt");
    let resumed = ArtifactPublicationTransactionV1::from_snapshot(transaction.snapshot())
        .expect("original native state reconstruction");
    assert_eq!(resumed.validate_registry_projection(&registry), Ok(()));
    assert_eq!(resumed.snapshot(), transaction.snapshot());
}

#[test]
fn state_suffix_cannot_register_another_candidate_or_disable_current_publication() {
    let (transaction, mut registry, mut change) = prepared_suffix();
    let before = registry.records().to_vec();
    change.artifact_id = v2_manifest().artifact_id;
    assert!(
        stage_state_changes(
            transaction.intent(),
            &mut registry,
            &[ArtifactEvent::Revoke(change)]
        )
        .is_err()
    );
    assert_eq!(registry.records(), before.as_slice());
    let ArtifactEvent::Register { mut manifest, .. } = before[0].event.clone() else {
        unreachable!()
    };
    manifest.artifact_id = id("extra-artifact");
    assert!(
        stage_state_changes(
            transaction.intent(),
            &mut registry,
            &[ArtifactEvent::Register {
                event_id: id("extra-register"),
                manifest,
            }]
        )
        .is_err()
    );
    assert_eq!(registry.records(), before.as_slice());
}

#[test]
fn exact_objective_support_predecessor_and_state_change_capacity_are_required() {
    let (transaction, registry, change) = prepared_suffix();
    for field in 0..3 {
        let mut changed = ArtifactRegistry::new();
        changed
            .append(registry.records()[0].event.clone())
            .expect("prior exact prefix");
        let ArtifactEvent::Register {
            event_id,
            mut manifest,
        } = registry.records()[1].event.clone()
        else {
            unreachable!()
        };
        match field {
            0 => manifest.support_digest = digest("old unrelated support"),
            1 => manifest.objective_digest = digest("unrelated objective"),
            2 => manifest.predecessor_id = Some(id("old-artifact")),
            _ => unreachable!(),
        }
        changed
            .append(ArtifactEvent::Register { event_id, manifest })
            .expect("valid generic registry event");
        assert_eq!(
            validate_registry_suffix(transaction.intent(), &changed),
            Err(ArtifactPublicationError::RegistryProjectionMismatch)
        );
    }
    let mut changed = registry.clone();
    assert!(
        stage_state_changes(
            transaction.intent(),
            &mut changed,
            &vec![ArtifactEvent::Revoke(change); 65]
        )
        .is_err()
    );
    assert_eq!(changed.records(), registry.records());
    let mut intent = transaction.intent().clone();
    intent.expected_registry_predecessor_head = digest("different original head");
    assert_eq!(
        validate_registry_suffix(&intent, &registry),
        Err(ArtifactPublicationError::RegistryPredecessorMismatch)
    );
}
