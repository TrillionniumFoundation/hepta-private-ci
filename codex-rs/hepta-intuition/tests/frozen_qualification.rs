use codex_hepta_intuition::{
    AssignmentModeV1, CalibratedActionCandidateV1, CalibratedDecisionRequestV1,
    CalibrationArtifactV1, CandidateSetCompletenessBindingV1, CanonicalPolicyProfileV1,
    LearnedScorerContractV1, OodArtifactV1, QualificationAuthorityVerifier,
    QualificationManifestV1, QualifiedDecisionRequestV1, RiskClass,
    canonical_candidate_order_digest_v1, canonical_candidate_set_digest_v1,
    canonical_learned_scorer_contract_digest_v1, canonical_policy_profile_digest_v1,
    canonical_qualification_manifest_digest_v1, decide_qualified,
};
use codex_hepta_types::{Digest32, FixedQ32, ProbabilityQ32, StableId};

const FROZEN_DATA: &str = include_str!("fixtures/intuition_frozen_validation_v1.csv");
const MODEL_ARTIFACT: &str = include_str!("fixtures/reference_model_v1.txt");

#[derive(Clone, Copy)]
struct Row {
    confidence_ppm: u32,
    correct: bool,
    ood_score_ppm: u32,
    is_ood: bool,
}

struct FrozenAuthority {
    authority: Digest32,
    signer_set: Digest32,
    model: Digest32,
    data: Digest32,
}

impl QualificationAuthorityVerifier for FrozenAuthority {
    fn authenticate(&self, manifest: &QualificationManifestV1) -> bool {
        manifest.authority_digest == self.authority
            && manifest.signer_set_digest == self.signer_set
            && manifest.model_artifact_digest == self.model
            && manifest.frozen_validation_digest == self.data
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn id(value: &str) -> StableId {
    StableId::new(value).expect("valid fixture id")
}

fn ppm_probability(ppm: u32) -> ProbabilityQ32 {
    let raw = (u128::from(ProbabilityQ32::ONE.raw()) * u128::from(ppm)) / 1_000_000u128;
    ProbabilityQ32::from_raw(u64::try_from(raw).expect("Q32 ppm conversion")).expect("probability")
}

fn parse_rows() -> Vec<Row> {
    FROZEN_DATA
        .lines()
        .skip(1)
        .filter(|line| !line.trim().is_empty())
        .map(|line| {
            let fields = line.split(',').collect::<Vec<_>>();
            assert_eq!(fields.len(), 4);
            Row {
                confidence_ppm: fields[0].parse().expect("confidence"),
                correct: fields[1] == "1",
                ood_score_ppm: fields[2].parse().expect("ood score"),
                is_ood: fields[3] == "1",
            }
        })
        .collect()
}

fn measured_ece_ppm(rows: &[Row]) -> u32 {
    let in_domain = rows.iter().filter(|row| !row.is_ood).collect::<Vec<_>>();
    let mean_confidence = in_domain
        .iter()
        .map(|row| u64::from(row.confidence_ppm))
        .sum::<u64>()
        / u64::try_from(in_domain.len()).expect("bounded rows");
    let accuracy = 1_000_000u64
        * u64::try_from(in_domain.iter().filter(|row| row.correct).count()).expect("bounded rows")
        / u64::try_from(in_domain.len()).expect("bounded rows");
    u32::try_from(mean_confidence.abs_diff(accuracy)).expect("ppm")
}

fn measured_ood_false_acceptance_ppm(rows: &[Row], maximum_in_domain_ppm: u32) -> u32 {
    let ood = rows.iter().filter(|row| row.is_ood).collect::<Vec<_>>();
    let false_accepts = ood
        .iter()
        .filter(|row| row.ood_score_ppm <= maximum_in_domain_ppm)
        .count();
    u32::try_from(
        1_000_000u64 * u64::try_from(false_accepts).expect("bounded")
            / u64::try_from(ood.len()).expect("bounded"),
    )
    .expect("ppm")
}

#[test]
fn frozen_model_data_artifacts_flow_through_authenticated_qualified_policy() {
    let rows = parse_rows();
    let measured_ece = measured_ece_ppm(&rows);
    let maximum_in_domain_ppm = 300_000u32;
    let measured_ood_far = measured_ood_false_acceptance_ppm(&rows, maximum_in_domain_ppm);
    assert_eq!(measured_ece, 50_000);
    assert_eq!(measured_ood_far, 0);

    let model_digest = Digest32::of_bytes(MODEL_ARTIFACT.as_bytes());
    let frozen_validation_digest = Digest32::of_bytes(FROZEN_DATA.as_bytes());
    let policy_digest = digest("qualified-policy-v1");
    let objective_class_digest = digest("objective-class-v1");
    let calibration_digest = digest("calibration-from-frozen-data-v1");
    let ood_digest = digest("ood-from-frozen-data-v1");

    let scorer0 = LearnedScorerContractV1 {
        contract_digest: Digest32::ZERO,
        feature_schema_digest: digest("reference_features_v1"),
        model_artifact_digest: model_digest,
        calibration_artifact_digest: calibration_digest,
        ood_artifact_digest: ood_digest,
        score_semantics_digest: digest("utility_confidence_ood_v1"),
        policy_digest,
        policy_generation: 1,
    };
    let scorer = LearnedScorerContractV1 {
        contract_digest: canonical_learned_scorer_contract_digest_v1(&scorer0),
        ..scorer0
    };

    let profile0 = CanonicalPolicyProfileV1 {
        profile_digest: Digest32::ZERO,
        policy_digest,
        policy_generation: 1,
        minimum_confidence: ppm_probability(500_000),
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        allow_elevated_risk: false,
    };
    let profile = CanonicalPolicyProfileV1 {
        profile_digest: canonical_policy_profile_digest_v1(&profile0),
        ..profile0
    };

    let candidates = vec![CalibratedActionCandidateV1 {
        candidate_id: id("candidate:qualified"),
        legal: true,
        hard_veto: false,
        utility: FixedQ32::from_raw(100),
        calibrated_confidence: ppm_probability(950_000),
        ood_score: ppm_probability(50_000),
        assignment_probability: ProbabilityQ32::ZERO,
        support_digest: digest("fixture-support"),
    }];
    let completeness_digest = digest("complete-legal-set-v1");
    let decision = CalibratedDecisionRequestV1 {
        decision_id: id("decision:frozen-qualification"),
        objective_digest: digest("objective-v1"),
        objective_class_digest,
        state_digest: digest("state-v1"),
        policy_digest,
        policy_generation: 1,
        sequence: 10,
        minimum_confidence: profile.minimum_confidence,
        maximum_ece_ppm: profile.maximum_ece_ppm,
        maximum_ood_false_acceptance_ppm: profile.maximum_ood_false_acceptance_ppm,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: completeness_digest,
            generator_digest: digest("generator-v1"),
            grammar_digest: digest("grammar-v1"),
            hard_filter_digest: digest("hard-filter-v1"),
            truncation_digest: digest("no-truncation-v1"),
            candidate_set_digest: canonical_candidate_set_digest_v1(&candidates).expect("set digest"),
            canonical_order_digest: canonical_candidate_order_digest_v1(&candidates).expect("order digest"),
            candidate_count: 1,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: calibration_digest,
            policy_digest,
            objective_class_digest,
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            measured_ece_ppm: measured_ece,
            subgroup_audit_digest: digest("subgroup-audit-v1"),
        },
        ood: OodArtifactV1 {
            artifact_digest: ood_digest,
            policy_digest,
            detector_digest: digest("ood-detector-v1"),
            support_digest: digest("ood-support-v1"),
            generation: 1,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: ppm_probability(maximum_in_domain_ppm),
            measured_false_acceptance_ppm: measured_ood_far,
        },
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };

    let authority = digest("fixture-qualification-authority");
    let signer_set = digest("fixture-signer-set");
    let manifest0 = QualificationManifestV1 {
        manifest_digest: Digest32::ZERO,
        authority_digest: authority,
        signer_set_digest: signer_set,
        qualification_run_digest: digest("fixture-qualification-run"),
        frozen_validation_digest,
        model_artifact_digest: model_digest,
        scorer_contract_digest: scorer.contract_digest,
        profile_digest: profile.profile_digest,
        policy_digest,
        objective_class_digest,
        policy_generation: 1,
        completeness_receipt_digest: completeness_digest,
        calibration_artifact_digest: calibration_digest,
        ood_artifact_digest: ood_digest,
    };
    let qualification = QualificationManifestV1 {
        manifest_digest: canonical_qualification_manifest_digest_v1(&manifest0),
        ..manifest0
    };
    let verifier = FrozenAuthority {
        authority,
        signer_set,
        model: model_digest,
        data: frozen_validation_digest,
    };

    let receipt = decide_qualified(
        QualifiedDecisionRequestV1 { decision, profile, qualification },
        &verifier,
    )
    .expect("qualified policy must accept frozen qualified artifact chain");
    assert!(!receipt.authority.grants_any());
}
