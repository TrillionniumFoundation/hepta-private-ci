//! Protocol/type-confusion tests; fixture digests are not execution evidence.

use pretty_assertions::assert_eq;

use super::*;
use crate::CellStatePartitionV1;
use crate::learning_iteration_digest::learning_iteration_receipt_signing_bytes_v1;
use crate::learning_iteration_test_support::digest;
use crate::learning_iteration_test_support::id;
use crate::learning_iteration_test_support::owners;
use crate::learning_iteration_test_support::receipt;
use crate::learning_iteration_test_support::request;
use crate::test_support::FixtureValue;

#[test]
fn retained_task_and_model_cutover_are_not_interchangeable() {
    for decision_stage in [3, 4, 5] {
        let mut coordinator =
            LearningIterationCoordinatorV1::new(request(), owners()).fixture("coordinator");
        for _ in 0..decision_stage {
            coordinator
                .record(receipt(&coordinator), 20)
                .fixture("stage");
        }
        if decision_stage < 5 {
            let mut decision = receipt(&coordinator);
            match &mut decision.observation {
                LearningIterationObservationV1::Evaluation { disposition, .. } => {
                    *disposition = LearningEvaluationDispositionV1::NoUpdate
                }
                LearningIterationObservationV1::Proposal { disposition, .. } => {
                    *disposition = LearningProposalDispositionV1::NoAdmissibleUpdate
                }
                _ => panic!("decision fixture"),
            }
            coordinator.record(decision, 20).fixture("decision");
        }
        coordinator
            .record(receipt(&coordinator), 20)
            .fixture("selection");
        let before = coordinator.snapshot().clone();
        let mut wrong = receipt(&coordinator);
        wrong.observation = match wrong.observation {
            LearningIterationObservationV1::RetainedModelNextUse {
                retained_bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                task_owner_publication,
            } => LearningIterationObservationV1::NextUse {
                candidate_bundle: retained_bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                state_cutover_receipt: task_owner_publication,
            },
            LearningIterationObservationV1::NextUse {
                candidate_bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                state_cutover_receipt,
            } => LearningIterationObservationV1::RetainedModelNextUse {
                retained_bundle: candidate_bundle,
                state_partition,
                checkpoint_digest,
                selection_digest,
                committed_step_receipt,
                task_owner_publication: state_cutover_receipt,
            },
            _ => panic!("next-use fixture"),
        };
        assert_eq!(
            coordinator.record(wrong, 20),
            Err(LearningIterationError::ContextMismatch)
        );
        assert_eq!(coordinator.snapshot(), &before);
    }
}

#[test]
fn retained_use_rejects_wrong_partition_selection_and_missing_owner_receipts() {
    let mut coordinator =
        LearningIterationCoordinatorV1::new(request(), owners()).fixture("coordinator");
    for _ in 0..3 {
        coordinator
            .record(receipt(&coordinator), 20)
            .fixture("stage");
    }
    let mut decision = receipt(&coordinator);
    if let LearningIterationObservationV1::Evaluation { disposition, .. } =
        &mut decision.observation
    {
        *disposition = LearningEvaluationDispositionV1::NoUpdate;
    }
    coordinator.record(decision, 20).fixture("decision");
    coordinator
        .record(receipt(&coordinator), 20)
        .fixture("selection");
    let before = coordinator.snapshot().clone();
    for change in [
        "principal",
        "agent",
        "cell",
        "run",
        "checkpoint",
        "selection",
        "step",
        "publication",
    ] {
        let mut wrong = receipt(&coordinator);
        let LearningIterationObservationV1::RetainedModelNextUse {
            state_partition,
            checkpoint_digest,
            selection_digest,
            committed_step_receipt,
            task_owner_publication,
            ..
        } = &mut wrong.observation
        else {
            panic!("retained-use fixture")
        };
        match change {
            "principal" => state_partition.principal_id = id("other-principal"),
            "agent" => state_partition.agent_id = id("other-agent"),
            "cell" => state_partition.cell_id = id("other-cell"),
            "run" => state_partition.run_id = before.request.source_run_id.clone(),
            "checkpoint" => *checkpoint_digest = Digest32::ZERO,
            "selection" => *selection_digest = digest("other-selection"),
            "step" => *committed_step_receipt = Digest32::ZERO,
            "publication" => *task_owner_publication = Digest32::ZERO,
            _ => panic!("unknown mutation"),
        }
        assert_eq!(
            coordinator.record(wrong, 20),
            Err(LearningIterationError::ContextMismatch)
        );
        assert_eq!(coordinator.snapshot(), &before);
    }
}

#[test]
fn existing_cutover_signing_bytes_are_preserved_and_retained_use_has_its_own_tag() {
    let mut observed = LearningIterationReceiptV1 {
        operation_id: id("operation"),
        predecessor: Digest32::from_array([1; 32]),
        actor_id: id("observer"),
        evidence_digest: Digest32::from_array([2; 32]),
        observed_unix_seconds: 42,
        observation: LearningIterationObservationV1::NextUse {
            candidate_bundle: Digest32::from_array([3; 32]),
            state_partition: CellStatePartitionV1 {
                principal_id: id("principal"),
                agent_id: id("agent"),
                cell_id: id("cell"),
                run_id: id("run"),
            },
            checkpoint_digest: Digest32::from_array([4; 32]),
            selection_digest: Digest32::from_array([5; 32]),
            committed_step_receipt: Digest32::from_array([6; 32]),
            state_cutover_receipt: Digest32::from_array([7; 32]),
        },
    };
    let original =
        learning_iteration_receipt_signing_bytes_v1(&observed).fixture("legacy encoding");
    assert_eq!(
        Digest32::of_bytes(&original).to_string(),
        "cea426fda4d553a9ec83a8d376a4e03e20d8e6c34295babc600f7efe5e609cd0"
    );
    let LearningIterationObservationV1::NextUse {
        candidate_bundle,
        state_partition,
        checkpoint_digest,
        selection_digest,
        committed_step_receipt,
        state_cutover_receipt,
    } = observed.observation
    else {
        panic!("legacy fixture")
    };
    observed.observation = LearningIterationObservationV1::RetainedModelNextUse {
        retained_bundle: candidate_bundle,
        state_partition,
        checkpoint_digest,
        selection_digest,
        committed_step_receipt,
        task_owner_publication: state_cutover_receipt,
    };
    let retained =
        learning_iteration_receipt_signing_bytes_v1(&observed).fixture("retained encoding");
    assert_ne!(original, retained);
    assert_eq!(
        Digest32::of_bytes(&retained).to_string(),
        "c156312f3af93615f6165e23d9e4168f1a1f78f4c401fbe1955ccfd497d62df9"
    );
}
