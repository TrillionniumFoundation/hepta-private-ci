use super::*;
use codex_hepta_ndu::AxisValue;
use codex_hepta_ndu::CandidateUtility;
use codex_hepta_ndu::EvaluationDisposition;
use codex_hepta_ndu::NduEvaluationReceipt;
use codex_hepta_types::FixedQ32;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn ndu(recommendation: Option<&str>) -> NduEvaluationReceiptV2 {
    NduEvaluationReceiptV2 {
        base: NduEvaluationReceipt {
            objective_digest: digest("objective"),
            generation: Generation::new(1).expect("generation"),
            disposition: EvaluationDisposition::ScalarizedRecommendation,
            utility_profile_digest: digest("profile"),
            scalarization_profile_digest: Some(digest("scalarization")),
            evaluated_candidates: vec![
                CandidateUtility {
                    candidate_id: id("cell-0"),
                    utility: vec![AxisValue {
                        axis: id("quality"),
                        value: FixedQ32::ZERO,
                    }],
                    risk: vec![],
                    resource: vec![],
                    uncertainty: vec![],
                    support_digest: digest("support-0"),
                    scalar_score: Some(FixedQ32::ZERO),
                },
                CandidateUtility {
                    candidate_id: id("cell-1"),
                    utility: vec![AxisValue {
                        axis: id("quality"),
                        value: FixedQ32::ONE,
                    }],
                    risk: vec![],
                    resource: vec![],
                    uncertainty: vec![],
                    support_digest: digest("support-1"),
                    scalar_score: Some(FixedQ32::ONE),
                },
            ],
            rejected_candidates: vec![],
            pareto_frontier: vec![],
            advisory_recommendation: recommendation.map(id),
            evaluation_digest: digest("evaluation"),
        },
        evaluation_policy_digest: digest("policy"),
        evaluation_digest_v2: digest("evaluation-v2"),
    }
}

fn request(recommendation: Option<&str>) -> CellNduEvaluationRequestV1 {
    CellNduEvaluationRequestV1 {
        evaluator_id: id("evaluator"),
        selector_id: id("selector"),
        executor_id: id("executor"),
        baseline_id: id("cell-0"),
        baseline_artifact_digest: digest("artifact-0"),
        generation: Generation::new(1).expect("generation"),
        ndu: ndu(recommendation),
        candidates: vec![
            CellNduCandidateEvidenceV1 {
                candidate_id: id("cell-0"),
                artifact_digest: digest("artifact-0"),
                future_window_digest: digest("future-0"),
                utility_delta_q32: 0,
                resource_cost_q32: 0,
                negative_migration_q32: 0,
            },
            CellNduCandidateEvidenceV1 {
                candidate_id: id("cell-1"),
                artifact_digest: digest("artifact-1"),
                future_window_digest: digest("future-1"),
                utility_delta_q32: 4,
                resource_cost_q32: 1,
                negative_migration_q32: 1,
            },
        ],
    }
}

#[test]
fn evaluator_freezes_baseline_and_selector_follows_ndu_recommendation() {
    let request = request(Some("cell-1"));
    let receipt = evaluate_cell_ndu_v1(request.clone()).expect("evaluation");
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    let decision = select_cell_ndu_v1(&receipt, &request.ndu, digest("artifact-1"))
        .expect("selection");
    let CellNduSelectionDecisionV1::Candidate(token) = decision else {
        panic!("candidate should be selected")
    };
    let execution = execute_cell_ndu_v1(token, &id("executor")).expect("execution");
    assert_eq!(execution.candidate_id, id("cell-1"));
    assert_eq!(execution.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn selector_rejects_caller_supplied_artifact_digest_drift() {
    let request = request(Some("cell-1"));
    let receipt = evaluate_cell_ndu_v1(request.clone()).expect("evaluation");
    assert_eq!(
        select_cell_ndu_v1(&receipt, &request.ndu, digest("different-artifact")),
        Err(CellNduSelectionErrorV1::TokenBinding)
    );
}

#[test]
fn no_recommendation_is_a_durable_no_change_decision() {
    let request = request(None);
    let receipt = evaluate_cell_ndu_v1(request.clone()).expect("evaluation");
    assert!(matches!(
        select_cell_ndu_v1(&receipt, &request.ndu, digest("artifact-0")),
        Ok(CellNduSelectionDecisionV1::NoChange { .. })
    ));
    assert_eq!(
        select_cell_ndu_v1(&receipt, &request.ndu, digest("wrong-baseline")),
        Err(CellNduSelectionErrorV1::TokenBinding)
    );
}

#[test]
fn roles_and_negative_migration_are_independent_and_fail_closed() {
    let mut request = request(Some("cell-1"));
    request.selector_id = request.evaluator_id.clone();
    assert_eq!(
        evaluate_cell_ndu_v1(request),
        Err(CellNduSelectionErrorV1::RoleCollision)
    );
    let mut request = request(Some("cell-1"));
    request.candidates[1].negative_migration_q32 = -1;
    assert_eq!(
        evaluate_cell_ndu_v1(request),
        Err(CellNduSelectionErrorV1::NegativeMigration)
    );
}

#[test]
fn negative_utility_is_retained_as_rejected_and_cannot_be_selected() {
    let mut request = request(Some("cell-1"));
    request.candidates[1].utility_delta_q32 = -1;
    let receipt = evaluate_cell_ndu_v1(request.clone()).expect("negative utility is evidence");
    assert_eq!(receipt.eligible_candidate_ids, vec![id("cell-0")]);
    assert_eq!(receipt.rejected_candidate_ids, vec![id("cell-1")]);
    assert_eq!(
        receipt.candidate_artifact_digests.get(&id("cell-1")),
        Some(&digest("artifact-1"))
    );
    assert_eq!(
        select_cell_ndu_v1(&receipt, &request.ndu, digest("artifact-1")),
        Err(CellNduSelectionErrorV1::RecommendationRejected)
    );
}

#[test]
fn selector_rejects_receipt_role_generation_and_ndu_digest_drift() {
    let request = request(Some("cell-1"));
    let receipt = evaluate_cell_ndu_v1(request.clone()).expect("evaluation");

    let mut role_drift = receipt.clone();
    role_drift.selector_id = role_drift.evaluator_id.clone();
    assert_eq!(
        select_cell_ndu_v1(&role_drift, &request.ndu, digest("artifact-1")),
        Err(CellNduSelectionErrorV1::RoleCollision)
    );

    let mut generation_drift = receipt.clone();
    generation_drift.generation = Generation::new(2).expect("generation");
    assert_eq!(
        select_cell_ndu_v1(&generation_drift, &request.ndu, digest("artifact-1")),
        Err(CellNduSelectionErrorV1::GenerationMismatch)
    );

    let mut ndu_drift = request.ndu.clone();
    ndu_drift.evaluation_digest_v2 = digest("other-evaluation");
    assert_eq!(
        select_cell_ndu_v1(&receipt, &ndu_drift, digest("artifact-1")),
        Err(CellNduSelectionErrorV1::NduBinding)
    );
}

#[test]
fn evaluator_rejects_generation_mismatch_without_dropping_evidence() {
    let mut request = request(Some("cell-1"));
    request.generation = Generation::new(2).expect("generation");
    assert_eq!(
        evaluate_cell_ndu_v1(request),
        Err(CellNduSelectionErrorV1::GenerationMismatch)
    );
}
