use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::CalibratedActionCandidateV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::CalibrationArtifactV1;
use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::qualified::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

const MODEL_BYTES: &[u8] = include_bytes!(
    "../../../qualification/intuition-policy/frozen-v1/model.snapshot"
);
const VALIDATION: &str = include_str!(
    "../../../qualification/intuition-policy/frozen-v1/validation.csv"
);

#[derive(Clone, Copy, Debug)]
struct ReferenceModel {
    generation: u64,
    weight_ppm: i64,
    bias_ppm: i64,
    support_min_ppm: i64,
    support_max_ppm: i64,
}

#[derive(Clone, Copy, Debug)]
struct ValidationRow {
    feature_ppm: i64,
    label: u64,
    in_domain: bool,
}

#[test]
fn frozen_model_metrics_authenticate_and_drive_policy_decision() {
    let model = parse_model(std::str::from_utf8(MODEL_BYTES).unwrap_or_else(|error| {
        panic!("model snapshot must be utf8: {error:?}")
    }));
    let rows = parse_validation(VALIDATION);
    let model_digest = Digest32::of_bytes(MODEL_BYTES);
    let dataset_digest = Digest32::of_bytes(VALIDATION.as_bytes());
    let measured_ece_ppm = measured_ece_ppm(model, &rows);
    let ood_threshold_ppm = 250_000_u64;
    let measured_far_ppm = measured_ood_false_acceptance_ppm(model, &rows, ood_threshold_ppm);

    assert_eq!(measured_ece_ppm, 125_000);
    assert_eq!(measured_far_ppm, 0);

    let policy_digest = digest(b"frozen-policy-v1");
    let objective_class_digest = digest(b"frozen-objective-class-v1");
    let state_digest = digest(b"frozen-state-v1");
    let sequence = 42;

    let mut calibration = CalibrationArtifactV1 {
        artifact_digest: Digest32::ZERO,
        policy_digest,
        objective_class_digest,
        generation: model.generation,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        measured_ece_ppm,
        subgroup_audit_digest: dataset_digest,
    };
    calibration.artifact_digest = canonical_calibration_artifact_digest_v1(&calibration);

    let detector_digest = digest(b"reference-support-interval-ood-v1");
    let mut ood = OodArtifactV1 {
        artifact_digest: Digest32::ZERO,
        policy_digest,
        detector_digest,
        support_digest: dataset_digest,
        generation: model.generation,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        maximum_in_domain_score: probability_ppm(ood_threshold_ppm),
        measured_false_acceptance_ppm: measured_far_ppm,
    };
    ood.artifact_digest = canonical_ood_artifact_digest_v1(&ood);

    let scored = [900_000_i64, 950_000_i64]
        .into_iter()
        .map(|feature| scored_candidate(model, feature))
        .collect::<Vec<_>>();
    let candidates = scored
        .iter()
        .map(|(_, candidate)| candidate.clone())
        .collect::<Vec<_>>();
    let score_evidence = scored
        .iter()
        .map(|(evidence, _)| evidence.clone())
        .collect::<Vec<_>>();
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates)
        .unwrap_or_else(|error| panic!("candidate set digest: {error:?}"));
    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates)
        .unwrap_or_else(|error| panic!("candidate order digest: {error:?}"));
    let mut completeness = CandidateSetCompletenessBindingV1 {
        receipt_digest: Digest32::ZERO,
        generator_digest: digest(b"frozen-generator-v1"),
        grammar_digest: digest(b"frozen-grammar-v1"),
        hard_filter_digest: digest(b"frozen-hard-filter-v1"),
        truncation_digest: digest(b"no-truncation-v1"),
        candidate_set_digest,
        canonical_order_digest,
        candidate_count: u32::try_from(candidates.len())
            .unwrap_or_else(|error| panic!("candidate count: {error:?}")),
        omitted_count_bound: 0,
    };
    completeness.receipt_digest = canonical_completeness_receipt_digest_v1(
        &completeness,
        state_digest,
        policy_digest,
        model.generation,
        sequence,
    );

    let mut scorer_contract = LearnedScorerContractV1 {
        contract_digest: Digest32::ZERO,
        policy_digest,
        objective_class_digest,
        model_artifact_digest: model_digest,
        feature_schema_digest: digest(b"scalar-feature-ppm-v1"),
        utility_semantics_digest: digest(b"linear-score-centered-utility-v1"),
        confidence_semantics_digest: digest(b"binary-calibrated-confidence-v1"),
        ood_semantics_digest: detector_digest,
        calibration_artifact_digest: calibration.artifact_digest,
        ood_artifact_digest: ood.artifact_digest,
        ood_detector_digest: detector_digest,
        generation: model.generation,
    };
    scorer_contract.contract_digest = canonical_scorer_contract_digest_v1(&scorer_contract);

    let mut profile = CanonicalPolicyProfileV1 {
        profile_digest: Digest32::ZERO,
        policy_digest,
        objective_class_digest,
        scorer_contract_digest: scorer_contract.contract_digest,
        generation: model.generation,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        minimum_confidence: probability_ppm(800_000),
        maximum_ece_ppm: 150_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        risk_policy: RiskPolicyV1::HighAlwaysSlowPath,
        require_zero_omissions: true,
    };
    profile.profile_digest = canonical_policy_profile_digest_v1(&profile)
        .unwrap_or_else(|error| panic!("profile digest: {error:?}"));

    let request = CalibratedDecisionRequestV1 {
        decision_id: id("decision:frozen-qualification"),
        objective_digest: digest(b"frozen-objective-v1"),
        objective_class_digest,
        state_digest,
        policy_digest,
        policy_generation: model.generation,
        sequence,
        minimum_confidence: profile.minimum_confidence,
        maximum_ece_ppm: profile.maximum_ece_ppm,
        maximum_ood_false_acceptance_ppm: profile.maximum_ood_false_acceptance_ppm,
        risk_class: RiskClass::Low,
        completeness,
        calibration,
        ood,
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };
    let scorer_output_digest = canonical_scorer_output_digest_v1(
        &request.decision_id,
        request.state_digest,
        scorer_contract.contract_digest,
        scorer_contract.model_artifact_digest,
        &score_evidence,
    )
    .unwrap_or_else(|error| panic!("scorer output digest: {error:?}"));
    let assignment_digest = canonical_assignment_digest_v1(
        &request,
        profile.profile_digest,
        scorer_output_digest,
    )
    .unwrap_or_else(|error| panic!("assignment digest: {error:?}"));

    let artifact_key = QualificationMacKeyV1::from_trusted_bytes(
        id("qualification:key:frozen-artifacts"),
        1,
        [0x31; 32],
        false,
    );
    let scorer_key = QualificationMacKeyV1::from_trusted_bytes(
        id("qualification:key:frozen-scorer"),
        1,
        [0x52; 32],
        false,
    );
    let assignment_key = QualificationMacKeyV1::from_trusted_bytes(
        id("qualification:key:frozen-assignment"),
        1,
        [0x73; 32],
        false,
    );
    let subject_id = id("intuition:policy:frozen-v1");
    let profile_mac = issue_qualification_mac_v1(
        &artifact_key,
        subject_id.clone(),
        policy_profile_scope_digest_v1(),
        profile.profile_digest,
        model.generation,
        1,
        100,
    )
    .unwrap_or_else(|error| panic!("profile auth: {error:?}"));
    let calibration_mac = issue_qualification_mac_v1(
        &artifact_key,
        subject_id.clone(),
        calibration_scope_digest_v1(),
        request.calibration.artifact_digest,
        model.generation,
        1,
        100,
    )
    .unwrap_or_else(|error| panic!("calibration auth: {error:?}"));
    let ood_mac = issue_qualification_mac_v1(
        &artifact_key,
        subject_id.clone(),
        ood_scope_digest_v1(),
        request.ood.artifact_digest,
        model.generation,
        1,
        100,
    )
    .unwrap_or_else(|error| panic!("ood auth: {error:?}"));
    let completeness_mac = issue_qualification_mac_v1(
        &artifact_key,
        subject_id.clone(),
        completeness_scope_digest_v1(),
        request.completeness.receipt_digest,
        model.generation,
        sequence,
        sequence,
    )
    .unwrap_or_else(|error| panic!("completeness auth: {error:?}"));
    let scorer_mac = issue_qualification_mac_v1(
        &scorer_key,
        subject_id.clone(),
        scorer_output_scope_digest_v1(),
        scorer_output_digest,
        model.generation,
        sequence,
        sequence,
    )
    .unwrap_or_else(|error| panic!("scorer auth: {error:?}"));
    let assignment_mac = issue_qualification_mac_v1(
        &assignment_key,
        subject_id.clone(),
        assignment_scope_digest_v1(),
        assignment_digest,
        model.generation,
        sequence,
        sequence,
    )
    .unwrap_or_else(|error| panic!("assignment auth: {error:?}"));

    let receipt = decide_qualified_v1(
        QualifiedDecisionRequestV1 {
            request,
            profile,
            scorer_contract,
            score_evidence,
            artifacts: QualifiedArtifactsV1 {
                profile: &profile_mac,
                calibration: &calibration_mac,
                ood: &ood_mac,
                completeness: &completeness_mac,
                scorer_output: &scorer_mac,
                assignment: &assignment_mac,
            },
        },
        QualificationTrustV1 {
            artifact_key: &artifact_key,
            scorer_key: &scorer_key,
            assignment_key: &assignment_key,
            subject_id: &subject_id,
            expected_generation: model.generation,
        },
    )
    .unwrap_or_else(|error| panic!("qualified frozen decision: {error:?}"));

    assert_eq!(
        receipt.decision.disposition,
        CalibratedDispositionV1::Selected(id("candidate:950000"))
    );
    assert!(!receipt.authority.grants_any());
}

fn scored_candidate(
    model: ReferenceModel,
    feature_ppm: i64,
) -> (LearnedScoreEvidenceV1, CalibratedActionCandidateV1) {
    let score_ppm = model.score_ppm(feature_ppm);
    let confidence_ppm = u64::try_from(score_ppm.max(1_000_000 - score_ppm))
        .unwrap_or_else(|error| panic!("confidence conversion: {error:?}"));
    let ood_ppm = model.ood_score_ppm(feature_ppm);
    let candidate_id = id(&format!("candidate:{feature_ppm}"));
    let feature_digest = Digest32::of_bytes(&feature_ppm.to_be_bytes());
    let support_digest = digest(b"frozen-reference-support-v1");
    let evidence = LearnedScoreEvidenceV1 {
        candidate_id: candidate_id.clone(),
        feature_digest,
        utility: FixedQ32::from_raw(score_ppm - 500_000),
        calibrated_confidence: probability_ppm(confidence_ppm),
        ood_score: probability_ppm(
            u64::try_from(ood_ppm).unwrap_or_else(|error| panic!("ood conversion: {error:?}")),
        ),
        support_digest,
    };
    let candidate = CalibratedActionCandidateV1 {
        candidate_id,
        legal: true,
        hard_veto: false,
        utility: evidence.utility,
        calibrated_confidence: evidence.calibrated_confidence,
        ood_score: evidence.ood_score,
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest,
    };
    (evidence, candidate)
}

impl ReferenceModel {
    fn score_ppm(self, feature_ppm: i64) -> i64 {
        let raw = feature_ppm.saturating_mul(self.weight_ppm) / 1_000_000 + self.bias_ppm;
        raw.clamp(0, 1_000_000)
    }

    fn ood_score_ppm(self, feature_ppm: i64) -> i64 {
        if (self.support_min_ppm..=self.support_max_ppm).contains(&feature_ppm) {
            0
        } else {
            1_000_000
        }
    }
}

fn measured_ece_ppm(model: ReferenceModel, rows: &[ValidationRow]) -> u32 {
    let mut total = 0_u64;
    let mut count = 0_u64;
    for row in rows.iter().filter(|row| row.in_domain) {
        let target = i64::try_from(row.label.saturating_mul(1_000_000))
            .unwrap_or_else(|error| panic!("label conversion: {error:?}"));
        total = total.saturating_add(model.score_ppm(row.feature_ppm).abs_diff(target));
        count = count.saturating_add(1);
    }
    assert_ne!(count, 0, "frozen validation set requires in-domain rows");
    u32::try_from(total / count).unwrap_or_else(|error| panic!("ece conversion: {error:?}"))
}

fn measured_ood_false_acceptance_ppm(
    model: ReferenceModel,
    rows: &[ValidationRow],
    threshold_ppm: u64,
) -> u32 {
    let mut false_accepts = 0_u64;
    let mut count = 0_u64;
    for row in rows.iter().filter(|row| !row.in_domain) {
        let ood_score =
            u64::try_from(model.ood_score_ppm(row.feature_ppm)).unwrap_or(u64::MAX);
        false_accepts += u64::from(ood_score <= threshold_ppm);
        count = count.saturating_add(1);
    }
    assert_ne!(count, 0, "frozen validation set requires out-domain rows");
    let numerator = false_accepts.saturating_mul(1_000_000);
    u32::try_from(numerator / count)
        .unwrap_or_else(|error| panic!("false acceptance conversion: {error:?}"))
}

fn parse_model(text: &str) -> ReferenceModel {
    assert_eq!(field(text, "format"), "hepta.intuition.reference-linear.v1");
    ReferenceModel {
        generation: field(text, "generation")
            .parse()
            .unwrap_or_else(|error| panic!("model generation: {error:?}")),
        weight_ppm: field(text, "weight_ppm")
            .parse()
            .unwrap_or_else(|error| panic!("model weight: {error:?}")),
        bias_ppm: field(text, "bias_ppm")
            .parse()
            .unwrap_or_else(|error| panic!("model bias: {error:?}")),
        support_min_ppm: field(text, "support_min_ppm")
            .parse()
            .unwrap_or_else(|error| panic!("model support min: {error:?}")),
        support_max_ppm: field(text, "support_max_ppm")
            .parse()
            .unwrap_or_else(|error| panic!("model support max: {error:?}")),
    }
}

fn field<'a>(text: &'a str, name: &str) -> &'a str {
    text.lines()
        .find_map(|line| line.strip_prefix(&format!("{name}=")))
        .unwrap_or_else(|| panic!("missing model field {name}"))
}

fn parse_validation(text: &str) -> Vec<ValidationRow> {
    text.lines()
        .skip(1)
        .filter(|line| !line.is_empty())
        .map(|line| {
            let columns = line.split(',').collect::<Vec<_>>();
            assert_eq!(columns.len(), 3, "validation row shape");
            ValidationRow {
                feature_ppm: columns[0]
                    .parse()
                    .unwrap_or_else(|error| panic!("feature: {error:?}")),
                label: columns[1]
                    .parse()
                    .unwrap_or_else(|error| panic!("label: {error:?}")),
                in_domain: columns[2]
                    .parse()
                    .unwrap_or_else(|error| panic!("in-domain flag: {error:?}")),
            }
        })
        .collect()
}

fn probability_ppm(ppm: u64) -> ProbabilityQ32 {
    let raw = (u128::from(ProbabilityQ32::ONE.raw()) * u128::from(ppm) / 1_000_000) as u64;
    ProbabilityQ32::from_raw(raw)
        .unwrap_or_else(|error| panic!("valid probability: {error:?}"))
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid id {value}: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}
