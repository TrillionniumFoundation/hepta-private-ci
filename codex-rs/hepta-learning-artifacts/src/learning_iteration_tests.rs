use pretty_assertions::assert_eq;

use super::*;
use crate::learning_iteration_test_support::digest;
use crate::learning_iteration_test_support::id;
use crate::learning_iteration_test_support::owners;
use crate::learning_iteration_test_support::receipt;
use crate::learning_iteration_test_support::request;
use crate::test_support::FixtureValue;

#[test]
fn completes_only_after_next_task_and_replays_every_durable_boundary() {
    let request = request();
    let selected = request.selected_bundle.clone();
    let mut coordinator =
        LearningIterationCoordinatorV1::new(request, owners()).fixture("coordinator");
    for stage in STAGES {
        assert_eq!(coordinator.next_stage(), Some(stage));
        let observed = receipt(&coordinator);
        coordinator.record(observed.clone(), 20).fixture("record");
        let expected = coordinator.snapshot().clone();
        assert_eq!(coordinator.record(observed, 200), Ok(expected.head_digest));
        coordinator =
            LearningIterationCoordinatorV1::from_snapshot(expected.clone()).fixture("restart");
        assert_eq!(coordinator.snapshot(), &expected);
    }
    assert_eq!(coordinator.next_stage(), None);
    assert_eq!(
        coordinator.disposition(),
        LearningIterationDispositionV1::UsedByNextTask
    );
    assert_eq!(&coordinator.snapshot().request.selected_bundle, &selected);
}

#[test]
fn failed_validation_never_advances_checkpoint() {
    let mut coordinator =
        LearningIterationCoordinatorV1::new(request(), owners()).fixture("coordinator");
    let original = coordinator.snapshot().clone();
    let changes: [fn(&mut LearningIterationReceiptV1); 5] = [
        |r| r.operation_id = id("wrong:operation"),
        |r| r.actor_id = id("wrong:owner"),
        |r| r.predecessor = digest("stale"),
        |r| r.evidence_digest = Digest32::ZERO,
        |r| r.observed_unix_seconds = 99,
    ];
    for change in changes {
        let mut observed = receipt(&coordinator);
        change(&mut observed);
        assert!(coordinator.record(observed, 20).is_err());
        assert_eq!(coordinator.snapshot(), &original);
    }
    assert_eq!(
        coordinator.record(receipt(&coordinator), 100),
        Err(LearningIterationError::DeadlineExceeded)
    );
    assert_eq!(coordinator.snapshot(), &original);
}

#[test]
fn over_budget_dataset_and_cross_dataset_training_are_rejected() {
    let mut coordinator =
        LearningIterationCoordinatorV1::new(request(), owners()).fixture("coordinator");
    coordinator
        .record(receipt(&coordinator), 20)
        .fixture("experience");
    let before = coordinator.snapshot().clone();
    let mut over_budget = receipt(&coordinator);
    if let LearningIterationObservationV1::Dataset { rows, .. } = &mut over_budget.observation {
        *rows = 11;
    }
    assert_eq!(
        coordinator.record(over_budget, 20),
        Err(LearningIterationError::ContextMismatch)
    );
    assert_eq!(coordinator.snapshot(), &before);
    coordinator
        .record(receipt(&coordinator), 20)
        .fixture("dataset");
    let mut wrong = receipt(&coordinator);
    if let LearningIterationObservationV1::Training { candidate, .. } = &mut wrong.observation {
        candidate
            .training_lineage
            .as_mut()
            .fixture("lineage")
            .dataset = digest("other-dataset");
    }
    assert_eq!(
        coordinator.record(wrong, 20),
        Err(LearningIterationError::ContextMismatch)
    );
    assert_eq!(
        coordinator.next_stage(),
        Some(LearningIterationStageV1::Training)
    );
}

#[test]
fn no_update_keeps_baseline_and_replays_selection_and_actual_next_use() {
    for stage_count in [3, 4] {
        let mut coordinator =
            LearningIterationCoordinatorV1::new(request(), owners()).fixture("coordinator");
        for _ in 0..stage_count {
            coordinator
                .record(receipt(&coordinator), 20)
                .fixture("stage");
        }
        let mut decision = receipt(&coordinator);
        match &mut decision.observation {
            LearningIterationObservationV1::Evaluation { disposition, .. } => {
                *disposition = LearningEvaluationDispositionV1::NoUpdate
            }
            LearningIterationObservationV1::Proposal { disposition, .. } => {
                *disposition = LearningProposalDispositionV1::NoAdmissibleUpdate
            }
            _ => panic!("wrong test stage"),
        }
        coordinator.record(decision, 20).fixture("no update");
        assert_eq!(
            coordinator.disposition(),
            LearningIterationDispositionV1::NoUpdate
        );
        let original_bundle = coordinator.snapshot().request.selected_bundle.clone();
        assert_eq!(coordinator.next_task_bundle(), Some(&original_bundle));
        let rejected = coordinator
            .candidate()
            .fixture("candidate")
            .digest()
            .fixture("digest");
        for stage in [
            LearningIterationStageV1::Selection,
            LearningIterationStageV1::NextUse,
        ] {
            coordinator =
                LearningIterationCoordinatorV1::from_snapshot(coordinator.snapshot().clone())
                    .fixture("reopen pending no update");
            assert_eq!(coordinator.next_stage(), Some(stage));
            assert_eq!(
                coordinator.disposition(),
                LearningIterationDispositionV1::NoUpdate
            );
            let before = coordinator.snapshot().clone();
            let actual = receipt(&coordinator);
            let mut wrong = actual.clone();
            match &mut wrong.observation {
                LearningIterationObservationV1::Selection {
                    candidate_bundle, ..
                }
                | LearningIterationObservationV1::NextUse {
                    candidate_bundle, ..
                } => {
                    *candidate_bundle = rejected;
                }
                LearningIterationObservationV1::RetainedModelNextUse {
                    retained_bundle, ..
                } => {
                    *retained_bundle = rejected;
                }
                _ => panic!("wrong test stage"),
            }
            assert_eq!(
                coordinator.record(wrong, 20),
                Err(LearningIterationError::ContextMismatch)
            );
            assert_eq!(coordinator.snapshot(), &before);
            coordinator
                .record(actual.clone(), 20)
                .fixture("retained baseline");
            let committed = coordinator.snapshot().clone();
            assert_eq!(coordinator.record(actual, 200), Ok(committed.head_digest));
            coordinator = LearningIterationCoordinatorV1::from_snapshot(committed.clone())
                .fixture("reopen committed");
            assert_eq!(coordinator.snapshot(), &committed);
        }
        assert_eq!(coordinator.next_stage(), None);
        assert_eq!(
            coordinator.disposition(),
            LearningIterationDispositionV1::UsedByNextTask
        );
        assert_eq!(coordinator.next_task_bundle(), Some(&original_bundle));
    }
}

#[test]
fn no_update_cannot_skip_selection_or_substitute_a_no_admissible_proposal() {
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
    coordinator
        .record(decision, 20)
        .fixture("rejected evaluation");
    let before = coordinator.snapshot().clone();
    let mut wrong = receipt(&coordinator);
    wrong.actor_id = before.owners.proposal.clone();
    wrong.observation = LearningIterationObservationV1::Proposal {
        candidate_bundle: coordinator
            .candidate()
            .fixture("candidate")
            .digest()
            .fixture("digest"),
        proposal_id: before.request.operation_id.clone(),
        composition_digest: digest("invented generator result"),
        disposition: LearningProposalDispositionV1::NoAdmissibleUpdate,
    };
    assert_eq!(
        coordinator.record(wrong, 20),
        Err(LearningIterationError::WrongStage)
    );
    assert_eq!(coordinator.snapshot(), &before);
    coordinator
        .record(receipt(&coordinator), 20)
        .fixture("selection");
    let next_use = receipt(&coordinator);
    let mut restored =
        LearningIterationCoordinatorV1::from_snapshot(before.clone()).fixture("old cut");
    assert_eq!(
        restored.record(next_use, 20),
        Err(LearningIterationError::WrongStage)
    );
    assert_eq!(restored.snapshot(), &before);
}

#[test]
fn replay_rejects_missing_receipts_changed_budget_and_false_next_use() {
    let mut coordinator =
        LearningIterationCoordinatorV1::new(request(), owners()).fixture("coordinator");
    for _ in 0..6 {
        coordinator
            .record(receipt(&coordinator), 20)
            .fixture("stage");
    }
    let before = coordinator.snapshot().clone();
    let changes: [fn(&mut LearningIterationObservationV1); 4] = [
        |o| {
            if let LearningIterationObservationV1::NextUse {
                state_partition, ..
            } = o
            {
                state_partition.run_id = id("run:source");
            }
        },
        |o| {
            if let LearningIterationObservationV1::NextUse {
                state_partition, ..
            } = o
            {
                state_partition.cell_id = id("cell:other");
            }
        },
        |o| {
            if let LearningIterationObservationV1::NextUse {
                state_partition, ..
            } = o
            {
                state_partition.principal_id = id("principal:other");
            }
        },
        |o| {
            if let LearningIterationObservationV1::NextUse {
                selection_digest, ..
            } = o
            {
                *selection_digest = digest("other-selection");
            }
        },
    ];
    for change in changes {
        let mut next_use = receipt(&coordinator);
        change(&mut next_use.observation);
        assert_eq!(
            coordinator.record(next_use, 20),
            Err(LearningIterationError::ContextMismatch)
        );
    }
    let mut missing = before.clone();
    missing.receipts.remove(1);
    assert!(LearningIterationCoordinatorV1::from_snapshot(missing).is_err());
    let mut changed = before.clone();
    changed.request.budget.maximum_dataset_rows += 1;
    assert!(LearningIterationCoordinatorV1::from_snapshot(changed).is_err());
    assert_eq!(coordinator.snapshot(), &before);
}

#[test]
fn owner_independence_is_checked_before_any_stage() {
    let changes: [fn(&mut LearningIterationOwnersV1); 3] = [
        |o| o.evaluator = o.trainer.clone(),
        |o| o.selector = o.evaluator.clone(),
        |o| o.next_use_observer = o.trainer.clone(),
    ];
    for change in changes {
        let mut altered = owners();
        change(&mut altered);
        assert!(matches!(
            LearningIterationCoordinatorV1::new(request(), altered),
            Err(LearningIterationError::OwnerConflict)
        ));
    }
}
