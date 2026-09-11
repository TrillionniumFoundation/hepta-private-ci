use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid test id: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn probability(raw: u64) -> ProbabilityQ32 {
    ProbabilityQ32::from_raw(raw).unwrap_or_else(|error| panic!("valid probability: {error:?}"))
}

fn candidate(
    name: &str,
    utility: i64,
    confidence: u64,
    ood: u64,
    assignment: u64,
) -> CalibratedActionCandidateV1 {
    CalibratedActionCandidateV1 {
        candidate_id: id(name),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::from_raw(utility),
        calibrated_confidence: probability(confidence),
        ood_score: probability(ood),
        assignment_probability: probability(assignment),
        support_digest: digest(name.as_bytes()),
    }
}

fn request_with(
    candidates: Vec<CalibratedActionCandidateV1>,
    assignment: AssignmentModeV1,
) -> CalibratedDecisionRequestV1 {
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates)
        .unwrap_or_else(|error| panic!("candidate digest: {error:?}"));
    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates)
        .unwrap_or_else(|error| panic!("candidate order digest: {error:?}"));
    CalibratedDecisionRequestV1 {
        decision_id: id("decision:calibrated"),
        objective_digest: digest(b"objective"),
        objective_class_digest: digest(b"objective-class"),
        state_digest: digest(b"state"),
        policy_digest: digest(b"policy"),
        policy_generation: 7,
        sequence: 10,
        minimum_confidence: probability(ProbabilityQ32::ONE.raw() / 2),
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest(b"complete-receipt"),
            generator_digest: digest(b"generator"),
            grammar_digest: digest(b"grammar"),
            hard_filter_digest: digest(b"hard-filter"),
            truncation_digest: digest(b"truncation"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: candidates.len() as u32,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: digest(b"calibration"),
            policy_digest: digest(b"policy"),
            objective_class_digest: digest(b"objective-class"),
            generation: 7,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            measured_ece_ppm: 10_000,
            subgroup_audit_digest: digest(b"subgroup-audit"),
        },
        ood: OodArtifactV1 {
            artifact_digest: digest(b"ood"),
            policy_digest: digest(b"policy"),
            detector_digest: digest(b"ood-detector"),
            support_digest: digest(b"ood-support"),
            generation: 7,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: probability(ProbabilityQ32::ONE.raw() / 4),
            measured_false_acceptance_ppm: 1_000,
        },
        assignment,
        candidates,
    }
}

#[test]
fn deterministic_profile_selects_only_supported_calibrated_candidate() {
    let request = request_with(
        vec![
            candidate("candidate:a", 10, ProbabilityQ32::ONE.raw(), 0, 0),
            candidate("candidate:b", 20, ProbabilityQ32::ONE.raw(), 0, 0),
        ],
        AssignmentModeV1::Deterministic,
    );
    let receipt =
        decide_calibrated(request).unwrap_or_else(|error| panic!("calibrated decision: {error:?}"));
    assert_eq!(
        receipt.disposition,
        CalibratedDispositionV1::Selected(id("candidate:b"))
    );
    assert_eq!(
        receipt
            .propensities
            .iter()
            .find(|row| row.candidate_id == id("candidate:b"))
            .map(|row| row.probability),
        Some(ProbabilityQ32::ONE)
    );
    assert_eq!(receipt.abstain_probability, ProbabilityQ32::ZERO);
    assert_eq!(receipt.slow_path_probability, ProbabilityQ32::ZERO);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn high_risk_forces_slow_path_without_candidate_propensity() {
    let mut request = request_with(
        vec![candidate(
            "candidate:a",
            10,
            ProbabilityQ32::ONE.raw(),
            0,
            0,
        )],
        AssignmentModeV1::Deterministic,
    );
    request.risk_class = RiskClass::High;
    let receipt =
        decide_calibrated(request).unwrap_or_else(|error| panic!("high-risk slow path: {error:?}"));
    assert_eq!(
        receipt.disposition,
        CalibratedDispositionV1::SlowPath(SlowPathReasonV1::HighRisk)
    );
    assert!(
        receipt
            .propensities
            .iter()
            .all(|row| row.probability == ProbabilityQ32::ZERO)
    );
    assert_eq!(receipt.slow_path_probability, ProbabilityQ32::ONE);
}

#[test]
fn out_of_distribution_candidate_cannot_be_selected() {
    let mut value = candidate(
        "candidate:a",
        100,
        ProbabilityQ32::ONE.raw(),
        ProbabilityQ32::ONE.raw(),
        0,
    );
    value.ood_score = ProbabilityQ32::ONE;
    let request = request_with(vec![value], AssignmentModeV1::Deterministic);
    let receipt =
        decide_calibrated(request).unwrap_or_else(|error| panic!("OOD decision: {error:?}"));
    assert_eq!(
        receipt.disposition,
        CalibratedDispositionV1::SlowPath(SlowPathReasonV1::OutOfDistribution)
    );
}

#[test]
fn stale_calibration_artifact_rejects_before_selection() {
    let mut request = request_with(
        vec![candidate(
            "candidate:a",
            10,
            ProbabilityQ32::ONE.raw(),
            0,
            0,
        )],
        AssignmentModeV1::Deterministic,
    );
    request.sequence = 101;
    assert_eq!(
        decide_calibrated(request),
        Err(CalibratedError::ArtifactExpired)
    );
}

#[test]
fn candidate_set_substitution_is_rejected() {
    let mut request = request_with(
        vec![candidate(
            "candidate:a",
            10,
            ProbabilityQ32::ONE.raw(),
            0,
            0,
        )],
        AssignmentModeV1::Deterministic,
    );
    request.completeness.candidate_set_digest = digest(b"forged-set");
    assert_eq!(
        decide_calibrated(request),
        Err(CalibratedError::CandidateSetMismatch)
    );
}

#[test]
fn randomized_assignment_uses_exact_logged_distribution() {
    let half = ProbabilityQ32::ONE.raw() / 2;
    let request = request_with(
        vec![
            candidate("candidate:a", 10, ProbabilityQ32::ONE.raw(), 0, half),
            candidate("candidate:b", 20, ProbabilityQ32::ONE.raw(), 0, half),
        ],
        AssignmentModeV1::CounterBased {
            random_stream_digest: digest(b"random-stream"),
            draw: probability(half),
            abstain_probability: ProbabilityQ32::ZERO,
        },
    );
    let receipt =
        decide_calibrated(request).unwrap_or_else(|error| panic!("randomized decision: {error:?}"));
    assert_eq!(
        receipt.disposition,
        CalibratedDispositionV1::Selected(id("candidate:b"))
    );
    assert_eq!(
        receipt
            .propensities
            .iter()
            .map(|row| u128::from(row.probability.raw()))
            .sum::<u128>(),
        u128::from(ProbabilityQ32::ONE.raw())
    );
}

#[test]
fn randomized_probability_for_ood_candidate_is_rejected() {
    let mut excluded = candidate(
        "candidate:a",
        10,
        ProbabilityQ32::ONE.raw(),
        ProbabilityQ32::ONE.raw(),
        ProbabilityQ32::ONE.raw(),
    );
    excluded.ood_score = ProbabilityQ32::ONE;
    let request = request_with(
        vec![excluded],
        AssignmentModeV1::CounterBased {
            random_stream_digest: digest(b"random-stream"),
            draw: ProbabilityQ32::ZERO,
            abstain_probability: ProbabilityQ32::ZERO,
        },
    );
    assert_eq!(
        decide_calibrated(request),
        Err(CalibratedError::ProbabilityForIneligibleCandidate(
            "candidate:a".to_string()
        ))
    );
}

#[test]
fn calibration_quality_gate_fails_closed() {
    let mut request = request_with(
        vec![candidate(
            "candidate:a",
            10,
            ProbabilityQ32::ONE.raw(),
            0,
            0,
        )],
        AssignmentModeV1::Deterministic,
    );
    request.calibration.measured_ece_ppm = request.maximum_ece_ppm + 1;
    assert_eq!(
        decide_calibrated(request),
        Err(CalibratedError::CalibrationQualityInsufficient)
    );
}

#[test]
fn canonical_candidate_order_is_required() {
    let candidates = vec![
        candidate("candidate:b", 10, ProbabilityQ32::ONE.raw(), 0, 0),
        candidate("candidate:a", 20, ProbabilityQ32::ONE.raw(), 0, 0),
    ];
    let request = request_with(candidates, AssignmentModeV1::Deterministic);
    assert_eq!(
        decide_calibrated(request),
        Err(CalibratedError::NonCanonicalCandidateOrder)
    );
}

