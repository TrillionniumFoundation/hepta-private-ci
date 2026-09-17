#[test]
fn frozen_model_and_validation_data_drive_signed_v3_decision() {
    let (authenticated, verifier, measured_ece_ppm, measured_far_ppm) = authenticated_fixture();
    assert!(measured_ece_ppm <= authenticated.policy_profile.profile.maximum_ece_ppm);
    assert!(
        measured_far_ppm
            <= authenticated
                .policy_profile
                .profile
                .maximum_ood_false_acceptance_ppm
    );
    assert_eq!(
        authenticated.calibration_qualification.payload.frozen_dataset_digest,
        digest(FROZEN_VALIDATION.as_bytes())
    );
    assert_eq!(
        authenticated.scorer.descriptor.model_digest,
        digest(FROZEN_MODEL.as_bytes())
    );

    let receipt = decide_calibrated_v3(authenticated, &verifier).expect("qualified v3 decision");
    assert_eq!(
        receipt.decision.disposition,
        CalibratedDispositionV1::Selected(id("candidate:a"))
    );
    assert!(!receipt.authority.grants_any());
    assert!(!receipt.decision.authority.grants_any());
}

#[test]
fn v2_rejects_nonzero_omitted_count_bound_inside_intuition_crate() {
    let (mut authenticated, _verifier, _, _) = authenticated_fixture();
    authenticated.request.completeness.omitted_count_bound = 1;
    assert_eq!(
        decide_calibrated_v2(authenticated.request),
        Err(CalibratedError::CandidateSetMismatch)
    );
}

#[test]
fn v3_rejects_tampered_qualification_signature() {
    let (mut authenticated, verifier, _, _) = authenticated_fixture();
    authenticated.policy_profile.signature.signature[0] ^= 1;
    assert_eq!(
        decide_calibrated_v3(authenticated, &verifier),
        Err(QualifiedCalibratedError::Qualification(
            QualificationError::SignatureInvalid
        ))
    );
}

#[test]
fn v3_rejects_caller_threshold_override() {
    let (mut authenticated, verifier, _, _) = authenticated_fixture();
    authenticated.request.maximum_ece_ppm += 1;
    assert_eq!(
        decide_calibrated_v3(authenticated, &verifier),
        Err(QualifiedCalibratedError::Qualification(
            QualificationError::ProfileMismatch("thresholds")
        ))
    );
}

#[test]
fn v3_rejects_scorer_output_drift() {
    let (mut authenticated, verifier, _, _) = authenticated_fixture();
    authenticated.scorer.predictions_digest = digest(b"forged-predictions");
    assert_eq!(
        decide_calibrated_v3(authenticated, &verifier),
        Err(QualifiedCalibratedError::Qualification(
            QualificationError::ScorerMismatch("predictions")
        ))
    );
}

#[test]
fn frozen_metrics_are_computed_not_caller_asserted() {
    let model = parse_model();
    let validation = parse_validation();
    let (ece, far, predictions_digest) = frozen_metrics(&model, &validation);
    assert_eq!(ece, 0);
    assert_eq!(far, 0);
    assert!(!predictions_digest.is_zero());
}
