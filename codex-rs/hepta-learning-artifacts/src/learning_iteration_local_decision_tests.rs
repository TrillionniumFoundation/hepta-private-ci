//! Protocol controls with synthetic owner observations; no quality claims.

use pretty_assertions::assert_eq;

use super::*;
use crate::FrozenLearningScopeV2;
use crate::LearningUpdateScopeV2;
use crate::learning_iteration_digest::learning_iteration_receipt_signing_bytes_v1;
use crate::learning_iteration_test_support::*;
use crate::test_support::FixtureValue;

fn qualified() -> LearningIterationCoordinatorV1 {
    let mut c = LearningIterationCoordinatorV1::new(request(), owners()).fixture("initial");
    for _ in 0..5 {
        c.record(receipt(&c), 20).fixture("qualified prefix");
    }
    c
}

fn local(
    c: &LearningIterationCoordinatorV1,
    disposition: LearningLocalDispositionV2,
) -> LearningIterationReceiptV1 {
    let mut r = receipt(c);
    let candidate_bundle = c
        .candidate()
        .fixture("candidate")
        .digest()
        .fixture("candidate digest");
    r.observation = LearningIterationObservationV1::LocalDecisionV2(LearningLocalDecisionV2 {
        proposal_head: c.snapshot().head_digest,
        candidate_bundle,
        selected_bundle: match disposition {
            LearningLocalDispositionV2::AdoptCandidate => candidate_bundle,
            LearningLocalDispositionV2::DeferCandidate
            | LearningLocalDispositionV2::RetainParent => c
                .snapshot()
                .request
                .selected_bundle
                .digest()
                .fixture("parent"),
        },
        policy_digest: digest("node policy version 4"),
        reason_digest: digest("original local decision reason"),
        disposition,
    });
    r
}

#[test]
fn qualified_candidate_can_be_locally_retained_without_rewriting_evaluation() {
    for disposition in [
        LearningLocalDispositionV2::AdoptCandidate,
        LearningLocalDispositionV2::DeferCandidate,
        LearningLocalDispositionV2::RetainParent,
    ] {
        let mut c = qualified();
        let original = c.snapshot().clone();
        let mut legacy_retention = receipt(&c);
        legacy_retention.observation = LearningIterationObservationV1::Selection {
            candidate_bundle: original.request.selected_bundle.digest().fixture("parent"),
            selection_digest: digest("selection"),
        };
        assert_eq!(
            c.record(legacy_retention, 20),
            Err(LearningIterationError::ContextMismatch)
        );
        assert_eq!(c.snapshot(), &original);
        let choice = local(&c, disposition);
        let signed = learning_iteration_receipt_signing_bytes_v1(&choice).fixture("signed choice");
        assert!(signed.starts_with(b"hepta.learning.iteration-local-decision.v2\0"));
        c.record(choice.clone(), 20).fixture("local decision");
        assert_eq!(
            c.record(choice, 20).fixture("exact replay"),
            c.snapshot().head_digest
        );
        assert_eq!(&c.snapshot().receipts[..5], original.receipts.as_slice());
        assert_eq!(c.next_stage(), Some(LearningIterationStageV1::Selection));
        assert_eq!(
            c.disposition(),
            match disposition {
                LearningLocalDispositionV2::AdoptCandidate =>
                    LearningIterationDispositionV1::InProgress,
                LearningLocalDispositionV2::DeferCandidate =>
                    LearningIterationDispositionV1::LocallyDeferredV2,
                LearningLocalDispositionV2::RetainParent =>
                    LearningIterationDispositionV1::LocallyRetainedV2,
            }
        );
        // No use can be reported until the original version owner's Selection.
        let mut skipped = receipt(&c);
        skipped.observation = LearningIterationObservationV1::RetainedModelNextUse {
            retained_bundle: original.request.selected_bundle.digest().fixture("parent"),
            state_partition: crate::CellStatePartitionV1 {
                principal_id: original.request.principal_id.clone(),
                agent_id: original.request.agent_id.clone(),
                cell_id: original.request.cell_id.clone(),
                run_id: id("run:fresh-task"),
            },
            checkpoint_digest: digest("checkpoint"),
            selection_digest: digest("selection"),
            committed_step_receipt: digest("step"),
            task_owner_publication: digest("publication"),
        };
        assert_eq!(
            c.record(skipped, 20),
            Err(LearningIterationError::WrongStage)
        );
        c.record(receipt(&c), 20).fixture("actual selection");
        c.record(receipt(&c), 20).fixture("distinct next use");
        assert_eq!(c.snapshot().receipts.len(), 8);
        assert_eq!(
            c.disposition(),
            LearningIterationDispositionV1::UsedByNextTask
        );
        assert_eq!(
            LearningIterationCoordinatorV1::from_snapshot(c.snapshot().clone())
                .fixture("cold structural replay")
                .snapshot(),
            c.snapshot()
        );
    }
}

#[test]
fn local_policy_cannot_choose_an_unbound_bundle_or_replace_a_prior_choice() {
    let mutations: [fn(&mut LearningLocalDecisionV2); 5] = [
        |d| d.proposal_head = digest("foreign proposal"),
        |d| d.candidate_bundle = digest("foreign candidate"),
        |d| d.selected_bundle = digest("arbitrary model"),
        |d| d.policy_digest = Digest32::ZERO,
        |d| d.reason_digest = Digest32::ZERO,
    ];
    for mutate in mutations {
        let mut c = qualified();
        let before = c.snapshot().clone();
        let mut choice = local(&c, LearningLocalDispositionV2::RetainParent);
        let LearningIterationObservationV1::LocalDecisionV2(decision) = &mut choice.observation
        else {
            panic!("local decision");
        };
        mutate(decision);
        assert_eq!(
            c.record(choice, 20),
            Err(LearningIterationError::ContextMismatch)
        );
        assert_eq!(c.snapshot(), &before);
    }
    let mut c = qualified();
    let mut forged = local(&c, LearningLocalDispositionV2::RetainParent);
    forged.actor_id = c.snapshot().owners.trainer.clone();
    assert_eq!(
        c.record(forged, 20),
        Err(LearningIterationError::WrongOwner)
    );
    c.record(local(&c, LearningLocalDispositionV2::DeferCandidate), 20)
        .fixture("defer");
    let before = c.snapshot().clone();
    assert_eq!(
        c.record(local(&c, LearningLocalDispositionV2::AdoptCandidate), 20),
        Err(LearningIterationError::ContextMismatch)
    );
    assert_eq!(c.snapshot(), &before);
    let mut selected = receipt(&c);
    let LearningIterationObservationV1::Selection {
        candidate_bundle, ..
    } = &mut selected.observation
    else {
        panic!("selection");
    };
    *candidate_bundle = c
        .candidate()
        .fixture("candidate")
        .digest()
        .fixture("digest");
    assert_eq!(
        c.record(selected, 20),
        Err(LearningIterationError::ContextMismatch)
    );
    assert_eq!(c.snapshot(), &before);
}

#[test]
fn signed_local_decision_binds_policy_reason_choice_and_evidence() {
    let c = qualified();
    let original = local(&c, LearningLocalDispositionV2::RetainParent);
    let bytes = learning_iteration_receipt_signing_bytes_v1(&original).fixture("payload");
    let mutations: [fn(&mut LearningIterationReceiptV1); 5] = [
        |r| r.evidence_digest = digest("other owner evidence"),
        |r| r.actor_id = id("selector:other"),
        |r| {
            if let LearningIterationObservationV1::LocalDecisionV2(d) = &mut r.observation {
                d.policy_digest = digest("changed policy");
            }
        },
        |r| {
            if let LearningIterationObservationV1::LocalDecisionV2(d) = &mut r.observation {
                d.reason_digest = digest("changed reason");
            }
        },
        |r| {
            if let LearningIterationObservationV1::LocalDecisionV2(d) = &mut r.observation {
                d.disposition = LearningLocalDispositionV2::DeferCandidate;
            }
        },
    ];
    for mutate in mutations {
        let mut changed = original.clone();
        mutate(&mut changed);
        assert_ne!(
            learning_iteration_receipt_signing_bytes_v1(&changed).fixture("changed"),
            bytes
        );
    }
}

#[test]
fn local_decision_does_not_relax_frozen_base_or_execution_schema() {
    for mutate in [
        (|bundle: &mut CellCompatibilityBundleV1| bundle.components.base = digest("new base"))
            as fn(&mut CellCompatibilityBundleV1),
        |bundle| bundle.components.numeric_profile = digest("new executable profile"),
        |bundle| bundle.components.output_schema = digest("new command schema"),
    ] {
        let initial = request();
        let scope = FrozenLearningScopeV2::freeze(
            &initial,
            &owners(),
            LearningUpdateScopeV2::Cell,
            digest("rule"),
        )
        .fixture("scope");
        let mut c = LearningIterationCoordinatorV1::new(initial, owners()).fixture("initial");
        for _ in 0..2 {
            c.record(receipt(&c), 20).fixture("prefix");
        }
        let mut trained = receipt(&c);
        let LearningIterationObservationV1::Training { candidate, .. } = &mut trained.observation
        else {
            panic!("training");
        };
        mutate(candidate);
        c.record(trained, 20)
            .fixture("authority-free structural record");
        let mut evaluated = receipt(&c);
        let LearningIterationObservationV1::Evaluation {
            candidate_bundle, ..
        } = &mut evaluated.observation
        else {
            panic!("evaluation");
        };
        *candidate_bundle = c
            .candidate()
            .fixture("candidate")
            .digest()
            .fixture("bundle");
        c.record(evaluated, 20).fixture("evaluation");
        let mut proposed = receipt(&c);
        let LearningIterationObservationV1::Proposal {
            candidate_bundle, ..
        } = &mut proposed.observation
        else {
            panic!("proposal");
        };
        *candidate_bundle = c
            .candidate()
            .fixture("candidate")
            .digest()
            .fixture("bundle");
        c.record(proposed, 20).fixture("proposal");
        c.record(local(&c, LearningLocalDispositionV2::RetainParent), 20)
            .fixture("local decision");
        assert_eq!(
            scope.validate_snapshot(c.snapshot()),
            Err(LearningIterationError::UpdateScopeMismatch)
        );
    }
}
