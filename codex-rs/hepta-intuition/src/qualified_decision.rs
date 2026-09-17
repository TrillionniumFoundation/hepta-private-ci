pub fn decide_calibrated_v3(
    authenticated: AuthenticatedCalibratedDecisionRequestV1,
    verifier: &QualificationArtifactVerifierV1,
) -> Result<QualifiedCalibratedIntuitionReceiptV1, QualifiedCalibratedError> {
    validate_authenticated_request(&authenticated, verifier)?;
    let request_digest = canonical_authenticated_request_digest_v1(&authenticated)?;
    let scorer_descriptor_digest =
        canonical_learned_scorer_descriptor_digest_v1(&authenticated.scorer.descriptor)?;
    let qualification_bundle_digest = qualification_bundle_digest(&authenticated)?;
    let profile_digest = authenticated.policy_profile.artifact_digest;
    let calibration_digest = authenticated.calibration_qualification.artifact_digest;
    let ood_digest = authenticated.ood_qualification.artifact_digest;
    let completeness_digest = authenticated.completeness_qualification.artifact_digest;
    let scorer_predictions_digest = authenticated.scorer.predictions_digest;

    let decision = decide_calibrated_v2(authenticated.request)?;
    let mut bytes = b"hepta.intuition.calibrated-decision.v3".to_vec();
    bytes.extend_from_slice(request_digest.as_array());
    bytes.extend_from_slice(qualification_bundle_digest.as_array());
    bytes.extend_from_slice(decision.receipt_digest.as_array());
    let receipt_digest = Digest32::of_bytes(&bytes);

    Ok(QualifiedCalibratedIntuitionReceiptV1 {
        decision,
        policy_profile_artifact_digest: profile_digest,
        calibration_qualification_digest: calibration_digest,
        ood_qualification_digest: ood_digest,
        completeness_qualification_digest: completeness_digest,
        scorer_descriptor_digest,
        scorer_predictions_digest,
        qualification_bundle_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_authenticated_request(
    authenticated: &AuthenticatedCalibratedDecisionRequestV1,
    verifier: &QualificationArtifactVerifierV1,
) -> Result<(), QualifiedCalibratedError> {
    let request = &authenticated.request;
    let signed_profile = &authenticated.policy_profile;
    let profile = &signed_profile.profile;

    validate_profile(profile)?;
    let profile_digest = canonical_policy_profile_artifact_digest_v1(profile)?;
    if signed_profile.artifact_digest != profile_digest {
        return Err(QualificationError::DigestMismatch("policy profile").into());
    }
    verifier.verify_signature(
        QualificationArtifactKindV1::PolicyProfile,
        signed_profile.artifact_digest,
        &signed_profile.signature,
    )?;
    validate_window(
        profile.valid_from_sequence,
        profile.expires_after_sequence,
        request.sequence,
    )?;
    if profile.policy_digest != request.policy_digest {
        return Err(QualificationError::ProfileMismatch("policy digest").into());
    }
    if profile.objective_class_digest != request.objective_class_digest {
        return Err(QualificationError::ProfileMismatch("objective class").into());
    }
    if profile.generation != request.policy_generation {
        return Err(QualificationError::ProfileMismatch("generation").into());
    }
    if request.minimum_confidence != profile.minimum_confidence
        || request.maximum_ece_ppm != profile.maximum_ece_ppm
        || request.maximum_ood_false_acceptance_ppm
            != profile.maximum_ood_false_acceptance_ppm
        || request.ood.maximum_in_domain_score != profile.maximum_in_domain_score
    {
        return Err(QualificationError::ProfileMismatch("thresholds").into());
    }

    validate_scorer(authenticated)?;
    let scorer_descriptor_digest =
        canonical_learned_scorer_descriptor_digest_v1(&authenticated.scorer.descriptor)?;

    let calibration = &authenticated.calibration_qualification;
    let calibration_digest = canonical_calibration_qualification_digest_v1(&calibration.payload)?;
    if calibration.artifact_digest != calibration_digest
        || calibration.payload.calibration.artifact_digest != calibration_digest
    {
        return Err(QualificationError::DigestMismatch("calibration qualification").into());
    }
    verifier.verify_signature(
        QualificationArtifactKindV1::Calibration,
        calibration.artifact_digest,
        &calibration.signature,
    )?;
    if calibration.payload.calibration != request.calibration
        || calibration.payload.profile_artifact_digest != signed_profile.artifact_digest
        || calibration.payload.scorer_descriptor_digest != scorer_descriptor_digest
        || calibration.payload.model_digest != authenticated.scorer.descriptor.model_digest
    {
        return Err(QualificationError::ArtifactMismatch("calibration binding").into());
    }
    require_nonzero(
        calibration.payload.frozen_dataset_digest,
        "calibration frozen dataset",
    )?;
    require_nonzero(
        calibration.payload.frozen_predictions_digest,
        "calibration frozen predictions",
    )?;

    let ood = &authenticated.ood_qualification;
    let ood_digest = canonical_ood_qualification_digest_v1(&ood.payload)?;
    if ood.artifact_digest != ood_digest || ood.payload.ood.artifact_digest != ood_digest {
        return Err(QualificationError::DigestMismatch("ood qualification").into());
    }
    verifier.verify_signature(
        QualificationArtifactKindV1::Ood,
        ood.artifact_digest,
        &ood.signature,
    )?;
    if ood.payload.ood != request.ood
        || ood.payload.profile_artifact_digest != signed_profile.artifact_digest
        || ood.payload.scorer_descriptor_digest != scorer_descriptor_digest
        || ood.payload.model_digest != authenticated.scorer.descriptor.model_digest
    {
        return Err(QualificationError::ArtifactMismatch("ood binding").into());
    }
    require_nonzero(ood.payload.frozen_dataset_digest, "ood frozen dataset")?;
    require_nonzero(
        ood.payload.frozen_predictions_digest,
        "ood frozen predictions",
    )?;

    let completeness = &authenticated.completeness_qualification;
    let completeness_digest = canonical_completeness_qualification_digest_v1(&completeness.payload)?;
    if completeness.artifact_digest != completeness_digest
        || completeness.payload.completeness.receipt_digest != completeness_digest
    {
        return Err(QualificationError::DigestMismatch("completeness qualification").into());
    }
    verifier.verify_signature(
        QualificationArtifactKindV1::Completeness,
        completeness.artifact_digest,
        &completeness.signature,
    )?;
    if completeness.payload.completeness != request.completeness
        || completeness.payload.profile_artifact_digest != signed_profile.artifact_digest
        || completeness.payload.policy_digest != request.policy_digest
        || completeness.payload.objective_digest != request.objective_digest
        || completeness.payload.state_digest != request.state_digest
        || completeness.payload.generation != request.policy_generation
        || completeness.payload.scorer_descriptor_digest != scorer_descriptor_digest
        || completeness.payload.scorer_predictions_digest != authenticated.scorer.predictions_digest
    {
        return Err(QualificationError::ArtifactMismatch("completeness binding").into());
    }

    if request.completeness.omitted_count_bound != 0 {
        return Err(QualificationError::ArtifactMismatch("incomplete candidate set").into());
    }
    Ok(())
}

fn validate_profile(profile: &CanonicalPolicyProfileV1) -> Result<(), QualificationError> {
    for (name, digest) in [
        ("profile policy", profile.policy_digest),
        ("profile objective class", profile.objective_class_digest),
    ] {
        require_nonzero(digest, name)?;
    }
    if profile.generation == 0
        || profile.valid_from_sequence > profile.expires_after_sequence
        || profile.maximum_ece_ppm > 1_000_000
        || profile.maximum_ood_false_acceptance_ppm > 1_000_000
    {
        return Err(QualificationError::WindowInvalid);
    }
    // V3 freezes the currently implemented hard rule: Low/Elevated may use
    // the fast path, High must take the deterministic slow path. A future
    // profile revision can change this only together with a new decision kernel.
    if profile.maximum_fast_path_risk != RiskClass::Elevated {
        return Err(QualificationError::UnsafeFastPathRisk);
    }
    Ok(())
}

fn validate_scorer(
    authenticated: &AuthenticatedCalibratedDecisionRequestV1,
) -> Result<(), QualifiedCalibratedError> {
    let scorer = &authenticated.scorer;
    let request = &authenticated.request;
    for (name, digest) in [
        ("scorer interface", scorer.descriptor.interface_digest),
        ("scorer feature schema", scorer.descriptor.feature_schema_digest),
        ("scorer score semantics", scorer.descriptor.score_semantics_digest),
        ("scorer model", scorer.descriptor.model_digest),
        ("scorer state", scorer.state_digest),
        ("scorer candidate set", scorer.candidate_set_digest),
        ("scorer predictions", scorer.predictions_digest),
    ] {
        require_nonzero(digest, name)?;
    }
    if scorer.descriptor.generation != request.policy_generation {
        return Err(QualificationError::ScorerMismatch("generation").into());
    }
    if scorer.state_digest != request.state_digest
        || scorer.candidate_set_digest != request.completeness.candidate_set_digest
    {
        return Err(QualificationError::ScorerMismatch("request lineage").into());
    }
    if scorer.predictions_digest != canonical_scorer_predictions_digest_v1(&request.candidates)? {
        return Err(QualificationError::ScorerMismatch("predictions").into());
    }
    Ok(())
}

fn qualification_bundle_digest(
    authenticated: &AuthenticatedCalibratedDecisionRequestV1,
) -> Result<Digest32, QualificationError> {
    let mut bytes = b"hepta.intuition.qualification-bundle.v1".to_vec();
    for digest in [
        authenticated.policy_profile.artifact_digest,
        authenticated.calibration_qualification.artifact_digest,
        authenticated.ood_qualification.artifact_digest,
        authenticated.completeness_qualification.artifact_digest,
        canonical_learned_scorer_descriptor_digest_v1(&authenticated.scorer.descriptor)?,
        authenticated.scorer.predictions_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_window(
    valid_from_sequence: u64,
    expires_after_sequence: u64,
    sequence: u64,
) -> Result<(), QualificationError> {
    if valid_from_sequence > expires_after_sequence {
        return Err(QualificationError::WindowInvalid);
    }
    if sequence < valid_from_sequence || sequence > expires_after_sequence {
        return Err(QualificationError::ArtifactExpired);
    }
    Ok(())
}

fn require_nonzero(digest: Digest32, name: &'static str) -> Result<(), QualificationError> {
    if digest.is_zero() {
        return Err(QualificationError::EmptyDigest(name));
    }
    Ok(())
}

fn artifact_kind_code(kind: QualificationArtifactKindV1) -> u8 {
    match kind {
        QualificationArtifactKindV1::PolicyProfile => 0,
        QualificationArtifactKindV1::Calibration => 1,
        QualificationArtifactKindV1::Ood => 2,
        QualificationArtifactKindV1::Completeness => 3,
    }
}

fn risk_rank(risk: RiskClass) -> u8 {
    match risk {
        RiskClass::Low => 0,
        RiskClass::Elevated => 1,
        RiskClass::High => 2,
    }
}

fn push_stable_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), QualificationError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| QualificationError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}
