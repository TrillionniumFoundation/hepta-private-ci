//! Synthetic authenticated-owner fixtures; these are not real learning trials.
use super::*;
use pretty_assertions::assert_eq;

type TestResult = Result<(), Box<dyn std::error::Error>>;

fn input(fixture: &Fixture) -> LearningDecisionInputV1 {
    let candidate_id = fixture.bundle.candidate_id.clone();
    LearningDecisionInputV1 {
        plan: LearningDecisionPlanV1 {
            cycle_id: id("learning-cycle"),
            incumbent_id: fixture.admission.baseline_id.clone(),
            incumbent_model_digest: fixture.admission.selected_artifact_digest,
            protocol_digest: digest("prospective-protocol"),
            objective_digest: fixture.admission.objective_digest,
            dataset_digest: fixture.admission.dataset_digest,
            search_space_digest: fixture.generated.generator_digest,
            cost_profile_digest: digest("disjoint-cost-normalization"),
            maximum_candidates: 8,
            maximum_attempts: 32,
            maximum_cost_units: 1000,
            next_attempt_reservation_units: 10,
        },
        stop: LearningStopV1::FiniteSearchComplete,
        terminal_evidence_digest: digest("native-owner-terminal"),
        data_eligibility_evidence_digest: digest("qualified-data-inventory"),
        candidates: vec![LearningCandidateResultV1 {
            candidate_id: candidate_id.clone(),
            model_digest: digest("candidate-model"),
            evaluation: fixture.request().evaluations.into_iter().next(),
        }],
        attempts: vec![LearningAttemptV1 {
            attempt_id: id("attempt:1"),
            retry_of: None,
            candidate_id: Some(candidate_id),
            phase: LearningAttemptPhaseV1::Evaluation,
            status: LearningAttemptStatusV1::Succeeded,
            cost_units: [Some(1); 9],
            owner_receipt_digest: digest("owner-attempt:1"),
        }],
    }
}

fn attest(
    fixture: &Fixture,
    input: &LearningDecisionInputV1,
) -> Result<LearningDecisionAttestationsV1, LearningDecisionErrorV1> {
    let bytes = learning_decision_signing_payload_v1(input)?;
    Ok(LearningDecisionAttestationsV1 {
        generator: fixture.sign(/*signer*/ 0, LearningEvidenceRoleV1::Generator, &bytes),
        observer: fixture.sign(/*signer*/ 1, LearningEvidenceRoleV1::Observer, &bytes),
        evaluator: fixture.sign(/*signer*/ 2, LearningEvidenceRoleV1::Evaluator, &bytes),
    })
}

fn complete(
    fixture: &Fixture,
    input: LearningDecisionInputV1,
) -> Result<LearningDecisionReceiptV1, LearningDecisionErrorV1> {
    let pins = learning_decision_inventory_v1(&input)?;
    let attestations = attest(fixture, &input)?;
    complete_authenticated_learning_decision_v1(
        input,
        pins,
        attestations,
        &fixture.verifier,
        /*now*/ 50,
    )
}

#[test]
fn all_four_decisions_preserve_incumbent_and_exact_evidence() -> TestResult {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    let success = input(&fixture);
    let mut no_data = success.clone();
    no_data.stop = LearningStopV1::NoQualifiedData;
    no_data.candidates.clear();
    no_data.attempts.clear();
    let mut incomplete = success.clone();
    incomplete.candidates[0].evaluation = None;
    let mut failed = success.clone();
    failed.stop = LearningStopV1::ExecutionFailed;
    failed.attempts[0].status = LearningAttemptStatusV1::Failed;
    failed.attempts[0].cost_units[0] = None;
    for (input, expected) in [
        (success, LearningCycleDispositionV1::Adoptable),
        (no_data, LearningCycleDispositionV1::NoUpdate),
        (incomplete, LearningCycleDispositionV1::Inconclusive),
        (failed, LearningCycleDispositionV1::Failed),
    ] {
        let receipt = complete(&fixture, input.clone())?;
        assert_eq!(receipt.summary().decision, expected);
        assert_eq!(receipt.evidence().0, &input);
        assert_eq!(
            (
                &receipt.summary().retained_incumbent_id,
                receipt.summary().retained_incumbent_model_digest,
                receipt.summary().authority
            ),
            (
                &input.plan.incumbent_id,
                input.plan.incumbent_model_digest,
                AuthorityPosture::DENY_ALL
            )
        );
        assert_eq!(
            receipt.summary().eligible_candidate_ids.is_empty(),
            expected != LearningCycleDispositionV1::Adoptable
        );
    }
    Ok(())
}

#[test]
fn revalidation_is_idempotent_but_still_obeys_current_validity() -> TestResult {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    let record = input(&fixture);
    let pins = learning_decision_inventory_v1(&record)?;
    let signatures = attest(&fixture, &record)?;
    let first = complete_authenticated_learning_decision_v1(
        record.clone(),
        pins,
        signatures.clone(),
        &fixture.verifier,
        /*now*/ 50,
    )?;
    let later = complete_authenticated_learning_decision_v1(
        record.clone(),
        pins,
        signatures.clone(),
        &fixture.verifier,
        /*now*/ 51,
    )?;
    assert_eq!(first, later);
    assert!(matches!(
        complete_authenticated_learning_decision_v1(
            record,
            pins,
            signatures,
            &fixture.verifier,
            /*now*/ 91
        ),
        Err(LearningDecisionErrorV1::Authentication(_))
    ));
    Ok(())
}

#[test]
fn evaluated_rejection_is_finite_no_update_without_relaxing_proposal() -> TestResult {
    let fixture = Fixture::with_minimum_improvement(
        /*evaluator_controller_collision_with*/ None,
        digest("rejected-publication"),
        FixedQ32::from_raw(3_i64 << 32),
    );
    let receipt = complete(&fixture, input(&fixture))?;
    assert_eq!(
        (
            receipt.summary().decision,
            receipt.summary().no_update_reason
        ),
        (
            LearningCycleDispositionV1::NoUpdate,
            Some(LearningStopV1::FiniteSearchComplete)
        )
    );
    let result = propose_authenticated_parameter_plasticity_v1(
        fixture.request(),
        &fixture.verifier,
        &mut writer(),
        &mut AnchorCommitter {
            accept: true,
            ..AnchorCommitter::default()
        },
        /*now*/ 50,
    );
    assert!(matches!(
        result,
        Err(ParameterPlasticityProductErrorV1::Ineligible(
            IndependentEvaluationDispositionV1::Ineligible
        ))
    ));
    Ok(())
}

#[test]
fn budget_stop_is_predeclared_and_does_not_claim_unseen_candidates_failed() -> TestResult {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    let mut record = input(&fixture);
    record.candidates[0].evaluation = None;
    record.attempts[0].phase = LearningAttemptPhaseV1::Training;
    record.stop = LearningStopV1::BudgetStopped;
    assert!(matches!(
        complete(&fixture, record.clone()),
        Err(LearningDecisionErrorV1::Binding(
            "budget stop before declared boundary"
        ))
    ));
    record.plan.maximum_cost_units = 18;
    let receipt = complete(&fixture, record)?;
    assert_eq!(
        (
            receipt.summary().decision,
            receipt.summary().known_cost_units
        ),
        (LearningCycleDispositionV1::NoUpdate, 9)
    );
    assert!(receipt.evidence().0.candidates[0].evaluation.is_none());
    let mut failed = receipt.evidence().0.clone();
    failed.attempts[0].status = LearningAttemptStatusV1::Failed;
    assert_eq!(
        complete(&fixture, failed)?.summary().decision,
        LearningCycleDispositionV1::Failed
    );
    let mut lost = receipt.evidence().0.clone();
    lost.attempts[0].phase = LearningAttemptPhaseV1::Evaluation;
    assert_eq!(
        complete(&fixture, lost)?.summary().decision,
        LearningCycleDispositionV1::Inconclusive
    );
    Ok(())
}

#[test]
fn unknown_cost_unresolved_owner_and_missing_eval_work_never_become_no_update() -> TestResult {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    for variant in 0..3 {
        let mut record = input(&fixture);
        match variant {
            0 => record.attempts[0].cost_units[8] = None,
            1 => record.attempts[0].status = LearningAttemptStatusV1::Unresolved,
            2 => record.attempts.clear(),
            _ => unreachable!(),
        }
        let receipt = complete(&fixture, record)?;
        assert_eq!(
            (
                receipt.summary().decision,
                receipt.summary().no_update_reason
            ),
            (LearningCycleDispositionV1::Inconclusive, None)
        );
    }
    Ok(())
}

#[test]
fn failed_retries_are_retained_charged_and_overruns_fail() -> TestResult {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    let mut record = input(&fixture);
    let mut retry = record.attempts[0].clone();
    retry.attempt_id = id("attempt:0");
    retry.status = LearningAttemptStatusV1::Failed;
    retry.owner_receipt_digest = digest("owner-attempt:0");
    record.attempts[0].retry_of = Some(retry.attempt_id.clone());
    record.attempts.insert(0, retry);
    let receipt = complete(&fixture, record.clone())?;
    assert_eq!(
        (
            receipt.summary().decision,
            receipt.summary().known_cost_units,
            receipt.summary().failed_attempts,
            receipt.evidence().0.attempts.len()
        ),
        (LearningCycleDispositionV1::Adoptable, 18, 1, 2)
    );
    record.plan.maximum_cost_units = 17;
    assert_eq!(
        complete(&fixture, record)?.summary().decision,
        LearningCycleDispositionV1::Failed
    );
    Ok(())
}

#[test]
fn shared_failure_and_unrelated_earlier_success_cannot_become_no_update() -> TestResult {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    for stop in [
        LearningStopV1::NoQualifiedData,
        LearningStopV1::FiniteSearchComplete,
    ] {
        let mut record = input(&fixture);
        record.candidates.clear();
        record.attempts[0].candidate_id = None;
        record.attempts[0].status = LearningAttemptStatusV1::Failed;
        record.stop = stop;
        assert_eq!(
            complete(&fixture, record)?.summary().decision,
            LearningCycleDispositionV1::Failed
        );
    }
    let mut record = input(&fixture);
    record.candidates[0].evaluation = None;
    record.stop = LearningStopV1::BudgetStopped;
    record.plan.maximum_cost_units = 18;
    record.attempts[0].phase = LearningAttemptPhaseV1::Training;
    let mut later = record.attempts[0].clone();
    later.attempt_id = id("attempt:2");
    later.owner_receipt_digest = digest("later-attempt");
    later.status = LearningAttemptStatusV1::Failed;
    record.attempts.push(later);
    assert_eq!(
        complete(&fixture, record)?.summary().decision,
        LearningCycleDispositionV1::Failed
    );
    Ok(())
}

#[test]
fn invalid_retry_lineage_and_unresolved_retries_are_refused() -> TestResult {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    let mut record = input(&fixture);
    let mut later = record.attempts[0].clone();
    later.attempt_id = id("attempt:2");
    later.owner_receipt_digest = digest("later-attempt");
    later.retry_of = Some(record.attempts[0].attempt_id.clone());
    record.attempts.push(later);
    for status in [
        LearningAttemptStatusV1::Succeeded,
        LearningAttemptStatusV1::Unresolved,
    ] {
        record.attempts[0].status = status;
        assert!(matches!(
            complete(&fixture, record.clone()),
            Err(LearningDecisionErrorV1::Binding("retry lineage"))
        ));
    }
    record.attempts[0].status = LearningAttemptStatusV1::Failed;
    record.attempts[1].retry_of = Some(id("future-attempt"));
    assert!(matches!(
        complete(&fixture, record),
        Err(LearningDecisionErrorV1::Binding("retry predecessor"))
    ));
    Ok(())
}

#[test]
fn completed_rejected_candidate_cap_is_a_valid_budget_boundary() -> TestResult {
    let fixture = Fixture::with_minimum_improvement(
        /*evaluator_controller_collision_with*/ None,
        digest("rejected-publication"),
        FixedQ32::from_raw(3_i64 << 32),
    );
    let mut record = input(&fixture);
    record.plan.maximum_candidates = 1;
    record.stop = LearningStopV1::BudgetStopped;
    let receipt = complete(&fixture, record)?;
    assert_eq!(
        (
            receipt.summary().decision,
            receipt.summary().no_update_reason
        ),
        (
            LearningCycleDispositionV1::NoUpdate,
            Some(LearningStopV1::BudgetStopped)
        )
    );
    Ok(())
}

#[test]
fn native_inventory_omission_and_post_signature_changes_are_refused() -> TestResult {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    let original = input(&fixture);
    let pins = learning_decision_inventory_v1(&original)?;
    let mut changed = original.clone();
    changed.attempts.clear();
    let signed_changed = attest(&fixture, &changed)?;
    assert!(matches!(
        complete_authenticated_learning_decision_v1(
            changed,
            pins,
            signed_changed,
            &fixture.verifier,
            /*now*/ 50
        ),
        Err(LearningDecisionErrorV1::Binding(
            "host-owned plan or inventory"
        ))
    ));
    let signatures = attest(&fixture, &original)?;
    let mut changed = original;
    changed.attempts[0].cost_units[0] = Some(2);
    let pins = learning_decision_inventory_v1(&changed)?;
    assert!(matches!(
        complete_authenticated_learning_decision_v1(
            changed,
            pins,
            signatures,
            &fixture.verifier,
            /*now*/ 50
        ),
        Err(LearningDecisionErrorV1::Authentication(_))
    ));
    Ok(())
}

#[test]
fn duplicate_receipts_noop_models_and_mislabeled_no_data_are_refused() -> TestResult {
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    let mut record = input(&fixture);
    let mut duplicate = record.attempts[0].clone();
    duplicate.attempt_id = id("attempt:2");
    record.attempts.push(duplicate);
    assert!(matches!(
        complete(&fixture, record),
        Err(LearningDecisionErrorV1::Binding("attempt inventory"))
    ));
    let mut record = input(&fixture);
    record.candidates[0].model_digest = record.plan.incumbent_model_digest;
    assert!(matches!(
        complete(&fixture, record),
        Err(LearningDecisionErrorV1::Binding(
            "candidate inventory or no-op"
        ))
    ));
    let mut record = input(&fixture);
    record.stop = LearningStopV1::NoQualifiedData;
    assert!(matches!(
        complete(&fixture, record),
        Err(LearningDecisionErrorV1::Binding(
            "no-qualified-data with candidates"
        ))
    ));
    Ok(())
}

#[test]
fn colliding_evaluator_and_tampered_qualifications_fail_authentication() -> TestResult {
    let collision = Fixture::new(/*evaluator_controller_collision*/ true);
    assert!(matches!(
        complete(&collision, input(&collision)),
        Err(LearningDecisionErrorV1::Authentication(_))
    ));
    let fixture = Fixture::new(/*evaluator_controller_collision*/ false);
    let mut record = input(&fixture);
    if let Some(evaluation) = &mut record.candidates[0].evaluation {
        evaluation.qualification.publication_digest = digest("substituted-publication");
    }
    assert!(matches!(
        complete(&fixture, record),
        Err(LearningDecisionErrorV1::Evaluation(_))
    ));
    Ok(())
}
