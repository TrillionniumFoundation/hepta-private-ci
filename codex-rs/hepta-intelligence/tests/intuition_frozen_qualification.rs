use codex_hepta_intelligence::IntuitionQualificationError;
use codex_hepta_intelligence::IntuitionQualificationEvidenceV1;
use codex_hepta_intelligence::decide_authenticated_intuition_v1;
use codex_hepta_intuition::AssignmentModeV1;
use codex_hepta_intuition::CalibratedActionCandidateV1;
use codex_hepta_intuition::CalibratedDecisionRequestV1;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::CalibrationArtifactV1;
use codex_hepta_intuition::CandidateSetCompletenessBindingV1;
use codex_hepta_intuition::CanonicalPolicyProfileV1;
use codex_hepta_intuition::CanonicalRiskRuleV1;
use codex_hepta_intuition::LearnedScorerContractV1;
use codex_hepta_intuition::OodArtifactV1;
use codex_hepta_intuition::RiskClass;
use codex_hepta_intuition::canonical_candidate_order_digest_v1;
use codex_hepta_intuition::canonical_candidate_set_digest_v1;
use codex_hepta_intuition::canonical_completeness_evidence_payload_v1;
use codex_hepta_intuition::canonical_profile_qualification_evidence_payload_v1;
use codex_hepta_intuition::canonical_random_assignment_evidence_payload_v1;
use codex_hepta_intuition::canonical_scoring_evidence_payload_v1;
use codex_hepta_intuition::scoring_commitment_for_request_v1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

const MODEL_BYTES: &[u8] = include_bytes!("fixtures/intuition-policy/linear-scorer-v1.model");
const CALIBRATION_CSV: &str = include_str!("fixtures/intuition-policy/frozen-calibration-v1.csv");
const OOD_CSV: &str = include_str!("fixtures/intuition-policy/frozen-ood-v1.csv");

#[derive(Clone, Copy)]
struct LinearScorer {
    bias_confidence_ppm: i64,
    x_confidence_ppm_per_q16: i64,
    y_confidence_ppm_per_q16: i64,
    utility_x_weight_q16: i64,
    utility_y_weight_q16: i64,
    ood_scale_q16: i64,
}

#[derive(Clone, Copy)]
struct Score {
    utility: FixedQ32,
    confidence_ppm: u32,
    ood_score_ppm: u32,
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn probability_ppm(ppm: u32) -> ProbabilityQ32 {
    let raw = (u128::from(ProbabilityQ32::ONE.raw()) * u128::from(ppm)) / 1_000_000;
    ProbabilityQ32::from_raw(raw as u64).unwrap()
}

fn parse_model() -> LinearScorer {
    let text = std::str::from_utf8(MODEL_BYTES).unwrap();
    let get = |key: &str| -> i64 {
        let prefix = format!("{key}=");
        text.lines()
            .find_map(|line| line.strip_prefix(prefix.as_str()))
            .unwrap_or_else(|| panic!("missing {key}"))
            .parse()
            .unwrap()
    };
    assert!(text.contains("format=hepta.intuition.linear-scorer.v1"));
    LinearScorer {
        bias_confidence_ppm: get("bias_confidence_ppm"),
        x_confidence_ppm_per_q16: get("x_confidence_ppm_per_q16"),
        y_confidence_ppm_per_q16: get("y_confidence_ppm_per_q16"),
        utility_x_weight_q16: get("utility_x_weight_q16"),
        utility_y_weight_q16: get("utility_y_weight_q16"),
        ood_scale_q16: get("ood_scale_q16"),
    }
}

fn score(model: LinearScorer, x_q16: i64, y_q16: i64) -> Score {
    let confidence = model.bias_confidence_ppm
        + (i128::from(x_q16) * i128::from(model.x_confidence_ppm_per_q16) / 65_536) as i64
        + (i128::from(y_q16) * i128::from(model.y_confidence_ppm_per_q16) / 65_536) as i64;
    let confidence_ppm = confidence.clamp(0, 1_000_000) as u32;
    let farthest = x_q16.unsigned_abs().max(y_q16.unsigned_abs());
    let ood_score_ppm = ((u128::from(farthest) * 1_000_000)
        / u128::try_from(model.ood_scale_q16).unwrap())
    .min(1_000_000) as u32;
    let utility_q16 = i128::from(x_q16) * i128::from(model.utility_x_weight_q16)
        + i128::from(y_q16) * i128::from(model.utility_y_weight_q16);
    let utility_raw = (utility_q16 << 16) / 65_536;
    Score {
        utility: FixedQ32::from_raw(i64::try_from(utility_raw).unwrap()),
        confidence_ppm,
        ood_score_ppm,
    }
}

fn calibration_ece_ppm(model: LinearScorer) -> (u32, Digest32) {
    let mut bins = [(0_u64, 0_u64, 0_u64); 5];
    let mut rows = 0_u64;
    for line in CALIBRATION_CSV
        .lines()
        .skip(1)
        .filter(|line| !line.is_empty())
    {
        let fields = line.split(',').collect::<Vec<_>>();
        let x: i64 = fields[1].parse().unwrap();
        let y: i64 = fields[2].parse().unwrap();
        let label: u64 = fields[3].parse().unwrap();
        let prediction = u64::from(score(model, x, y).confidence_ppm);
        let bin = usize::try_from((prediction * 5 / 1_000_001).min(4)).unwrap();
        bins[bin].0 += 1;
        bins[bin].1 += prediction;
        bins[bin].2 += label;
        rows += 1;
    }
    let mut weighted_error = 0_u128;
    let mut audit = String::from("hepta.intuition.calibration-audit.v1|");
    for (index, (count, prediction_sum, label_sum)) in bins.into_iter().enumerate() {
        if count == 0 {
            continue;
        }
        let mean_prediction = prediction_sum / count;
        let mean_label_ppm = label_sum * 1_000_000 / count;
        let gap = mean_prediction.abs_diff(mean_label_ppm);
        weighted_error += u128::from(gap) * u128::from(count);
        audit.push_str(&format!(
            "{index}:{count}:{mean_prediction}:{mean_label_ppm};"
        ));
    }
    (
        u32::try_from(weighted_error / u128::from(rows)).unwrap(),
        Digest32::of_bytes(audit.as_bytes()),
    )
}

fn ood_false_acceptance_ppm(model: LinearScorer, maximum_in_domain_ppm: u32) -> u32 {
    let mut ood_rows = 0_u64;
    let mut false_accepts = 0_u64;
    for line in OOD_CSV.lines().skip(1).filter(|line| !line.is_empty()) {
        let fields = line.split(',').collect::<Vec<_>>();
        let x: i64 = fields[1].parse().unwrap();
        let y: i64 = fields[2].parse().unwrap();
        let in_domain: u8 = fields[3].parse().unwrap();
        if in_domain == 0 {
            ood_rows += 1;
            if score(model, x, y).ood_score_ppm <= maximum_in_domain_ppm {
                false_accepts += 1;
            }
        }
    }
    u32::try_from(false_accepts * 1_000_000 / ood_rows).unwrap()
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    evidence_id: &str,
    objective_digest: Digest32,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(evidence_id),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest,
        authority_epoch: principal.authority_epoch,
        issued_at: 100,
        expires_at: 200,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

#[test]
fn frozen_model_and_data_produce_four_role_authenticated_policy_decision() {
    let model = parse_model();
    let model_artifact_digest = Digest32::of_bytes(MODEL_BYTES);
    let policy_digest = digest("policy:intuition-qualified-v3");
    assert_ne!(policy_digest, model_artifact_digest);

    let calibration_dataset_digest = Digest32::of_bytes(CALIBRATION_CSV.as_bytes());
    let ood_dataset_digest = Digest32::of_bytes(OOD_CSV.as_bytes());
    let (measured_ece_ppm, subgroup_audit_digest) = calibration_ece_ppm(model);
    let maximum_in_domain_ppm = 750_000;
    let measured_false_acceptance_ppm =
        ood_false_acceptance_ppm(model, maximum_in_domain_ppm);
    assert!(measured_ece_ppm <= 400_000, "ECE {measured_ece_ppm}");
    assert_eq!(measured_false_acceptance_ppm, 0);

    let calibration_artifact_bytes = format!(
        "hepta.intuition.calibration-artifact.v2|policy={policy_digest:?}|model={model_artifact_digest:?}|dataset={calibration_dataset_digest:?}|ece_ppm={measured_ece_ppm}|subgroup={subgroup_audit_digest:?}"
    );
    let calibration_artifact_digest = Digest32::of_bytes(calibration_artifact_bytes.as_bytes());
    let ood_detector_digest = digest("linear-scorer:ood-head:v1");
    let ood_artifact_bytes = format!(
        "hepta.intuition.ood-artifact.v2|policy={policy_digest:?}|model={model_artifact_digest:?}|dataset={ood_dataset_digest:?}|far_ppm={measured_false_acceptance_ppm}|max_in_domain_ppm={maximum_in_domain_ppm}|detector={ood_detector_digest:?}"
    );
    let ood_artifact_digest = Digest32::of_bytes(ood_artifact_bytes.as_bytes());

    let objective_digest = digest("objective:intuition-frozen-qualification");
    let objective_class_digest = digest("objective-class:read-only-intervention");
    let scored = [
        ("candidate:a", score(model, 65_536, 0)),
        ("candidate:b", score(model, 131_072, 0)),
    ];
    let half = ProbabilityQ32::from_raw(ProbabilityQ32::ONE.raw() / 2).unwrap();
    let candidates = scored
        .into_iter()
        .map(|(candidate_id, value)| CalibratedActionCandidateV1 {
            candidate_id: id(candidate_id),
            legal: true,
            hard_veto: false,
            utility: value.utility,
            calibrated_confidence: probability_ppm(value.confidence_ppm),
            ood_score: probability_ppm(value.ood_score_ppm),
            assignment_probability: half,
            support_digest: digest(&format!("support:{candidate_id}")),
        })
        .collect::<Vec<_>>();
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates).unwrap();
    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates).unwrap();
    let generator_digest = digest("legal-candidate-generator:v1");
    let mut completeness_bytes = b"hepta.test.complete-set.v2".to_vec();
    completeness_bytes.extend_from_slice(generator_digest.as_array());
    completeness_bytes.extend_from_slice(candidate_set_digest.as_array());
    completeness_bytes.extend_from_slice(canonical_order_digest.as_array());
    completeness_bytes.extend_from_slice(&(candidates.len() as u32).to_be_bytes());
    completeness_bytes.extend_from_slice(&0_u32.to_be_bytes());

    let request = CalibratedDecisionRequestV1 {
        decision_id: id("decision:frozen-qualification"),
        objective_digest,
        objective_class_digest,
        state_digest: digest("state:frozen-qualification"),
        policy_digest,
        policy_generation: 3,
        sequence: 7,
        minimum_confidence: probability_ppm(600_000),
        maximum_ece_ppm: 400_000,
        maximum_ood_false_acceptance_ppm: 50_000,
        risk_class: RiskClass::Low,
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: Digest32::of_bytes(&completeness_bytes),
            generator_digest,
            grammar_digest: digest("legal-grammar:v1"),
            hard_filter_digest: digest("hard-filter:v1"),
            truncation_digest: digest("no-truncation:v1"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: candidates.len() as u32,
            omitted_count_bound: 0,
        },
        calibration: CalibrationArtifactV1 {
            artifact_digest: calibration_artifact_digest,
            policy_digest,
            objective_class_digest,
            generation: 3,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            measured_ece_ppm,
            subgroup_audit_digest,
        },
        ood: OodArtifactV1 {
            artifact_digest: ood_artifact_digest,
            policy_digest,
            detector_digest: ood_detector_digest,
            support_digest: ood_dataset_digest,
            generation: 3,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: probability_ppm(maximum_in_domain_ppm),
            measured_false_acceptance_ppm,
        },
        assignment: AssignmentModeV1::CounterBased {
            random_stream_digest: digest("rng:intuition-frozen-v1"),
            draw: half,
            abstain_probability: ProbabilityQ32::ZERO,
        },
        candidates,
    };

    let model_text = std::str::from_utf8(MODEL_BYTES).unwrap();
    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("profile:intuition-frozen-v2"),
        policy_digest,
        objective_class_digest,
        generation: 3,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        minimum_confidence: probability_ppm(600_000),
        maximum_ece_ppm: 400_000,
        maximum_ood_false_acceptance_ppm: 50_000,
        maximum_in_domain_score: probability_ppm(maximum_in_domain_ppm),
        risk_rule: CanonicalRiskRuleV1::HighOnlySlowPath,
        scorer: LearnedScorerContractV1 {
            model_artifact_digest,
            feature_schema_digest: Digest32::of_bytes(
                model_text
                    .lines()
                    .find(|line| line.starts_with("feature_schema="))
                    .unwrap()
                    .as_bytes(),
            ),
            output_schema_digest: Digest32::of_bytes(
                model_text
                    .lines()
                    .find(|line| line.starts_with("output_schema="))
                    .unwrap()
                    .as_bytes(),
            ),
            score_semantics_digest: Digest32::of_bytes(
                model_text
                    .lines()
                    .find(|line| line.starts_with("score_semantics="))
                    .unwrap()
                    .as_bytes(),
            ),
            scorer_contract_digest: digest("hepta.intuition.learned-scorer-contract.v2"),
        },
        calibration_dataset_digest,
        ood_dataset_digest,
        calibration_artifact_digest,
        calibration_measured_ece_ppm: measured_ece_ppm,
        calibration_subgroup_audit_digest: subgroup_audit_digest,
        calibration_valid_from_sequence: 1,
        calibration_expires_after_sequence: 100,
        ood_artifact_digest,
        ood_measured_false_acceptance_ppm: measured_false_acceptance_ppm,
        ood_detector_digest,
        ood_support_digest: ood_dataset_digest,
        ood_valid_from_sequence: 1,
        ood_expires_after_sequence: 100,
    };
    let scoring = scoring_commitment_for_request_v1(
        &request,
        &profile,
        digest("feature-snapshot:frozen-candidates-v1"),
    )
    .unwrap();

    let keys = [
        SigningKey::from_bytes(&[31; 32]),
        SigningKey::from_bytes(&[37; 32]),
        SigningKey::from_bytes(&[47; 32]),
        SigningKey::from_bytes(&[53; 32]),
    ];
    let principals = [
        ("intuition-candidate-generator", "generator-credentials"),
        ("intuition-learned-scorer", "scorer-credentials"),
        ("intuition-independent-evaluator", "evaluator-credentials"),
        ("intuition-random-source", "random-source-credentials"),
    ]
    .into_iter()
    .enumerate()
    .map(|(index, (principal_id, credentials))| AuthenticatedPrincipalV1 {
        principal_id: id(principal_id),
        credential_chain_digest: digest(credentials),
        signing_key_digest: Digest32::of_bytes(&keys[index].verifying_key().to_bytes()),
        scope_digest: digest("intuition-qualification-scope"),
        authority_epoch: 12,
        authenticated_at: 50,
        expires_at: 250,
    })
    .collect::<Vec<_>>();

    let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: digest("intuition-qualification-scope"),
        objective_digest,
        authority_epoch: 12,
        signers: vec![
            TrustedLearningSignerV1 {
                principal: principals[0].clone(),
                controller_id: id("candidate-generator-controller"),
                verifying_key: keys[0].verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: principals[1].clone(),
                controller_id: id("scorer-controller"),
                verifying_key: keys[1].verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Scorer],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: principals[2].clone(),
                controller_id: id("independent-evaluator-controller"),
                verifying_key: keys[2].verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: principals[3].clone(),
                controller_id: id("random-source-controller"),
                verifying_key: keys[3].verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::RandomSource],
                revoked_at: None,
            },
        ],
    })
    .unwrap();

    let completeness_payload = canonical_completeness_evidence_payload_v1(&request).unwrap();
    let scoring_payload = canonical_scoring_evidence_payload_v1(&scoring).unwrap();
    let profile_payload =
        canonical_profile_qualification_evidence_payload_v1(&profile).unwrap();
    let assignment_payload = canonical_random_assignment_evidence_payload_v1(&request)
        .unwrap()
        .unwrap();

    let completeness_evidence = sign(
        &verifier,
        &principals[0],
        &keys[0],
        LearningEvidenceRoleV1::Generator,
        "evidence:intuition-completeness",
        objective_digest,
        &completeness_payload,
    );
    let scoring_evidence = sign(
        &verifier,
        &principals[1],
        &keys[1],
        LearningEvidenceRoleV1::Scorer,
        "evidence:intuition-scoring",
        objective_digest,
        &scoring_payload,
    );
    let profile_evidence = sign(
        &verifier,
        &principals[2],
        &keys[2],
        LearningEvidenceRoleV1::Evaluator,
        "evidence:intuition-profile-qualification",
        objective_digest,
        &profile_payload,
    );
    let assignment_evidence = sign(
        &verifier,
        &principals[3],
        &keys[3],
        LearningEvidenceRoleV1::RandomSource,
        "evidence:intuition-random-assignment",
        objective_digest,
        &assignment_payload,
    );

    let mut tampered_scoring = scoring_evidence.clone();
    tampered_scoring.signature[0] ^= 1;
    assert!(
        decide_authenticated_intuition_v1(
            request.clone(),
            profile.clone(),
            scoring.clone(),
            IntuitionQualificationEvidenceV1 {
                completeness: &completeness_evidence,
                scoring: &tampered_scoring,
                profile_qualification: &profile_evidence,
                assignment: Some(&assignment_evidence),
            },
            &verifier,
            150,
        )
        .is_err()
    );

    assert_eq!(
        decide_authenticated_intuition_v1(
            request.clone(),
            profile.clone(),
            scoring.clone(),
            IntuitionQualificationEvidenceV1 {
                completeness: &completeness_evidence,
                scoring: &scoring_evidence,
                profile_qualification: &profile_evidence,
                assignment: None,
            },
            &verifier,
            150,
        ),
        Err(IntuitionQualificationError::MissingRandomSourceEvidence)
    );

    let receipt = decide_authenticated_intuition_v1(
        request,
        profile,
        scoring,
        IntuitionQualificationEvidenceV1 {
            completeness: &completeness_evidence,
            scoring: &scoring_evidence,
            profile_qualification: &profile_evidence,
            assignment: Some(&assignment_evidence),
        },
        &verifier,
        150,
    )
    .unwrap();
    assert_eq!(
        receipt.decision.disposition,
        CalibratedDispositionV1::Selected(id("candidate:b"))
    );
    assert!(!receipt.authentication_digest.is_zero());
    assert!(!receipt.profile_digest.is_zero());
    assert!(!receipt.exact_request_digest.is_zero());
    assert!(!receipt.scoring_payload_digest.is_zero());
    assert!(!receipt.assignment_payload_digest.is_zero());
}
