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

fn fixture() -> (
    CalibratedDecisionRequestV1,
    CanonicalPolicyProfileV1,
    ScoringCommitmentV1,
) {
    let policy = digest("qualified-policy");
    let model = digest("qualified-model-artifact");
    let calibration = digest("qualified-calibration");
    let ood = digest("qualified-ood");
    let subgroup = digest("subgroup");
    let detector = digest("detector");
    let ood_support = digest("ood-support");
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
            subgroup_audit_digest: subgroup,
        },
        ood: OodArtifactV1 {
            artifact_digest: ood,
            policy_digest: policy,
            detector_digest: detector,
            support_digest: ood_support,
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
            model_digest: model,
            feature_schema_digest: digest("features-v1"),
            output_schema_digest: digest("outputs-v1"),
            score_semantics_digest: digest("semantics-v1"),
            scorer_contract_digest: digest("scorer-v1"),
        },
        calibration_dataset_digest: digest("calibration-data"),
        ood_dataset_digest: digest("ood-data"),
        calibration_artifact_digest: calibration,
        calibration_measured_ece_ppm: 10_000,
        calibration_subgroup_audit_digest: subgroup,
        ood_artifact_digest: ood,
        ood_measured_false_acceptance_ppm: 1_000,
        ood_detector_digest: detector,
        ood_support_digest: ood_support,
    };
    let scoring = ScoringCommitmentV1 {
        decision_id: request.decision_id.clone(),
        model_artifact_digest: model,
        feature_schema_digest: profile.scorer.feature_schema_digest,
        feature_snapshot_digest: digest("feature-snapshot"),
        scorer_contract_digest: profile.scorer.scorer_contract_digest,
        candidate_set_digest,
        scored_candidates_digest: canonical_scored_candidates_digest_v1(&request).unwrap(),
        policy_digest: policy,
        policy_generation: 9,
        sequence: 20,
    };
    (request, profile, scoring)
}

#[test]
fn current_v2_rejects_any_omitted_candidate_bound() {
    let (mut request, _, _) = fixture();
    request.completeness.omitted_count_bound = 1;
    assert_eq!(
        decide_calibrated_v2(request),
        Err(CalibratedError::CandidateSetMismatch)
    );
}

#[test]
fn v3_keeps_policy_model_and_scorer_identities_distinct() {
    let (request, profile, scoring) = fixture();
    assert_ne!(profile.policy_digest, profile.scorer.model_digest);
    assert_ne!(
        profile.scorer.model_digest,
        profile.scorer.scorer_contract_digest
    );
    assert!(canonical_scoring_commitment_digest_v1(&request, &profile, &scoring).is_ok());
    assert!(decide_calibrated_v3(request, &profile).is_ok());
}

#[test]
fn v3_rejects_request_threshold_or_artifact_metadata_drift() {
    let (mut request, profile, _) = fixture();
    request.maximum_ece_ppm += 1;
    assert_eq!(
        decide_calibrated_v3(request, &profile),
        Err(QualifiedCalibratedError::ProfileThresholdMismatch(
            "maximum ece"
        ))
    );

    let (mut request, profile, _) = fixture();
    request.calibration.measured_ece_ppm += 1;
    assert_eq!(
        decide_calibrated_v3(request, &profile),
        Err(QualifiedCalibratedError::ProfileArtifactMetadataMismatch(
            "calibration"
        ))
    );
}

#[test]
fn v3_can_tighten_risk_routing_from_the_authenticated_profile() {
    let (mut request, mut profile, _) = fixture();
    request.risk_class = RiskClass::Elevated;
    profile.risk_rule = CanonicalRiskRuleV1::ElevatedAndHighSlowPath;
    let receipt = decide_calibrated_v3(request, &profile).unwrap();
    assert_eq!(
        receipt.disposition,
        crate::calibrated::CalibratedDispositionV1::SlowPath(SlowPathReasonV1::HighRisk)
    );
}

#[test]
fn scoring_commitment_detects_score_or_model_substitution() {
    let (mut request, profile, scoring) = fixture();
    let original =
        canonical_scoring_evidence_payload_v1(&request, &profile, &scoring).unwrap();

    request.candidates[0].utility = FixedQ32::from_raw(2);
    request.completeness.candidate_set_digest =
        canonical_candidate_set_digest_v1(&request.candidates).unwrap();
    let mut changed = scoring.clone();
    changed.candidate_set_digest = request.completeness.candidate_set_digest;
    assert_eq!(
        canonical_scoring_commitment_digest_v1(&request, &profile, &changed),
        Err(QualifiedCalibratedError::ScoringCommitmentMismatch("scores"))
    );

    let (request, profile, mut scoring) = fixture();
    scoring.model_artifact_digest = digest("other-model");
    assert_eq!(
        canonical_scoring_commitment_digest_v1(&request, &profile, &scoring),
        Err(QualifiedCalibratedError::ScoringCommitmentMismatch("model"))
    );
    assert!(!original.is_empty());
}

#[test]
fn assignment_commitment_binds_stream_sequence_and_draw() {
    let (mut request, _, _) = fixture();
    request.candidates[0].assignment_probability = ProbabilityQ32::ONE;
    request.completeness.candidate_set_digest =
        canonical_candidate_set_digest_v1(&request.candidates).unwrap();
    request.assignment = AssignmentModeV1::CounterBased {
        random_stream_digest: digest("random-stream-manifest"),
        draw: ProbabilityQ32::ZERO,
        abstain_probability: ProbabilityQ32::ZERO,
    };
    let first = canonical_assignment_evidence_payload_v1(&request).unwrap();
    request.sequence += 1;
    let second = canonical_assignment_evidence_payload_v1(&request).unwrap();
    assert_ne!(first, second);
}
