pub fn qualification_signature_message_v1(
    kind: QualificationArtifactKindV1,
    artifact_digest: Digest32,
    signer_id: &StableId,
    signer_epoch: u64,
) -> Result<Vec<u8>, QualificationError> {
    let mut bytes = QUALIFICATION_SIGNATURE_DOMAIN_V1.to_vec();
    bytes.push(artifact_kind_code(kind));
    bytes.extend_from_slice(artifact_digest.as_array());
    push_stable_id(&mut bytes, signer_id)?;
    bytes.extend_from_slice(&signer_epoch.to_be_bytes());
    Ok(bytes)
}

pub fn canonical_policy_profile_artifact_digest_v1(
    profile: &CanonicalPolicyProfileV1,
) -> Result<Digest32, QualificationError> {
    let mut bytes = b"hepta.intuition.policy-profile.v1".to_vec();
    push_stable_id(&mut bytes, &profile.profile_id)?;
    bytes.extend_from_slice(profile.policy_digest.as_array());
    bytes.extend_from_slice(profile.objective_class_digest.as_array());
    bytes.extend_from_slice(&profile.generation.to_be_bytes());
    bytes.extend_from_slice(&profile.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&profile.expires_after_sequence.to_be_bytes());
    bytes.extend_from_slice(&profile.minimum_confidence.raw().to_be_bytes());
    bytes.extend_from_slice(&profile.maximum_ece_ppm.to_be_bytes());
    bytes.extend_from_slice(&profile.maximum_ood_false_acceptance_ppm.to_be_bytes());
    bytes.extend_from_slice(&profile.maximum_in_domain_score.raw().to_be_bytes());
    bytes.push(risk_rank(profile.maximum_fast_path_risk));
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_learned_scorer_descriptor_digest_v1(
    descriptor: &LearnedScorerDescriptorV1,
) -> Result<Digest32, QualificationError> {
    let mut bytes = b"hepta.intuition.learned-scorer-descriptor.v1".to_vec();
    push_stable_id(&mut bytes, &descriptor.producer_module)?;
    for digest in [
        descriptor.interface_digest,
        descriptor.feature_schema_digest,
        descriptor.score_semantics_digest,
        descriptor.model_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&descriptor.generation.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

/// Canonical commitment to learned outputs consumed by the policy. Legality,
/// hard-veto and assignment probabilities are not learned-score fields; they
/// remain committed by the complete candidate-set digest.
pub fn canonical_scorer_predictions_digest_v1(
    candidates: &[CalibratedActionCandidateV1],
) -> Result<Digest32, QualificationError> {
    let mut bytes = b"hepta.intuition.learned-scorer-predictions.v1".to_vec();
    let count = u32::try_from(candidates.len()).map_err(|_| QualificationError::Arithmetic)?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for candidate in candidates {
        push_stable_id(&mut bytes, &candidate.candidate_id)?;
        bytes.extend_from_slice(&candidate.utility.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.calibrated_confidence.raw().to_be_bytes());
        bytes.extend_from_slice(&candidate.ood_score.raw().to_be_bytes());
        bytes.extend_from_slice(candidate.support_digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_calibration_qualification_digest_v1(
    payload: &CalibrationQualificationPayloadV1,
) -> Result<Digest32, QualificationError> {
    let calibration = &payload.calibration;
    let mut bytes = b"hepta.intuition.calibration-qualification.v1".to_vec();
    for digest in [
        calibration.policy_digest,
        calibration.objective_class_digest,
        calibration.subgroup_audit_digest,
        payload.profile_artifact_digest,
        payload.frozen_dataset_digest,
        payload.scorer_descriptor_digest,
        payload.model_digest,
        payload.frozen_predictions_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&calibration.generation.to_be_bytes());
    bytes.extend_from_slice(&calibration.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&calibration.expires_after_sequence.to_be_bytes());
    bytes.extend_from_slice(&calibration.measured_ece_ppm.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_ood_qualification_digest_v1(
    payload: &OodQualificationPayloadV1,
) -> Result<Digest32, QualificationError> {
    let ood = &payload.ood;
    let mut bytes = b"hepta.intuition.ood-qualification.v1".to_vec();
    for digest in [
        ood.policy_digest,
        ood.detector_digest,
        ood.support_digest,
        payload.profile_artifact_digest,
        payload.frozen_dataset_digest,
        payload.scorer_descriptor_digest,
        payload.model_digest,
        payload.frozen_predictions_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&ood.generation.to_be_bytes());
    bytes.extend_from_slice(&ood.valid_from_sequence.to_be_bytes());
    bytes.extend_from_slice(&ood.expires_after_sequence.to_be_bytes());
    bytes.extend_from_slice(&ood.maximum_in_domain_score.raw().to_be_bytes());
    bytes.extend_from_slice(&ood.measured_false_acceptance_ppm.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_completeness_qualification_digest_v1(
    payload: &CompletenessQualificationPayloadV1,
) -> Result<Digest32, QualificationError> {
    let completeness = &payload.completeness;
    let mut bytes = b"hepta.intuition.completeness-qualification.v1".to_vec();
    for digest in [
        completeness.generator_digest,
        completeness.grammar_digest,
        completeness.hard_filter_digest,
        completeness.truncation_digest,
        completeness.candidate_set_digest,
        completeness.canonical_order_digest,
        payload.profile_artifact_digest,
        payload.policy_digest,
        payload.objective_digest,
        payload.state_digest,
        payload.scorer_descriptor_digest,
        payload.scorer_predictions_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&completeness.candidate_count.to_be_bytes());
    bytes.extend_from_slice(&completeness.omitted_count_bound.to_be_bytes());
    bytes.extend_from_slice(&payload.generation.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn canonical_authenticated_request_digest_v1(
    request: &AuthenticatedCalibratedDecisionRequestV1,
) -> Result<Digest32, QualifiedCalibratedError> {
    let mut bytes = b"hepta.intuition.authenticated-request.v1".to_vec();
    bytes.extend_from_slice(canonical_calibrated_request_digest_v1(&request.request)?.as_array());
    for digest in [
        request.policy_profile.artifact_digest,
        request.calibration_qualification.artifact_digest,
        request.ood_qualification.artifact_digest,
        request.completeness_qualification.artifact_digest,
        canonical_learned_scorer_descriptor_digest_v1(&request.scorer.descriptor)?,
        request.scorer.predictions_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for signature in [
        &request.policy_profile.signature,
        &request.calibration_qualification.signature,
        &request.ood_qualification.signature,
        &request.completeness_qualification.signature,
    ] {
        push_stable_id(&mut bytes, &signature.signer_id)?;
        bytes.extend_from_slice(&signature.signer_epoch.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}
