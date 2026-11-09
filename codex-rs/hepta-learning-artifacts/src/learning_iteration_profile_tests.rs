use pretty_assertions::assert_eq;

use super::*;
use crate::learning_iteration_test_support::digest;
use crate::learning_iteration_test_support::owners;
use crate::learning_iteration_test_support::receipt;
use crate::learning_iteration_test_support::request;
use crate::test_support::FixtureValue;

#[test]
fn frozen_profile_is_required_and_committed_before_any_owner_work() {
    let mut unfrozen = request();
    unfrozen.evaluation_profile = Digest32::ZERO;
    assert!(matches!(
        LearningIterationCoordinatorV1::new(unfrozen, owners()),
        Err(LearningIterationError::EmptyEvidence)
    ));

    let original =
        LearningIterationCoordinatorV1::new(request(), owners()).fixture("original freeze");
    let mut changed_request = request();
    changed_request.evaluation_profile = digest("other-preregistered-profile");
    let mut changed =
        LearningIterationCoordinatorV1::new(changed_request, owners()).fixture("different freeze");
    assert_ne!(
        original.snapshot().head_digest,
        changed.snapshot().head_digest
    );
    let before = changed.snapshot().clone();
    assert_eq!(
        changed.record(receipt(&original), 20),
        Err(LearningIterationError::StalePredecessor)
    );
    assert_eq!(changed.snapshot(), &before);
}

#[test]
fn trainer_and_evaluator_cannot_replace_the_frozen_profile() {
    for disposition in [
        LearningEvaluationDispositionV1::Qualified,
        LearningEvaluationDispositionV1::NoUpdate,
    ] {
        let mut coordinator =
            LearningIterationCoordinatorV1::new(request(), owners()).fixture("freeze");
        for _ in 0..2 {
            coordinator
                .record(receipt(&coordinator), 20)
                .fixture("source");
        }
        let before_training = coordinator.snapshot().clone();
        let mut drifted = receipt(&coordinator);
        let LearningIterationObservationV1::Training { candidate, .. } = &mut drifted.observation
        else {
            panic!("expected training");
        };
        candidate
            .training_lineage
            .as_mut()
            .fixture("lineage")
            .evaluation_profile = digest("post-training-profile");
        assert_eq!(
            coordinator.record(drifted, 20),
            Err(LearningIterationError::ContextMismatch)
        );
        assert_eq!(coordinator.snapshot(), &before_training);
        coordinator
            .record(receipt(&coordinator), 20)
            .fixture("training");

        let before_evaluation = coordinator.snapshot().clone();
        let mut evaluated = receipt(&coordinator);
        let LearningIterationObservationV1::Evaluation {
            evaluation_profile,
            disposition: observed_disposition,
            ..
        } = &mut evaluated.observation
        else {
            panic!("expected evaluation");
        };
        *evaluation_profile = digest("post-training-profile");
        *observed_disposition = disposition;
        assert_eq!(
            coordinator.record(evaluated, 20),
            Err(LearningIterationError::ContextMismatch)
        );
        assert_eq!(coordinator.snapshot(), &before_evaluation);

        let mut matching = receipt(&coordinator);
        if let LearningIterationObservationV1::Evaluation {
            disposition: observed_disposition,
            ..
        } = &mut matching.observation
        {
            *observed_disposition = disposition;
        }
        coordinator
            .record(matching, 20)
            .fixture("original evaluation");
        let recovered =
            LearningIterationCoordinatorV1::from_snapshot(coordinator.snapshot().clone())
                .fixture("recover frozen decision");
        assert_eq!(recovered.snapshot(), coordinator.snapshot());
        if disposition == LearningEvaluationDispositionV1::NoUpdate {
            assert_eq!(
                recovered.disposition(),
                LearningIterationDispositionV1::NoUpdate
            );
            assert_eq!(
                recovered.next_task_bundle(),
                Some(&recovered.snapshot().request.selected_bundle)
            );
        }
    }
}
