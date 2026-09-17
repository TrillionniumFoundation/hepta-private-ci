fn authenticated_fixture(
    candidate_count: usize,
) -> Result<
    (
        AuthenticatedCalibratedDecisionRequestV1,
        QualificationArtifactVerifierV1,
    ),
    Box<dyn Error>,
> {
    let signing_key = SigningKey::from_bytes(&[31; 32]);
    let verifier = QualificationArtifactVerifierV1::new(
        id("qualification:intuition-fast-gate")?,
        SIGNER_EPOCH,
        signing_key.verifying_key(),
    )?;
    let policy_digest = digest(b"benchmark-policy:generation-7");
    let objective_class_digest = digest(b"objective-class:benchmark");
    let objective_digest = digest(b"objective:benchmark");
    let state_digest = digest(b"state:benchmark");

    let profile = CanonicalPolicyProfileV1 {
        profile_id: id("intuition-profile:benchmark:v1")?,
        policy_digest,
        objective_class_digest,
        generation: 7,
        valid_from_sequence: 1,
        expires_after_sequence: 100,
        minimum_confidence: probability_ppm(600_000)?,
        maximum_ece_ppm: 50_000,
        maximum_ood_false_acceptance_ppm: 5_000,
        maximum_in_domain_score: probability_ppm(250_000)?,
        maximum_fast_path_risk: RiskClass::Elevated,
    };
    let profile_artifact_digest = canonical_policy_profile_artifact_digest_v1(&profile)?;
    let signed_profile = SignedPolicyProfileV1 {
        profile,
        artifact_digest: profile_artifact_digest,
        signature: sign(
            &signing_key,
            QualificationArtifactKindV1::PolicyProfile,
            profile_artifact_digest,
        )?,
    };

    let mut candidates = Vec::with_capacity(candidate_count);
    for index in 0..candidate_count {
        candidates.push(CalibratedActionCandidateV1 {
            candidate_id: id(&format!("candidate:{index:03}"))?,
            legal: true,
            hard_veto: false,
            utility: FixedQ32::from_raw(1_000_000 - i64::try_from(index)?),
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: ProbabilityQ32::ZERO,
            support_digest: digest(format!("support:{index:03}").as_bytes()),
        });
    }
    let candidate_set_digest = canonical_candidate_set_digest_v1(&candidates)?;
    let canonical_order_digest = canonical_candidate_order_digest_v1(&candidates)?;

    let scorer_descriptor = LearnedScorerDescriptorV1 {
        producer_module: id("learning.scorer.runtime")?,
        interface_digest: digest(b"hepta.intuition.learned-scorer-output.v1"),
        feature_schema_digest: digest(b"benchmark-feature-schema:v1"),
        score_semantics_digest: digest(b"utility,confidence,ood:v1"),
        model_digest: digest(b"benchmark-model:v1"),
        generation: 7,
    };
    let scorer_descriptor_digest =
        canonical_learned_scorer_descriptor_digest_v1(&scorer_descriptor)?;
    let scorer_predictions_digest = canonical_scorer_predictions_digest_v1(&candidates)?;
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
            measured_ece_ppm: 0,
            subgroup_audit_digest: digest(b"benchmark-subgroup-audit:v1"),
        },
        profile_artifact_digest,
        frozen_dataset_digest: digest(b"benchmark-frozen-dataset:v1"),
        scorer_descriptor_digest,
        model_digest: scorer.descriptor.model_digest,
        frozen_predictions_digest: digest(b"benchmark-frozen-predictions:v1"),
    };
    let calibration_digest = canonical_calibration_qualification_digest_v1(&calibration_payload)?;
    calibration_payload.calibration.artifact_digest = calibration_digest;
    let signed_calibration = SignedCalibrationQualificationV1 {
        payload: calibration_payload.clone(),
        artifact_digest: calibration_digest,
        signature: sign(
            &signing_key,
            QualificationArtifactKindV1::Calibration,
            calibration_digest,
        )?,
    };

    let mut ood_payload = OodQualificationPayloadV1 {
        ood: OodArtifactV1 {
            artifact_digest: digest(b"pending-ood"),
            policy_digest,
            detector_digest: digest(b"benchmark-ood-detector:v1"),
            support_digest: digest(b"benchmark-ood-support:v1"),
            generation: 7,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            maximum_in_domain_score: signed_profile.profile.maximum_in_domain_score,
            measured_false_acceptance_ppm: 0,
        },
        profile_artifact_digest,
        frozen_dataset_digest: digest(b"benchmark-frozen-dataset:v1"),
        scorer_descriptor_digest,
        model_digest: scorer.descriptor.model_digest,
        frozen_predictions_digest: digest(b"benchmark-frozen-predictions:v1"),
    };
    let ood_digest = canonical_ood_qualification_digest_v1(&ood_payload)?;
    ood_payload.ood.artifact_digest = ood_digest;
    let signed_ood = SignedOodQualificationV1 {
        payload: ood_payload.clone(),
        artifact_digest: ood_digest,
        signature: sign(
            &signing_key,
            QualificationArtifactKindV1::Ood,
            ood_digest,
        )?,
    };

    let mut completeness_payload = CompletenessQualificationPayloadV1 {
        completeness: CandidateSetCompletenessBindingV1 {
            receipt_digest: digest(b"pending-completeness"),
            generator_digest: digest(b"benchmark-generator:v1"),
            grammar_digest: digest(b"benchmark-grammar:v1"),
            hard_filter_digest: digest(b"benchmark-hard-filter:v1"),
            truncation_digest: digest(b"no-truncation:v1"),
            candidate_set_digest,
            canonical_order_digest,
            candidate_count: u32::try_from(candidate_count)?,
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
        canonical_completeness_qualification_digest_v1(&completeness_payload)?;
    completeness_payload.completeness.receipt_digest = completeness_digest;
    let signed_completeness = SignedCompletenessQualificationV1 {
        payload: completeness_payload.clone(),
        artifact_digest: completeness_digest,
        signature: sign(
            &signing_key,
            QualificationArtifactKindV1::Completeness,
            completeness_digest,
        )?,
    };

    let request = CalibratedDecisionRequestV1 {
        decision_id: id(&format!("decision:benchmark:{candidate_count}"))?,
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

    Ok((
        AuthenticatedCalibratedDecisionRequestV1 {
            request,
            policy_profile: signed_profile,
            calibration_qualification: signed_calibration,
            ood_qualification: signed_ood,
            completeness_qualification: signed_completeness,
            scorer,
        },
        verifier,
    ))
}
