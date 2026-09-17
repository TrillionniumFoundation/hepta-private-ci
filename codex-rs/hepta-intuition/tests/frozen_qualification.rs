use codex_hepta_intuition::calibrated::AssignmentModeV1;
use codex_hepta_intuition::calibrated::CalibratedActionCandidateV1;
use codex_hepta_intuition::calibrated::CalibratedDecisionRequestV1;
use codex_hepta_intuition::calibrated::CalibratedDispositionV1;
use codex_hepta_intuition::calibrated::CalibratedError;
use codex_hepta_intuition::calibrated::CalibrationArtifactV1;
use codex_hepta_intuition::calibrated::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::calibrated::OodArtifactV1;
use codex_hepta_intuition::calibrated::RiskClass;
use codex_hepta_intuition::calibrated::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::calibrated::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::calibrated::decide_calibrated_v2;
use codex_hepta_intuition::qualification::CanonicalPolicyProfileV1;
use codex_hepta_intuition::qualification::LearnedScorerContractV1;
use codex_hepta_intuition::qualification::QualificationError;
use codex_hepta_intuition::qualification::QualificationVerifierV1;
use codex_hepta_intuition::qualification::SignedCandidateCompletenessV1;
use codex_hepta_intuition::qualification::SignedPolicyQualificationV1;
use codex_hepta_intuition::qualification::canonical_calibration_artifact_digest_v1;
use codex_hepta_intuition::qualification::canonical_candidate_completeness_digest_v1;
use codex_hepta_intuition::qualification::canonical_ood_artifact_digest_v1;
use codex_hepta_intuition::qualification::canonical_policy_profile_digest_v1;
use codex_hepta_intuition::qualification::canonical_policy_qualification_digest_v1;
use codex_hepta_intuition::qualification::canonical_scorer_contract_digest_v1;
use codex_hepta_intuition::qualification::decide_qualified_v3;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer as _;
use ed25519_dalek::SigningKey;
use serde::Deserialize;

const MODEL_JSON: &str =
    include_str!("../../../qualification/intuition-policy-v3/frozen_model_v1.json");
const VALIDATION_JSON: &str =
    include_str!("../../../qualification/intuition-policy-v3/frozen_validation_v1.json");

#[derive(Debug, Deserialize)]
struct FrozenModel {
    schema_version: u32,
    model_id: String,
    feature_schema: String,
    weights: [i64; 2],
    bias: i64,
    confidence_floor_ppm: u32,
    confidence_step_ppm: u32,
    ood_novelty_abs_threshold: i64,
}

#[derive(Debug, Deserialize)]
struct FrozenDataset {
    schema_version: u32,
    dataset_id: String,
    rows: Vec<FrozenRow>,
}

#[derive(Debug, Deserialize)]
struct FrozenRow {
    id: String,
    features: [i64; 2],
    label: bool,
    ood: bool,
}

#[derive(Clone, Copy, Debug)]
struct ScoredRow {
    utility: i64,
    confidence_ppm: u32,
    ood_score_ppm: u32,
    predicted_label: bool,
}

struct QualifiedFixture {
    request: CalibratedDecisionRequestV1,
    qualification: SignedPolicyQualificationV1,
    completeness: SignedCandidateCompletenessV1,
    verifier: QualificationVerifierV1,
    selected_id: StableId,
    measured_ece_ppm: u32,
    measured_ood_far_ppm: u32,
}

#[test]
fn frozen_model_to_signed_qualification_to_policy_decision() {
    let fixture = build_fixture();
    assert!(fixture.measured_ece_ppm <= 200_000);
    assert_eq!(fixture.measured_ood_far_ppm, 0);

    let receipt = decide_qualified_v3(
        fixture.request,
        &fixture.qualification,
        &fixture.completeness,
        &fixture.verifier,
    )
    .unwrap_or_else(|error| panic!("qualified decision: {error:?}"));

    assert_eq!(
        receipt.decision.disposition,
        CalibratedDispositionV1::Selected(fixture.selected_id)
    );
    assert!(!receipt.authority.grants_any());
    assert!(!receipt.decision.authority.grants_any());
}

#[test]
fn v2_rejects_nonzero_omitted_count_inside_intuition_crate() {
    let mut fixture = build_fixture();
    fixture.request.completeness.omitted_count_bound = 1;
    assert_eq!(
        decide_calibrated_v2(fixture.request),
        Err(CalibratedError::CandidateSetMismatch)
    );
}

#[test]
fn qualified_v3_rejects_request_threshold_override() {
    let mut fixture = build_fixture();
    fixture.request.maximum_ece_ppm = 1_000_000;
    assert_eq!(
        decide_qualified_v3(
            fixture.request,
            &fixture.qualification,
            &fixture.completeness,
            &fixture.verifier,
        ),
        Err(QualificationError::PolicyProfileMismatch)
    );
}

#[test]
fn qualified_v3_rejects_tampered_qualification_signature() {
    let mut fixture = build_fixture();
    fixture.qualification.signature[0] ^= 1;
    assert_eq!(
        decide_qualified_v3(
            fixture.request,
            &fixture.qualification,
            &fixture.completeness,
            &fixture.verifier,
        ),
        Err(QualificationError::SignatureInvalid)
    );
}

fn build_fixture() -> QualifiedFixture {
    let model: FrozenModel = serde_json::from_str(MODEL_JSON)
        .unwrap_or_else(|error| panic!("parse frozen model: {error}"));
    let dataset: FrozenDataset = serde_json::from_str(VALIDATION_JSON)
        .unwrap_or_else(|error| panic!("parse frozen dataset: {error}"));
    assert_eq!(model.schema_version, 1);
    assert_eq!(dataset.schema_version, 1);
    assert!(!model.model_id.is_empty());
    assert!(!dataset.dataset_id.is_empty());

    let scored = dataset
        .rows
        .iter()
        .map(|row| score(&model, row))
        .collect::<Vec<_>>();
    let measured_ece_ppm = expected_calibration_error_ppm(&dataset.rows, &scored);
    let maximum_in_domain_ood_ppm = 250_000;
    let measured_ood_far_ppm =
        ood_false_acceptance_ppm(&dataset.rows, &scored, maximum_in_domain_ood_ppm);

    let policy_digest = digest(b"intuition-policy:v3:frozen-qualification");
    let objective_class_digest = digest(b"objective-class:adaptive-intervention");
    let support_digest = digest(b"support:frozen-validation-v1");

    let mut calibration = CalibrationArtifactV1 {
        artifact_digest: digest(b"pending-calibration-digest"),
        policy_digest,
        objective_class_digest,
        generation: 7,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        measured_ece_ppm,
        subgroup_audit_digest: digest(b"subgroup-audit:frozen-v1"),
    };
    calibration.artifact_digest = canonical_calibration_artifact_digest_v1(&calibration)
        .unwrap_or_else(|error| panic!("calibration digest: {error:?}"));

    let mut ood = OodArtifactV1 {
        artifact_digest: digest(b"pending-ood-digest"),
        policy_digest,
        detector_digest: digest(b"ood-detector:novelty-abs-v1"),
        support_digest,
        generation: 7,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        maximum_in_domain_score: probability_from_ppm(maximum_in_domain_ood_ppm),
        measured_false_acceptance_ppm: measured_ood_far_ppm,
    };
    ood.artifact_digest = canonical_ood_artifact_digest_v1(&ood)
        .unwrap_or_else(|error| panic!("OOD digest: {error:?}"));

    let scorer = LearnedScorerContractV1 {
        owner_id: id("scorer-owner:intuition"),
        scorer_service_digest: digest(b"scorer-service:external-v1"),
        model_digest: Digest32::of_bytes(MODEL_JSON.as_bytes()),
        feature_schema_digest: Digest32::of_bytes(model.feature_schema.as_bytes()),
        score_semantics_digest: digest(
            b"utility=linear-score;confidence=correctness-confidence;ood=novelty-threshold",
        ),
        calibration_link_digest: calibration.artifact_digest,
        support_digest,
    };
    let scorer_contract_digest = canonical_scorer_contract_digest_v1(&scorer)
        .unwrap_or_else(|error| panic!("scorer contract digest: {error:?}"));

    let profile = CanonicalPolicyProfileV1 {
        policy_digest,
        objective_class_digest,
        generation: 7,
        minimum_confidence: probability_from_ppm(700_000),
        maximum_ece_ppm: 200_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        allow_elevated_risk_direct: false,
        high_risk_forces_slow_path: true,
        scorer,
    };
    let profile_digest = canonical_policy_profile_digest_v1(&profile)
        .unwrap_or_else(|error| panic!("profile digest: {error:?}"));

    let signer = SigningKey::from_bytes(&[0x5a; 32]);
    let issuer_id = id("qualification:intuition-policy");
    let report = format!(
        "model={};dataset={};ece_ppm={};ood_far_ppm={}",
        model.model_id, dataset.dataset_id, measured_ece_ppm, measured_ood_far_ppm
    );
    let mut qualification = SignedPolicyQualificationV1 {
        issuer_id: issuer_id.clone(),
        issuer_epoch: 1,
        profile,
        calibration: calibration.clone(),
        ood: ood.clone(),
        frozen_validation_data_digest: Digest32::of_bytes(VALIDATION_JSON.as_bytes()),
        qualification_report_digest: Digest32::of_bytes(report.as_bytes()),
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        signature: [0; 64],
    };
    let qualification_digest = canonical_policy_qualification_digest_v1(&qualification)
        .unwrap_or_else(|error| panic!("qualification digest: {error:?}"));
    qualification.signature = signer.sign(qualification_digest.as_array()).to_bytes();

    let decision_row = dataset
        .rows
        .iter()
        .zip(scored.iter())
        .find(|(row, _)| !row.ood)
        .unwrap_or_else(|| panic!("frozen dataset contains an in-domain row"));
    let selected_id = id("candidate:model-action");
    let candidates = vec![CalibratedActionCandidateV1 {
        candidate_id: selected_id.clone(),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::from_raw(decision_row.1.utility),
        calibrated_confidence: probability_from_ppm(decision_row.1.confidence_ppm),
        ood_score: probability_from_ppm(decision_row.1.ood_score_ppm),
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest,
    }];
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates)
        .unwrap_or_else(|error| panic!("candidate set digest: {error:?}"));
    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates)
        .unwrap_or_else(|error| panic!("candidate order digest: {error:?}"));
    let completeness_binding = CandidateSetCompletenessBindingV1 {
        receipt_digest: digest(b"pending-completeness-receipt"),
        generator_digest: digest(b"candidate-generator:frozen-v1"),
        grammar_digest: digest(b"candidate-grammar:frozen-v1"),
        hard_filter_digest: digest(b"hard-filter:frozen-v1"),
        truncation_digest: digest(b"no-truncation:frozen-v1"),
        candidate_set_digest,
        canonical_order_digest,
        candidate_count: candidates.len() as u32,
        omitted_count_bound: 0,
    };

    let objective_digest = digest(b"objective:frozen-decision-v1");
    let state_digest = Digest32::of_bytes(decision_row.0.id.as_bytes());
    let decision_id = id("decision:frozen-qualified-v3");
    let mut completeness = SignedCandidateCompletenessV1 {
        issuer_id: issuer_id.clone(),
        issuer_epoch: 1,
        decision_id: decision_id.clone(),
        objective_digest,
        objective_class_digest,
        state_digest,
        policy_digest,
        policy_generation: 7,
        sequence: 10,
        policy_profile_digest: profile_digest,
        scorer_contract_digest,
        completeness: completeness_binding,
        signature: [0; 64],
    };
    let completeness_digest = canonical_candidate_completeness_digest_v1(&completeness)
        .unwrap_or_else(|error| panic!("completeness digest: {error:?}"));
    completeness.completeness.receipt_digest = completeness_digest;
    completeness.signature = signer.sign(completeness_digest.as_array()).to_bytes();

    let request = CalibratedDecisionRequestV1 {
        decision_id,
        objective_digest,
        objective_class_digest,
        state_digest,
        policy_digest,
        policy_generation: 7,
        sequence: 10,
        minimum_confidence: qualification.profile.minimum_confidence,
        maximum_ece_ppm: qualification.profile.maximum_ece_ppm,
        maximum_ood_false_acceptance_ppm: qualification
            .profile
            .maximum_ood_false_acceptance_ppm,
        risk_class: RiskClass::Low,
        completeness: completeness.completeness.clone(),
        calibration,
        ood,
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };
    let verifier = QualificationVerifierV1::from_bytes(
        issuer_id,
        1,
        signer.verifying_key().to_bytes(),
        policy_digest,
        7,
        profile_digest,
    )
    .unwrap_or_else(|error| panic!("qualification verifier: {error:?}"));

    QualifiedFixture {
        request,
        qualification,
        completeness,
        verifier,
        selected_id,
        measured_ece_ppm,
        measured_ood_far_ppm,
    }
}

fn score(model: &FrozenModel, row: &FrozenRow) -> ScoredRow {
    let utility = model.bias
        + model.weights[0] * row.features[0]
        + model.weights[1] * row.features[1];
    let magnitude = utility.unsigned_abs().min(u64::from(u32::MAX));
    let extra = magnitude.saturating_mul(u64::from(model.confidence_step_ppm));
    let confidence_ppm = u64::from(model.confidence_floor_ppm)
        .saturating_add(extra)
        .min(990_000) as u32;
    let ood_score_ppm = if row.features[1].abs() >= model.ood_novelty_abs_threshold {
        1_000_000
    } else {
        0
    };
    ScoredRow {
        utility,
        confidence_ppm,
        ood_score_ppm,
        predicted_label: utility >= 0,
    }
}

fn expected_calibration_error_ppm(rows: &[FrozenRow], scored: &[ScoredRow]) -> u32 {
    let mut count = [0u64; 10];
    let mut confidence_sum = [0u64; 10];
    let mut correct = [0u64; 10];
    let mut total = 0u64;
    for (row, score) in rows.iter().zip(scored.iter()) {
        if row.ood {
            continue;
        }
        let bin = usize::try_from(score.confidence_ppm / 100_000)
            .unwrap_or(9)
            .min(9);
        count[bin] += 1;
        confidence_sum[bin] += u64::from(score.confidence_ppm);
        correct[bin] += if score.predicted_label == row.label { 1 } else { 0 };
        total += 1;
    }
    let mut weighted_error = 0u64;
    for bin in 0..10 {
        if count[bin] == 0 {
            continue;
        }
        let average_confidence = confidence_sum[bin] / count[bin];
        let accuracy_ppm = correct[bin] * 1_000_000 / count[bin];
        weighted_error += average_confidence.abs_diff(accuracy_ppm) * count[bin];
    }
    u32::try_from(weighted_error / total).unwrap_or_else(|_| panic!("ECE must fit in ppm"))
}

fn ood_false_acceptance_ppm(
    rows: &[FrozenRow],
    scored: &[ScoredRow],
    maximum_in_domain_ood_ppm: u32,
) -> u32 {
    let mut ood_rows = 0u64;
    let mut accepted = 0u64;
    for (row, score) in rows.iter().zip(scored.iter()) {
        if !row.ood {
            continue;
        }
        ood_rows += 1;
        accepted += if score.ood_score_ppm <= maximum_in_domain_ood_ppm {
            1
        } else {
            0
        };
    }
    if ood_rows == 0 {
        return 0;
    }
    u32::try_from(accepted * 1_000_000 / ood_rows)
        .unwrap_or_else(|_| panic!("OOD FAR must fit in ppm"))
}

fn probability_from_ppm(ppm: u32) -> ProbabilityQ32 {
    let raw = u128::from(ProbabilityQ32::ONE.raw()) * u128::from(ppm) / 1_000_000u128;
    ProbabilityQ32::from_raw(raw as u64)
        .unwrap_or_else(|error| panic!("valid ppm probability: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id {value}: {error:?}"))
}
