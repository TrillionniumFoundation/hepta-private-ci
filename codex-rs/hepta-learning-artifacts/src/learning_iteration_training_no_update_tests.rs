//! Versioned protocol controls; fixture digests do not prove optimizer work.

use pretty_assertions::assert_eq;

use super::*;
use crate::FrozenLearningScopeV2;
use crate::LearningUpdateScopeV2;
use crate::learning_iteration_test_support::digest;
use crate::learning_iteration_test_support::id;
use crate::learning_iteration_test_support::owners;
use crate::learning_iteration_test_support::receipt;
use crate::learning_iteration_test_support::request;
use crate::test_support::FixtureValue;

fn dataset_cut() -> LearningIterationCoordinatorV1 {
    let mut coordinator =
        LearningIterationCoordinatorV1::new(request(), owners()).fixture("initial");
    for _ in 0..2 {
        coordinator
            .record(receipt(&coordinator), 20)
            .fixture("source stage");
    }
    coordinator
}

fn unchanged(coordinator: &LearningIterationCoordinatorV1) -> LearningIterationReceiptV1 {
    let mut observed = receipt(coordinator);
    observed.observation =
        LearningIterationObservationV1::TrainingNoUpdateV2(LearningTrainingNoUpdateV2 {
            retained_bundle: coordinator
                .snapshot()
                .request
                .selected_bundle
                .digest()
                .fixture("baseline"),
            dataset: digest("dataset"),
            update_rule: digest("rule"),
            steps: 2,
            milliseconds: 10,
            reason: LearningTrainingNoUpdateReasonV2::QuantizedWeightsUnchanged,
        });
    observed
}

fn scope(coordinator: &LearningIterationCoordinatorV1) -> FrozenLearningScopeV2 {
    FrozenLearningScopeV2::freeze(
        &coordinator.snapshot().request,
        &coordinator.snapshot().owners,
        LearningUpdateScopeV2::Cell,
        digest("rule"),
    )
    .fixture("original frozen scope")
}

#[test]
fn trainer_no_update_requires_selection_and_real_retained_use_without_candidate_or_evaluation() {
    let mut coordinator = dataset_cut();
    let scope = scope(&coordinator);
    let observed = unchanged(&coordinator);
    scope
        .validate_observation(&observed.observation)
        .fixture("frozen outcome");
    coordinator
        .record(observed, 20)
        .fixture("trainer no update");
    assert_eq!(coordinator.candidate(), None);
    assert_eq!(
        coordinator.disposition(),
        LearningIterationDispositionV1::NoUpdate
    );
    assert_eq!(
        coordinator.next_stage(),
        Some(LearningIterationStageV1::Selection)
    );
    assert_eq!(
        coordinator.next_task_bundle(),
        Some(&coordinator.snapshot().request.selected_bundle)
    );
    let pending = coordinator.snapshot().clone();
    let mut wrong_owner = receipt(&coordinator);
    wrong_owner.actor_id = pending.owners.trainer.clone();
    assert_eq!(
        coordinator.record(wrong_owner, 20),
        Err(LearningIterationError::WrongOwner)
    );
    assert_eq!(coordinator.snapshot(), &pending);
    coordinator
        .record(receipt(&coordinator), 20)
        .fixture("independent selection");
    assert_eq!(
        coordinator.disposition(),
        LearningIterationDispositionV1::NoUpdate
    );
    assert_eq!(
        coordinator.next_stage(),
        Some(LearningIterationStageV1::NextUse)
    );
    let before = coordinator.snapshot().clone();
    for fault in ["source-alias", "missing-use", "model-cutover"] {
        let mut next = receipt(&coordinator);
        let LearningIterationObservationV1::RetainedModelNextUse {
            retained_bundle,
            state_partition,
            checkpoint_digest,
            selection_digest,
            committed_step_receipt,
            task_owner_publication,
        } = &mut next.observation
        else {
            panic!("retained fixture")
        };
        match fault {
            "source-alias" => state_partition.run_id = before.request.source_run_id.clone(),
            "missing-use" => *committed_step_receipt = Digest32::ZERO,
            "model-cutover" => {
                next.observation = LearningIterationObservationV1::NextUse {
                    candidate_bundle: *retained_bundle,
                    state_partition: state_partition.clone(),
                    checkpoint_digest: *checkpoint_digest,
                    selection_digest: *selection_digest,
                    committed_step_receipt: *committed_step_receipt,
                    state_cutover_receipt: *task_owner_publication,
                }
            }
            _ => panic!("unknown fault"),
        }
        assert_eq!(
            coordinator.record(next, 20),
            Err(LearningIterationError::ContextMismatch)
        );
        assert_eq!(coordinator.snapshot(), &before);
    }
    coordinator
        .record(receipt(&coordinator), 20)
        .fixture("actual retained use");
    assert_eq!(coordinator.next_stage(), None);
    assert_eq!(
        coordinator.disposition(),
        LearningIterationDispositionV1::UsedByNextTask
    );
    assert_eq!(
        coordinator
            .snapshot()
            .receipts
            .iter()
            .map(|r| r.observation.stage())
            .collect::<Vec<_>>(),
        vec![
            LearningIterationStageV1::Experience,
            LearningIterationStageV1::Dataset,
            LearningIterationStageV1::Training,
            LearningIterationStageV1::Selection,
            LearningIterationStageV1::NextUse
        ]
    );
    scope
        .validate_snapshot(coordinator.snapshot())
        .fixture("completed original scope");
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(coordinator.snapshot().clone())
            .fixture("replay without evaluation")
            .snapshot(),
        coordinator.snapshot()
    );
}

#[test]
fn trainer_no_update_rejects_dataset_baseline_quota_and_original_scope_changes() {
    let mut coordinator = dataset_cut();
    let original = coordinator.snapshot().clone();
    for fault in [
        "baseline",
        "dataset",
        "empty-rule",
        "steps",
        "milliseconds",
        "actor",
    ] {
        let mut observed = unchanged(&coordinator);
        let LearningIterationObservationV1::TrainingNoUpdateV2(outcome) = &mut observed.observation
        else {
            panic!("trainer fixture")
        };
        match fault {
            "baseline" => outcome.retained_bundle = digest("different-weights"),
            "dataset" => outcome.dataset = digest("different-dataset"),
            "empty-rule" => outcome.update_rule = Digest32::ZERO,
            "steps" => outcome.steps = original.request.budget.maximum_training_steps + 1,
            "milliseconds" => outcome.milliseconds = 0,
            "actor" => observed.actor_id = original.owners.evaluator.clone(),
            _ => panic!("unknown fault"),
        }
        assert!(coordinator.record(observed, 20).is_err());
        assert_eq!(coordinator.snapshot(), &original);
    }
    let frozen = scope(&coordinator);
    let mut substituted = unchanged(&coordinator);
    let LearningIterationObservationV1::TrainingNoUpdateV2(outcome) = &mut substituted.observation
    else {
        panic!("trainer fixture")
    };
    outcome.update_rule = digest("arbitrary-nonzero-rule");
    assert_eq!(
        frozen.validate_observation(&substituted.observation),
        Err(LearningIterationError::UpdateScopeMismatch)
    );
    let mut rebound = original;
    rebound.request.source_run_id = id("different-original-source");
    assert_eq!(
        frozen.validate_snapshot(&rebound),
        Err(LearningIterationError::UpdateScopeMismatch)
    );
    coordinator
        .record(receipt(&coordinator), 20)
        .fixture("candidate training");
    assert_eq!(
        coordinator.record(unchanged(&dataset_cut()), 20),
        Err(LearningIterationError::WrongStage)
    );
}
