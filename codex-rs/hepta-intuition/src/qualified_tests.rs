use super::*;
use crate::calibrated::AssignmentModeV1;
use crate::calibrated::CalibratedActionCandidateV1;
use crate::calibrated::CalibrationArtifactV1;
use crate::calibrated::CandidateSetCompletenessBindingV1;
use crate::calibrated::OodArtifactV1;
use crate::calibrated::SlowPathReasonV1;
use crate::calibrated::canonical_candidate_order_digest_v1;
use crate::calibrated::canonical_candidate_set_digest_v1;
use crate::calibrated::decide_calibrated_v2;
use codex_hepta_types::FixedQ32;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn probability_ppm(ppm: u64) -> ProbabilityQ32 {
    ProbabilityQ32::from_raw(
        ((u128::from(ProbabilityQ32::ONE.raw()) * u128::from(ppm)) / 1_000_000) as u64,
    )
    .unwrap()
}

fn fixture() -> (CalibratedDecisionRequestV1, CanonicalPolicyProfileV1) {
    let policy = digest("qualified-policy");
    let calibration = digest("qualified-calibration");
    let ood = digest("qualified-ood");
    let candidates = vec![CalibratedActionCandidateV1 {
        candidate_id: id("candidate:a"),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::ONE,
        calibrated_confidence: probability_ppm(900_000),
        ood_score: probability_ppm(100_000),
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest: digest("candidate-support"),
    }];
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates).unwrap();
    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates).unwrap();
    let request = CalibratedDecisionRequestV1 {
        decision_id: id("decision:qualified"),
        objective_digest: digest("objective"),
        objective_class_digest: digest("objective-class"),
        state_digest: digest("state"),
        policy_digest: policy,
        policy_generation: 9,
        sequence: 20,
        minimum_confidence: probability_ppm(700_000),
        maximum_ece_ppm: 30_000,
        maximum_ood_false_acceptance_ppm: 2_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest("complete"),
            generator_digest: digest("generator"),
            grammar_digest: digest("grammar"),
            hard_filter_digest: digest("filter"),
            truncation_digest: digest("truncation"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: 1,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: calibration,
            policy_digest: policy,
            objective_class_digest: digest("objective-class"),
            generation: 9,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            measured_ece_ppm: 10_000,
            subgroup_audit_digest: digest("subgroup"),
        },
        ood: OodArtifactV1 {
            artifact_digest: ood,
            policy_digest: policy,
            detector_digest: digest("detector"),
            support_digest: digest("ood-support"),
            generation: 9,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: probability_ppm(500_000),
            measured_false_acceptance_ppm: 1_000,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };
    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("intuition-profile:v1"),
        policy_digest: policy,
        objective_class_digest: digest("objective-class"),
        generation: 9,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        minimum_confidence: probability_ppm(700_000),
        maximum_ece_ppm: 30_000,
        maximum_ood_false_acceptance_ppm: 2_000,
        maximum_in_domain_score: probability_ppm(500_000),
        risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
        scorer: LearnedScorerContractV1 {
            model_digest: policy,
            feature_schema_digest: digest("features-v1"),
            output_schema_digest: digest("outputs-v1"),
            score_semantics_digest: digest("semantics-v1"),
            scorer_contract_digest: digest("scorer-v1"),
        },
        calibration_dataset_digest: digest("calibration-data"),
        ood_dataset_digest: digest("ood-data"),
        calibration_artifact_digest: calibration,
        ood_artifact_digest: ood,
    };
    (request, profile)
}

#[test]
fn current_v2_rejects_any_omitted_candidate_bound() {
    let (mut request, _) = fixture();
    request.completeness.omitted_count_bound = 1;
    assert_eq!(
        decide_calibrated_v2(request),
        Err(CalibratedError::IncompleteCandidateSet)
    );
}

#[test]
fn v3_rejects_request_threshold_drift_from_canonical_profile() {
    let (mut request, profile) = fixture();
    request.maximum_ece_ppm += 1;
    assert_eq!(
        decide_calibrated_v3(request, &profile),
        Err(QualifiedCalibratedError::ProfileThresholdMismatch(
            "maximum ece"
        ))
    );
}

#[test]
fn v3_can_tighten_risk_routing_from_the_authenticated_profile() {
    let (mut request, mut profile) = fixture();
    request.risk_class = RiskClass::Elevated;
    profile.risk_rule = CanonicalRiskRuleV1::ElevatedAndHighSlowPath;
    let receipt = decide_calibrated_v3(request, &profile).unwrap();
    assert_eq!(
        receipt.disposition,
        crate::calibrated::CalibratedDispositionV1::SlowPath(SlowPathReasonV1::HighRisk)
    );
}

#[test]
fn evidence_payloads_change_when_profile_or_candidate_set_changes() {
    let (request, profile) = fixture();
    let completeness = canonical_completeness_evidence_payload_v1(&request).unwrap();
    let qualification = canonical_qualification_evidence_payload_v1(&request, &profile).unwrap();

    let mut changed_request = request;
    changed_request.candidates[0].utility = FixedQ32::from_raw(2);
    changed_request.completeness.candidate_set_digest =
        canonical_candidate_set_digest_v1(&changed_request.candidates).unwrap();
    assert_ne!(
        canonical_completeness_evidence_payload_v1(&changed_request).unwrap(),
        completeness
    );

    let mut changed_profile = profile;
    changed_profile.maximum_ece_ppm += 1;
    changed_request.maximum_ece_ppm = changed_profile.maximum_ece_ppm;
    assert_ne!(
        canonical_qualification_evidence_payload_v1(&changed_request, &changed_profile).unwrap(),
        qualification
    );
}

#[test]
fn policy_model_and_scorer_identities_are_independent_but_bound() {
    let (request, mut profile) = fixture();
    profile.scorer.model_digest = digest("model-artifact-v2");
    profile.scorer.scorer_contract_digest = digest("scorer-contract-v2");
    let receipt = decide_calibrated_v3(request, &profile).unwrap();
    assert_eq!(
        receipt.disposition,
        crate::calibrated::CalibratedDispositionV1::Selected(id("candidate:a"))
    );
}
