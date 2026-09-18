use super::*;
use crate::calibrated::AssignmentModeV1;
use crate::calibrated::CalibratedActionCandidateV1;
use crate::calibrated::CalibratedDecisionRequestV1;
use crate::calibrated::CalibratedDispositionV1;
use crate::calibrated::CalibratedError;
use crate::calibrated::CalibrationArtifactV1;
use crate::calibrated::CandidateSetCompletenessBindingV1;
use crate::calibrated::OodArtifactV1;
use crate::calibrated::RiskClass;
use crate::calibrated::canonical_candidate_order_digest_v1;
use crate::calibrated::canonical_candidate_set_digest_v1;
use crate::calibrated::decide_calibrated_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

struct Fixture {
    artifact_key: QualificationMacKeyV1,
    scorer_key: QualificationMacKeyV1,
    assignment_key: QualificationMacKeyV1,
    subject_id: StableId,
    request: CalibratedDecisionRequestV1,
    profile: CanonicalPolicyProfileV1,
    scorer_contract: LearnedScorerContractV1,
    score_evidence: Vec<LearnedScoreEvidenceV1>,
    profile_mac: QualificationMacV1,
    calibration_mac: QualificationMacV1,
    ood_mac: QualificationMacV1,
    completeness_mac: QualificationMacV1,
    scorer_mac: QualificationMacV1,
    assignment_mac: QualificationMacV1,
}

impl Fixture {
    fn new() -> Result<Self, QualifiedError> {
        let artifact_key = QualificationMacKeyV1::from_trusted_bytes(
            id("qualification:key:artifact"),
            3,
            [0x11; 32],
            false,
        );
        let scorer_key = QualificationMacKeyV1::from_trusted_bytes(
            id("qualification:key:scorer"),
            9,
            [0x22; 32],
            false,
        );
        let assignment_key = QualificationMacKeyV1::from_trusted_bytes(
            id("qualification:key:assignment"),
            11,
            [0x33; 32],
            false,
        );
        let subject_id = id("intuition:policy:production");
        let mut candidates = vec![candidate("candidate:a", 10), candidate("candidate:b", 20)];
        candidates[1].assignment_probability = ProbabilityQ32::ONE;
        let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates)?;
        let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates)?;
        let policy_digest = digest(b"policy");
        let objective_class_digest = digest(b"objective-class");
        let state_digest = digest(b"state");
        let generation = 7;
        let sequence = 10;

        let mut calibration = CalibrationArtifactV1 {
            artifact_digest: Digest32::ZERO,
            policy_digest,
            objective_class_digest,
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            measured_ece_ppm: 10_000,
            subgroup_audit_digest: digest(b"subgroup-audit"),
        };
        calibration.artifact_digest = canonical_calibration_artifact_digest_v1(&calibration);

        let mut ood = OodArtifactV1 {
            artifact_digest: Digest32::ZERO,
            policy_digest,
            detector_digest: digest(b"ood-detector"),
            support_digest: digest(b"ood-support"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: probability_ppm(250_000),
            measured_false_acceptance_ppm: 1_000,
        };
        ood.artifact_digest = canonical_ood_artifact_digest_v1(&ood);

        let mut completeness = CandidateSetCompletenessBindingV1 {
            receipt_digest: Digest32::ZERO,
            generator_digest: digest(b"generator"),
            grammar_digest: digest(b"grammar"),
            hard_filter_digest: digest(b"hard-filter"),
            truncation_digest: digest(b"truncation"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: candidates.len() as u32,
            omitted_count_bound: 0,
        };
        completeness.receipt_digest = canonical_completeness_receipt_digest_v1(
            &completeness,
            state_digest,
            policy_digest,
            generation,
            sequence,
        );

        let mut scorer_contract = LearnedScorerContractV1 {
            contract_digest: Digest32::ZERO,
            policy_digest,
            objective_class_digest,
            model_artifact_digest: digest(b"model-artifact"),
            feature_schema_digest: digest(b"feature-schema"),
            utility_semantics_digest: digest(b"utility-semantics"),
            confidence_semantics_digest: digest(b"confidence-semantics"),
            ood_semantics_digest: digest(b"ood-semantics"),
            calibration_artifact_digest: calibration.artifact_digest,
            ood_artifact_digest: ood.artifact_digest,
            ood_detector_digest: ood.detector_digest,
            generation,
        };
        scorer_contract.contract_digest = canonical_scorer_contract_digest_v1(&scorer_contract);

        let mut profile = CanonicalPolicyProfileV1 {
            profile_digest: Digest32::ZERO,
            policy_digest,
            objective_class_digest,
            scorer_contract_digest: scorer_contract.contract_digest,
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            minimum_confidence: probability_ppm(500_000),
            maximum_ece_ppm: 50_000,
            maximum_ood_false_acceptance_ppm: 5_000,
            risk_policy: RiskPolicyV1::HighAlwaysSlowPath,
            require_zero_omissions: true,
        };
        profile.profile_digest = canonical_policy_profile_digest_v1(&profile)?;

        let request = CalibratedDecisionRequestV1 {
            decision_id: id("decision:qualified"),
            objective_digest: digest(b"objective"),
            objective_class_digest,
            state_digest,
            policy_digest,
            policy_generation: generation,
            sequence,
            minimum_confidence: profile.minimum_confidence,
            maximum_ece_ppm: profile.maximum_ece_ppm,
            maximum_ood_false_acceptance_ppm: profile.maximum_ood_false_acceptance_ppm,
            risk_class: RiskClass::Low,
            completeness,
            calibration,
            ood,
            assignment: AssignmentModeV1::CounterBased {
                random_stream_digest: digest(b"qualified-random-stream"),
                draw: ProbabilityQ32::ZERO,
                abstain_probability: ProbabilityQ32::ZERO,
            },
            candidates,
        };

        let score_evidence = request
            .candidates
            .iter()
            .map(|candidate| LearnedScoreEvidenceV1 {
                candidate_id: candidate.candidate_id.clone(),
                feature_digest: digest(candidate.candidate_id.as_str().as_bytes()),
                utility: candidate.utility,
                calibrated_confidence: candidate.calibrated_confidence,
                ood_score: candidate.ood_score,
                support_digest: candidate.support_digest,
            })
            .collect::<Vec<_>>();
        let scorer_output_digest = canonical_scorer_output_digest_v1(
            &request.decision_id,
            request.state_digest,
            scorer_contract.contract_digest,
            scorer_contract.model_artifact_digest,
            &score_evidence,
        )?;
        let assignment_digest = canonical_assignment_digest_v1(
            &request,
            profile.profile_digest,
            scorer_output_digest,
        )?;

        let profile_mac = issue_qualification_mac_v1(
            &artifact_key,
            subject_id.clone(),
            policy_profile_scope_digest_v1(),
            profile.profile_digest,
            generation,
            1,
            100,
        )?;
        let calibration_mac = issue_qualification_mac_v1(
            &artifact_key,
            subject_id.clone(),
            calibration_scope_digest_v1(),
            request.calibration.artifact_digest,
            generation,
            1,
            100,
        )?;
        let ood_mac = issue_qualification_mac_v1(
            &artifact_key,
            subject_id.clone(),
            ood_scope_digest_v1(),
            request.ood.artifact_digest,
            generation,
            1,
            100,
        )?;
        let completeness_mac = issue_qualification_mac_v1(
            &artifact_key,
            subject_id.clone(),
            completeness_scope_digest_v1(),
            request.completeness.receipt_digest,
            generation,
            sequence,
            sequence,
        )?;
        let scorer_mac = issue_qualification_mac_v1(
            &scorer_key,
            subject_id.clone(),
            scorer_output_scope_digest_v1(),
            scorer_output_digest,
            generation,
            sequence,
            sequence,
        )?;
        let assignment_mac = issue_qualification_mac_v1(
            &assignment_key,
            subject_id.clone(),
            assignment_scope_digest_v1(),
            assignment_digest,
            generation,
            sequence,
            sequence,
        )?;

        Ok(Self {
            artifact_key,
            scorer_key,
            assignment_key,
            subject_id,
            request,
            profile,
            scorer_contract,
            score_evidence,
            profile_mac,
            calibration_mac,
            ood_mac,
            completeness_mac,
            scorer_mac,
            assignment_mac,
        })
    }

    fn decide(&self) -> Result<QualifiedIntuitionReceiptV1, QualifiedError> {
        decide_qualified_v1(
            QualifiedDecisionRequestV1 {
                request: self.request.clone(),
                profile: self.profile.clone(),
                scorer_contract: self.scorer_contract.clone(),
                score_evidence: self.score_evidence.clone(),
                artifacts: QualifiedArtifactsV1 {
                    profile: &self.profile_mac,
                    calibration: &self.calibration_mac,
                    ood: &self.ood_mac,
                    completeness: &self.completeness_mac,
                    scorer_output: &self.scorer_mac,
                    assignment: &self.assignment_mac,
                },
            },
            QualificationTrustV1 {
                artifact_key: &self.artifact_key,
                scorer_key: &self.scorer_key,
                assignment_key: &self.assignment_key,
                subject_id: &self.subject_id,
                expected_generation: self.request.policy_generation,
            },
        )
    }
}

#[test]
fn qualified_path_requires_authenticated_current_generation_material() {
    let fixture = Fixture::new().unwrap_or_else(|error| panic!("fixture: {error:?}"));
    let receipt = fixture
        .decide()
        .unwrap_or_else(|error| panic!("qualified decision: {error:?}"));
    assert_eq!(
        receipt.decision.disposition,
        CalibratedDispositionV1::Selected(id("candidate:b"))
    );
    assert!(!receipt.authority.grants_any());
}

#[test]
fn request_thresholds_cannot_override_authenticated_profile() {
    let mut fixture = Fixture::new().unwrap_or_else(|error| panic!("fixture: {error:?}"));
    fixture.request.minimum_confidence = ProbabilityQ32::ZERO;
    assert_eq!(fixture.decide(), Err(QualifiedError::ProfileThresholdMismatch));
}

#[test]
fn artifact_body_substitution_is_rejected_before_mac_admission() {
    let mut fixture = Fixture::new().unwrap_or_else(|error| panic!("fixture: {error:?}"));
    fixture.request.calibration.measured_ece_ppm += 1;
    assert_eq!(
        fixture.decide(),
        Err(QualifiedError::ArtifactDigestMismatch("calibration"))
    );
}

#[test]
fn authentication_tag_tampering_is_rejected() {
    let mut fixture = Fixture::new().unwrap_or_else(|error| panic!("fixture: {error:?}"));
    fixture.profile_mac.tag = digest(b"tampered-tag");
    assert_eq!(fixture.decide(), Err(QualifiedError::AuthenticationTagMismatch));
}

#[test]
fn assignment_probability_tampering_requires_assignment_authority() {
    let mut fixture = Fixture::new().unwrap_or_else(|error| panic!("fixture: {error:?}"));
    fixture.request.candidates[0].assignment_probability = ProbabilityQ32::ONE;
    fixture.request.candidates[1].assignment_probability = ProbabilityQ32::ZERO;
    assert_eq!(
        fixture.decide(),
        Err(QualifiedError::AuthenticationPayloadMismatch)
    );
}

#[test]
fn random_stream_and_draw_tampering_require_assignment_authority() {
    let mut stream_fixture =
        Fixture::new().unwrap_or_else(|error| panic!("fixture: {error:?}"));
    if let AssignmentModeV1::CounterBased {
        random_stream_digest,
        ..
    } = &mut stream_fixture.request.assignment
    {
        *random_stream_digest = digest(b"tampered-random-stream");
    }
    assert_eq!(
        stream_fixture.decide(),
        Err(QualifiedError::AuthenticationPayloadMismatch)
    );

    let mut draw_fixture = Fixture::new().unwrap_or_else(|error| panic!("fixture: {error:?}"));
    if let AssignmentModeV1::CounterBased { draw, .. } = &mut draw_fixture.request.assignment {
        *draw = probability_ppm(1);
    }
    assert_eq!(
        draw_fixture.decide(),
        Err(QualifiedError::AuthenticationPayloadMismatch)
    );
}

#[test]
fn qualification_roles_require_distinct_key_identities() {
    let mut fixture = Fixture::new().unwrap_or_else(|error| panic!("fixture: {error:?}"));
    fixture.assignment_key = QualificationMacKeyV1::from_trusted_bytes(
        id("qualification:key:scorer"),
        12,
        [0x44; 32],
        false,
    );
    assert_eq!(
        fixture.decide(),
        Err(QualifiedError::AuthenticationKeyRoleConflict)
    );
}

#[test]
fn qualification_roles_require_distinct_key_material() {
    let mut fixture = Fixture::new().unwrap_or_else(|error| panic!("fixture: {error:?}"));
    fixture.assignment_key = QualificationMacKeyV1::from_trusted_bytes(
        id("qualification:key:assignment-alias"),
        12,
        [0x22; 32],
        false,
    );
    assert_eq!(
        fixture.decide(),
        Err(QualifiedError::AuthenticationKeyRoleConflict)
    );
}

#[test]
fn assignment_abstain_and_mode_tampering_require_assignment_authority() {
    let mut abstain_fixture =
        Fixture::new().unwrap_or_else(|error| panic!("fixture: {error:?}"));
    if let AssignmentModeV1::CounterBased {
        abstain_probability,
        ..
    } = &mut abstain_fixture.request.assignment
    {
        *abstain_probability = probability_ppm(1);
    }
    assert_eq!(
        abstain_fixture.decide(),
        Err(QualifiedError::AuthenticationPayloadMismatch)
    );

    let mut mode_fixture = Fixture::new().unwrap_or_else(|error| panic!("fixture: {error:?}"));
    mode_fixture.request.assignment = AssignmentModeV1::Deterministic;
    assert_eq!(
        mode_fixture.decide(),
        Err(QualifiedError::AuthenticationPayloadMismatch)
    );
}

#[test]
fn calibrated_bound_kernel_rejects_nonzero_omission_bound_itself() {
    let mut fixture = Fixture::new().unwrap_or_else(|error| panic!("fixture: {error:?}"));
    fixture.request.completeness.omitted_count_bound = 1;
    assert_eq!(
        decide_calibrated_v2(fixture.request),
        Err(CalibratedError::CandidateSetMismatch)
    );
}

#[test]
fn hmac_implementation_matches_known_sha256_vector() {
    let actual = hmac_sha256(&[0x0b; 32], b"Hi There");
    let expected = Digest32::from_array([
        0x19, 0x8a, 0x60, 0x7e, 0xb4, 0x4b, 0xfb, 0xc6, 0x99, 0x03, 0xa0, 0xf1, 0xcf, 0x2b,
        0xbd, 0xc5, 0xba, 0x0a, 0xa3, 0xf3, 0xd9, 0xae, 0x3c, 0x1c, 0x7a, 0x3b, 0x16, 0x96,
        0xa0, 0xb6, 0x8c, 0xf7,
    ]);
    assert_eq!(actual, expected);
}

fn candidate(name: &str, utility: i64) -> CalibratedActionCandidateV1 {
    CalibratedActionCandidateV1 {
        candidate_id: id(name),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::from_raw(utility),
        calibrated_confidence: probability_ppm(900_000),
        ood_score: ProbabilityQ32::ZERO,
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest: digest(name.as_bytes()),
    }
}

fn probability_ppm(ppm: u64) -> ProbabilityQ32 {
    let raw = (u128::from(ProbabilityQ32::ONE.raw()) * u128::from(ppm) / 1_000_000) as u64;
    ProbabilityQ32::from_raw(raw)
        .unwrap_or_else(|error| panic!("valid test probability: {error:?}"))
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid test id: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}
