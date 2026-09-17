const FROZEN_MODEL: &str = include_str!("../qualification/frozen_model_v1.csv");
const FROZEN_VALIDATION: &str = include_str!("../qualification/frozen_validation_v1.csv");
const SIGNER_EPOCH: u64 = 3;

#[derive(Clone, Debug)]
struct ModelRow {
    action_id: String,
    segment: String,
    utility_raw: i64,
    confidence_ppm: u32,
    ood_score_ppm: u32,
}

#[derive(Clone, Debug)]
struct ValidationRow {
    action_id: String,
    segment: String,
    outcome: bool,
    in_domain: bool,
}

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("valid test id: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn probability_from_ppm(ppm: u32) -> ProbabilityQ32 {
    let one = u128::from(ProbabilityQ32::ONE.raw());
    let raw = (u128::from(ppm) * one + 500_000) / 1_000_000;
    ProbabilityQ32::from_raw(u64::try_from(raw).expect("Q32 ppm conversion fits"))
        .expect("ppm in probability range")
}

fn parse_model() -> Vec<ModelRow> {
    FROZEN_MODEL
        .lines()
        .filter(|line| !line.is_empty() && !line.starts_with('#') && !line.starts_with("action_id,"))
        .map(|line| {
            let fields = line.split(',').collect::<Vec<_>>();
            assert_eq!(fields.len(), 5, "model row shape");
            ModelRow {
                action_id: fields[0].to_string(),
                segment: fields[1].to_string(),
                utility_raw: fields[2].parse().expect("utility raw"),
                confidence_ppm: fields[3].parse().expect("confidence ppm"),
                ood_score_ppm: fields[4].parse().expect("ood score ppm"),
            }
        })
        .collect()
}

fn parse_validation() -> Vec<ValidationRow> {
    FROZEN_VALIDATION
        .lines()
        .filter(|line| !line.is_empty() && !line.starts_with('#') && !line.starts_with("action_id,"))
        .map(|line| {
            let fields = line.split(',').collect::<Vec<_>>();
            assert_eq!(fields.len(), 4, "validation row shape");
            ValidationRow {
                action_id: fields[0].to_string(),
                segment: fields[1].to_string(),
                outcome: fields[2] == "1",
                in_domain: fields[3] == "1",
            }
        })
        .collect()
}

fn model_row<'a>(model: &'a [ModelRow], action_id: &str, segment: &str) -> &'a ModelRow {
    model
        .iter()
        .find(|row| row.action_id == action_id && row.segment == segment)
        .expect("frozen model covers validation row")
}

fn frozen_metrics(model: &[ModelRow], validation: &[ValidationRow]) -> (u32, u32, Digest32) {
    let calibration = validation
        .iter()
        .filter(|row| row.in_domain)
        .map(|row| {
            let scored = model_row(model, &row.action_id, &row.segment);
            CalibrationObservationV1 {
                confidence: probability_from_ppm(scored.confidence_ppm),
                outcome: row.outcome,
            }
        })
        .collect::<Vec<_>>();
    let ood = validation
        .iter()
        .map(|row| {
            let scored = model_row(model, &row.action_id, &row.segment);
            OodObservationV1 {
                score: probability_from_ppm(scored.ood_score_ppm),
                in_domain: row.in_domain,
            }
        })
        .collect::<Vec<_>>();
    let maximum_in_domain_score = probability_from_ppm(250_000);
    let ece = expected_calibration_error_ppm_v1(&calibration, 10).expect("ECE");
    let far = ood_false_acceptance_ppm_v1(&ood, maximum_in_domain_score).expect("OOD FAR");

    let mut prediction_bytes = b"hepta.intuition.frozen-validation-predictions.v1".to_vec();
    for row in validation {
        let scored = model_row(model, &row.action_id, &row.segment);
        prediction_bytes.extend_from_slice(row.action_id.as_bytes());
        prediction_bytes.push(0);
        prediction_bytes.extend_from_slice(row.segment.as_bytes());
        prediction_bytes.push(0);
        prediction_bytes.extend_from_slice(&scored.utility_raw.to_be_bytes());
        prediction_bytes.extend_from_slice(&scored.confidence_ppm.to_be_bytes());
        prediction_bytes.extend_from_slice(&scored.ood_score_ppm.to_be_bytes());
    }
    (ece, far, Digest32::of_bytes(&prediction_bytes))
}

fn signature(
    key: &SigningKey,
    kind: QualificationArtifactKindV1,
    artifact_digest: Digest32,
) -> QualificationSignatureV1 {
    let signer_id = id("qualification:intuition-policy");
    let message = qualification_signature_message_v1(
        kind,
        artifact_digest,
        &signer_id,
        SIGNER_EPOCH,
    )
    .expect("signature message");
    QualificationSignatureV1 {
        signer_id,
        signer_epoch: SIGNER_EPOCH,
        signature: key.sign(&message).to_bytes().to_vec(),
    }
}

fn current_candidates(model: &[ModelRow]) -> Vec<CalibratedActionCandidateV1> {
    ["candidate:a", "candidate:b"]
        .into_iter()
        .map(|action| {
            let scored = model_row(model, action, "in");
            CalibratedActionCandidateV1 {
                candidate_id: id(action),
                legal: true,
                hard_veto: false,
                utility: FixedQ32::from_raw(scored.utility_raw),
                calibrated_confidence: probability_from_ppm(scored.confidence_ppm),
                ood_score: probability_from_ppm(scored.ood_score_ppm),
                assignment_probability: ProbabilityQ32::ZERO,
                support_digest: digest(format!("support:{action}:in").as_bytes()),
            }
        })
        .collect()
}

fn authenticated_fixture() -> (
    AuthenticatedCalibratedDecisionRequestV1,
    QualificationArtifactVerifierV1,
    u32,
    u32,
) {
    let model = parse_model();
    let validation = parse_validation();
    let model_digest = digest(FROZEN_MODEL.as_bytes());
    let frozen_dataset_digest = digest(FROZEN_VALIDATION.as_bytes());
    let (measured_ece_ppm, measured_false_acceptance_ppm, frozen_predictions_digest) =
        frozen_metrics(&model, &validation);
    let signing_key = SigningKey::from_bytes(&[19; 32]);
    let signer_id = id("qualification:intuition-policy");
    let verifier = QualificationArtifactVerifierV1::new(
        signer_id,
        SIGNER_EPOCH,
        signing_key.verifying_key(),
    )
    .expect("pinned verifier");

    let policy_digest = digest(b"intuition-policy:generation-7");
    let objective_class_digest = digest(b"objective-class:interactive-assist");
    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("intuition-profile:interactive-assist:v1"),
        policy_digest,
        objective_class_digest,
        generation: 7,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        minimum_confidence: probability_from_ppm(600_000),
        maximum_ece_ppm: 5_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        maximum_in_domain_score: probability_from_ppm(250_000),
        maximum_fast_path_risk: RiskClass::Elevated,
    };
    let profile_artifact_digest =
        canonical_policy_profile_artifact_digest_v1(&profile).expect("profile digest");
    let signed_profile = SignedPolicyProfileV1 {
        profile,
        artifact_digest: profile_artifact_digest,
        signature: signature(
            &signing_key,
            QualificationArtifactKindV1::PolicyProfile,
            profile_artifact_digest,
        ),
    };

    let candidates = current_candidates(&model);
    let candidate_set_digest =
        canonical_candidate_set_digest_v1(&candidates).expect("candidate set digest");
    let canonical_order_digest =
        canonical_candidate_order_digest_v1(&candidates).expect("candidate order digest");
    let state_digest = digest(b"state:frozen-decision-10");
    let objective_digest = digest(b"objective:frozen-decision-10");

    let scorer_descriptor = LearnedScorerDescriptorV1 {
        producer_module: id("learning.scorer.runtime"),
        interface_digest: digest(b"hepta.intuition.learned-scorer-output.v1"),
        feature_schema_digest: digest(b"action_id,segment"),
        score_semantics_digest: digest(b"utility_q32_raw,confidence_ppm,ood_score_ppm"),
        model_digest,
        generation: 7,
    };
    let scorer_descriptor_digest =
        canonical_learned_scorer_descriptor_digest_v1(&scorer_descriptor)
            .expect("scorer descriptor digest");
    let scorer_predictions_digest =
        canonical_scorer_predictions_digest_v1(&candidates).expect("scorer predictions digest");
    let scorer = LearnedScorerOutputBindingV1 {
        descriptor: scorer_descriptor,
        state_digest,
        candidate_set_digest,
        predictions_digest: scorer_predictions_digest,
    };

    let mut calibration_payload = CalibrationQualificationPayloadV1 {
        calibration: CalibrationArtifactV1 {
            artifact_digest: digest(b"pending-calibration"),
            policy_digest,
            objective_class_digest,
            generation: 7,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            measured_ece_ppm,
            subgroup_audit_digest: digest(b"frozen-subgroup-audit:v1"),
        },
        profile_artifact_digest,
        frozen_dataset_digest,
        scorer_descriptor_digest,
        model_digest,
        frozen_predictions_digest,
    };
    let calibration_digest =
        canonical_calibration_qualification_digest_v1(&calibration_payload)
            .expect("calibration digest");
    calibration_payload.calibration.artifact_digest = calibration_digest;
    let signed_calibration = SignedCalibrationQualificationV1 {
        payload: calibration_payload.clone(),
        artifact_digest: calibration_digest,
        signature: signature(
            &signing_key,
            QualificationArtifactKindV1::Calibration,
            calibration_digest,
        ),
    };

    let mut ood_payload = OodQualificationPayloadV1 {
        ood: OodArtifactV1 {
            artifact_digest: digest(b"pending-ood"),
            policy_digest,
            detector_digest: digest(b"empirical-scorer:segment-ood:v1"),
            support_digest: digest(b"frozen-support:v1"),
            generation: 7,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: signed_profile.profile.maximum_in_domain_score,
            measured_false_acceptance_ppm,
        },
        profile_artifact_digest,
        frozen_dataset_digest,
        scorer_descriptor_digest,
        model_digest,
        frozen_predictions_digest,
    };
    let ood_digest = canonical_ood_qualification_digest_v1(&ood_payload).expect("ood digest");
    ood_payload.ood.artifact_digest = ood_digest;
    let signed_ood = SignedOodQualificationV1 {
        payload: ood_payload.clone(),
        artifact_digest: ood_digest,
        signature: signature(
            &signing_key,
            QualificationArtifactKindV1::Ood,
            ood_digest,
        ),
    };

    let mut completeness_payload = CompletenessQualificationPayloadV1 {
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest(b"pending-completeness"),
            generator_digest: digest(b"legal-candidate-generator:v4"),
            grammar_digest: digest(b"action-grammar:v3"),
            hard_filter_digest: digest(b"hard-filter:v5"),
            truncation_digest: digest(b"no-truncation:v1"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: u32::try_from(candidates.len()).expect("candidate count fits"),
            omitted_count_bound: 0,
        },
        profile_artifact_digest,
        policy_digest,
        objective_digest,
        state_digest,
        generation: 7,
        scorer_descriptor_digest,
        scorer_predictions_digest,
    };
    let completeness_digest =
        canonical_completeness_qualification_digest_v1(&completeness_payload)
            .expect("completeness digest");
    completeness_payload.completeness.receipt_digest = completeness_digest;
    let signed_completeness = SignedCompletenessQualificationV1 {
        payload: completeness_payload.clone(),
        artifact_digest: completeness_digest,
        signature: signature(
            &signing_key,
            QualificationArtifactKindV1::Completeness,
            completeness_digest,
        ),
    };

    let request = CalibratedDecisionRequestV1 {
        decision_id: id("decision:frozen-qualification"),
        objective_digest,
        objective_class_digest,
        state_digest,
        policy_digest,
        policy_generation: 7,
        sequence: 10,
        minimum_confidence: signed_profile.profile.minimum_confidence,
        maximum_ece_ppm: signed_profile.profile.maximum_ece_ppm,
        maximum_ood_false_acceptance_ppm: signed_profile
            .profile
            .maximum_ood_false_acceptance_ppm,
        risk_class: RiskClass::Low,
        completeness: completeness_payload.completeness,
        calibration: calibration_payload.calibration,
        ood: ood_payload.ood,
        assignment: AssignmentModeV1::Deterministic,
        candidates,
    };

    (
        AuthenticatedCalibratedDecisionRequestV1 {
            request,
            policy_profile: signed_profile,
            calibration_qualification: signed_calibration,
            ood_qualification: signed_ood,
            completeness_qualification: signed_completeness,
            scorer,
        },
        verifier,
        measured_ece_ppm,
        measured_false_acceptance_ppm,
    )
}
