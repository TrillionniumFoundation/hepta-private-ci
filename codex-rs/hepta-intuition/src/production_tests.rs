use super::*;
use crate::calibrated::CalibrationArtifactV1;
use crate::calibrated::CandidateSetCompletenessBindingV1;
use crate::calibrated::OodArtifactV1;
use crate::calibrated::canonical_candidate_order_digest_v1;
use crate::calibrated::canonical_candidate_set_digest_v1;
use crate::qualified::LearnedScorerContractV1;
use codex_hepta_types::FixedQ32;

fn d(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("stable id")
}

fn fixture(
    risk_class: RiskClass,
    risk_rule: CanonicalRiskRuleV1,
) -> (CalibratedDecisionRequestV1, CanonicalPolicyProfileV1) {
    let candidates = vec![CalibratedActionCandidateV1 {
        candidate_id: id("candidate:a"),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::from_raw(7),
        calibrated_confidence: ProbabilityQ32::ONE,
        ood_score: ProbabilityQ32::ZERO,
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest: d("support:a"),
    }];
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates).expect("set");
    let request = CalibratedDecisionRequestV1 {
        decision_id: id("decision:production"),
        objective_digest: d("objective"),
        objective_class_digest: d("objective-class"),
        state_digest: d("state"),
        policy_digest: d("policy"),
        policy_generation: 4,
        sequence: 12,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        risk_class,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: d("completeness"),
            generator_digest: d("generator"),
            grammar_digest: d("grammar"),
            hard_filter_digest: d("hard-filter"),
            truncation_digest: d("truncation"),
            candidate_set_digest,
            canonical_order_digest: canonical_candidate_order_digest_v1(&candidates)
                .expect("order"),
            candidate_count: 1,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: d("calibration"),
            policy_digest: d("policy"),
            objective_class_digest: d("objective-class"),
            generation: 4,
            valid_from_sequence: 1,
            expires_after_sequence: 20,
            measured_ece_ppm: 1,
            subgroup_audit_digest: d("subgroup-audit"),
        },
        ood: OodArtifactV1 {
            artifact_digest: d("ood"),
            policy_digest: d("policy"),
            detector_digest: d("detector"),
            support_digest: d("ood-support"),
            generation: 4,
            valid_from_sequence: 1,
            expires_after_sequence: 20,
            maximum_in_domain_score: ProbabilityQ32::ONE,
            measured_false_acceptance_ppm: 1,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };
    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("profile:production"),
        policy_digest: d("policy"),
        objective_class_digest: d("objective-class"),
        generation: 4,
        valid_from_sequence: 1,
        expires_after_sequence: 20,
        minimum_confidence: ProbabilityQ32::ZERO,
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        maximum_in_domain_score: ProbabilityQ32::ONE,
        risk_rule,
        scorer: LearnedScorerContractV1 {
            model_digest: d("model"),
            feature_schema_digest: d("feature-schema"),
            output_schema_digest: d("output-schema"),
            score_semantics_digest: d("score-semantics"),
            scorer_contract_digest: d("scorer-contract"),
        },
        calibration_dataset_digest: d("calibration-data"),
        ood_dataset_digest: d("ood-data"),
        calibration_artifact_digest: d("calibration"),
        ood_artifact_digest: d("ood"),
    };
    (request, profile)
}

fn commitments(
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
) -> (ScoringCommitmentV2, AssignmentCommitmentV2) {
    let scoring = ScoringCommitmentV2 {
        model_artifact_digest: profile.scorer.model_digest,
        feature_snapshot_digest: d("feature-snapshot"),
        feature_schema_digest: profile.scorer.feature_schema_digest,
        scorer_contract_digest: profile.scorer.scorer_contract_digest,
        candidate_identity_digest: canonical_candidate_identity_digest_v2(&request.candidates)
            .expect("identity"),
        scored_outputs_digest: canonical_scored_outputs_digest_v2(request).expect("scores"),
        policy_digest: request.policy_digest,
        policy_generation: PolicyGeneration::new(request.policy_generation).expect("generation"),
    };
    let assignment = AssignmentCommitmentV2::Deterministic {
        distribution_digest: canonical_assignment_distribution_digest_v2(request)
            .expect("distribution"),
    };
    (scoring, assignment)
}

#[test]
fn bounded_scalar_types_reject_invalid_wire_values() {
    assert_eq!(Ppm::new(0).expect("zero ppm").get(), 0);
    assert_eq!(
        Ppm::new(PPM_SCALE).expect("one million ppm").get(),
        PPM_SCALE
    );
    assert_eq!(
        Ppm::new(PPM_SCALE + 1),
        Err(BoundedValueError::PpmOutOfRange)
    );
    assert_eq!(
        PolicyGeneration::new(0),
        Err(BoundedValueError::ZeroPolicyGeneration)
    );
    assert_eq!(PolicyGeneration::new(9).expect("generation").get(), 9);
}

#[test]
fn assignment_drift_does_not_change_identity_or_scorer_digests() {
    let (request, _) = fixture(RiskClass::Low, CanonicalRiskRuleV1::HighOnlySlowPath);
    let identity = canonical_candidate_identity_digest_v2(&request.candidates).expect("identity");
    let scores = canonical_scored_outputs_digest_v2(&request).expect("scores");
    let distribution = canonical_assignment_distribution_digest_v2(&request).expect("distribution");

    let mut changed = request;
    changed.candidates[0].assignment_probability = ProbabilityQ32::ONE;

    assert_eq!(
        identity,
        canonical_candidate_identity_digest_v2(&changed.candidates).expect("changed identity")
    );
    assert_eq!(
        scores,
        canonical_scored_outputs_digest_v2(&changed).expect("changed scores")
    );
    assert_ne!(
        distribution,
        canonical_assignment_distribution_digest_v2(&changed).expect("changed distribution")
    );
}

#[test]
fn scorer_drift_does_not_change_assignment_distribution_digest() {
    let (request, _) = fixture(RiskClass::Low, CanonicalRiskRuleV1::HighOnlySlowPath);
    let distribution = canonical_assignment_distribution_digest_v2(&request).expect("distribution");
    let scores = canonical_scored_outputs_digest_v2(&request).expect("scores");

    let mut changed = request;
    changed.candidates[0].utility = FixedQ32::from_raw(99);

    assert_eq!(
        distribution,
        canonical_assignment_distribution_digest_v2(&changed).expect("changed distribution")
    );
    assert_ne!(
        scores,
        canonical_scored_outputs_digest_v2(&changed).expect("changed scores")
    );
}

#[test]
fn generator_identity_digest_binds_every_owned_field_and_order() {
    let (request, _) = fixture(RiskClass::Low, CanonicalRiskRuleV1::HighOnlySlowPath);
    let base = canonical_candidate_identity_digest_v2(&request.candidates).expect("identity");

    let mut variants = Vec::new();
    let mut changed = request.candidates.clone();
    changed[0].candidate_id = id("candidate:b");
    variants.push(changed);
    let mut changed = request.candidates.clone();
    changed[0].legal = false;
    variants.push(changed);
    let mut changed = request.candidates.clone();
    changed[0].hard_veto = true;
    variants.push(changed);
    let mut changed = request.candidates.clone();
    changed[0].support_digest = d("support:changed");
    variants.push(changed);

    for variant in variants {
        assert_ne!(
            base,
            canonical_candidate_identity_digest_v2(&variant).expect("mutated identity")
        );
    }

    let mut ordered = request.candidates.clone();
    let mut second = ordered[0].clone();
    second.candidate_id = id("candidate:b");
    second.support_digest = d("support:b");
    ordered.push(second);
    let forward = canonical_candidate_identity_digest_v2(&ordered).expect("forward");
    ordered.reverse();
    let reverse = canonical_candidate_identity_digest_v2(&ordered).expect("reverse");
    assert_ne!(forward, reverse, "candidate order is semantic");
}

#[test]
fn split_digest_properties_hold_under_deterministic_mutation_fuzzing() {
    let (base, _) = fixture(RiskClass::Low, CanonicalRiskRuleV1::HighOnlySlowPath);
    let base_identity = canonical_candidate_identity_digest_v2(&base.candidates).expect("identity");
    let base_scores = canonical_scored_outputs_digest_v2(&base).expect("scores");
    let base_distribution =
        canonical_assignment_distribution_digest_v2(&base).expect("distribution");
    let mut state = 0x9e37_79b9_7f4a_7c15_u64;

    for _ in 0..2_048 {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        let probability = ProbabilityQ32::from_raw(state % (ProbabilityQ32::ONE.raw() + 1))
            .expect("bounded probability");

        let mut assignment_only = base.clone();
        assignment_only.candidates[0].assignment_probability = probability;
        assert_eq!(
            base_identity,
            canonical_candidate_identity_digest_v2(&assignment_only.candidates)
                .expect("assignment identity")
        );
        assert_eq!(
            base_scores,
            canonical_scored_outputs_digest_v2(&assignment_only).expect("assignment scores")
        );

        let mut scoring_only = base.clone();
        scoring_only.candidates[0].utility = FixedQ32::from_raw(state as i64);
        scoring_only.candidates[0].calibrated_confidence = probability;
        scoring_only.candidates[0].ood_score = ProbabilityQ32::from_raw(
            ProbabilityQ32::ONE.raw().saturating_sub(probability.raw()),
        )
        .expect("bounded inverse probability");
        assert_eq!(
            base_identity,
            canonical_candidate_identity_digest_v2(&scoring_only.candidates)
                .expect("scoring identity")
        );
        assert_eq!(
            base_distribution,
            canonical_assignment_distribution_digest_v2(&scoring_only)
                .expect("scoring distribution")
        );
    }
}

#[test]
fn production_contract_matches_cross_language_golden_vectors() {
    let (request, profile) = fixture(RiskClass::Low, CanonicalRiskRuleV1::HighOnlySlowPath);
    let (scoring, assignment) = commitments(&request, &profile);
    let vectors = include_str!("../testdata/production_contract_v2.json");
    let observed = [
        canonical_candidate_identity_digest_v2(&request.candidates)
            .expect("identity")
            .to_string(),
        canonical_scored_outputs_digest_v2(&request)
            .expect("scores")
            .to_string(),
        canonical_assignment_distribution_digest_v2(&request)
            .expect("distribution")
            .to_string(),
        canonical_scoring_commitment_digest_v2(&scoring)
            .expect("scoring commitment")
            .to_string(),
        canonical_assignment_commitment_digest_v2(&request, &assignment)
            .expect("assignment commitment")
            .to_string(),
    ];
    let expected = [
        "0f68fab105bf87ac3deccd9e600f50f3ac3f73d76b60cbb015f12f1f1b8cf4c3",
        "c68b21558abeb706fa2ff0a891260f13203d63d5ceeb74ca14ee6549388f8867",
        "b64df105e2dd632556aac5f1d9875f1f4f12c6e70e03c4358d017088a8bbbc0c",
        "8bae263cd6515398507323bd9b6702bea6303af58e9ac841ae72f814b6025422",
        "813530d434f0c0568dbfd256f352013a038b9824d4767418b36432da9e38efef",
    ];
    assert_eq!(observed, expected);
    for digest in expected {
        assert!(vectors.contains(digest), "golden vector file omitted {digest}");
    }
}

#[test]
fn profile_forced_slow_path_has_an_explicit_reason() {
    let (request, profile) = fixture(
        RiskClass::Elevated,
        CanonicalRiskRuleV1::ElevatedAndHighSlowPath,
    );
    let receipt = decide_calibrated_v4(request, &profile).expect("production decision");
    assert_eq!(
        receipt.disposition,
        ProductionDispositionV1::SlowPath(ProductionSlowPathReasonV1::ProfileRiskRule)
    );
    assert_eq!(receipt.original_risk_class, RiskClass::Elevated);
    assert_eq!(receipt.slow_path_probability, ProbabilityQ32::ONE);
    assert!(
        receipt
            .propensities
            .iter()
            .all(|item| item.probability == ProbabilityQ32::ZERO)
    );
}

#[test]
fn runtime_v2_accepts_only_exact_split_commitments() {
    let (request, profile) = fixture(RiskClass::Low, CanonicalRiskRuleV1::HighOnlySlowPath);
    let (scoring, assignment) = commitments(&request, &profile);
    let payload =
        canonical_runtime_commitment_payload_v2(&request, &profile, &scoring, &assignment)
            .expect("runtime payload");
    assert!(!payload.is_empty());

    let mut drifted = scoring;
    drifted.scored_outputs_digest = d("wrong-scores");
    assert_eq!(
        canonical_runtime_commitment_payload_v2(&request, &profile, &drifted, &assignment,),
        Err(ProductionPolicyError::ScoringDigestMismatch)
    );
}

#[test]
fn ppm_overflow_is_rejected_before_policy_admission() {
    let (mut request, profile) = fixture(RiskClass::Low, CanonicalRiskRuleV1::HighOnlySlowPath);
    request.maximum_ece_ppm = PPM_SCALE + 1;
    let error = decide_calibrated_v4(request, &profile).expect_err("overflow must fail");
    assert_eq!(error.code(), "intuition.policy.bound.ppm_out_of_range");
}
