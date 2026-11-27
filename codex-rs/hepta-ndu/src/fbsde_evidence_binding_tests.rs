use super::*;
use crate::AdmittedCovarianceProfileV1;
use crate::AdmittedZConversionProfileV1;
use crate::CovarianceConventionV1;
use crate::NduCoefficientProfileV1;
use crate::NduCovarianceProfileV1;
use crate::NduZConversionProfileV1;
use crate::ZCoordinateConventionV1;
use crate::admit_covariance_profile;
use crate::admit_ndu_coefficient_profile;
use crate::admit_z_conversion_profile;
use crate::fbsde_training::*;
use pretty_assertions::assert_eq;

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn q24(value: f64) -> i64 {
    // This fixture uses only exactly representable binary fractions.
    (value * 16_777_216.0) as i64
}

fn fixture_snapshot(locator: &str) -> Result<NduFbsdeDatasetSnapshotV1, NduFbsdeTrainingError> {
    let points = [
        (-2.0, -3.0, NduFbsdeFoldV1::Train),
        (-1.0, 2.0, NduFbsdeFoldV1::Train),
        (0.0, -2.0, NduFbsdeFoldV1::Train),
        (1.0, 3.0, NduFbsdeFoldV1::Train),
        (2.0, -1.0, NduFbsdeFoldV1::Train),
        (3.0, 1.0, NduFbsdeFoldV1::Train),
        (-1.5, -2.5, NduFbsdeFoldV1::Holdout),
        (0.5, 1.5, NduFbsdeFoldV1::Holdout),
        (2.5, 2.5, NduFbsdeFoldV1::Holdout),
    ];
    let mut trajectories = Vec::new();
    for (index, (feature, increment, fold)) in points.into_iter().enumerate() {
        let base = 1_700_000_000_000_u64 + index as u64 * 10_000;
        let step = |sequence: u32, offset: u64, feature_value: f64| NduFbsdeStepV1 {
            sequence,
            start_unix_ms: base + offset,
            end_unix_ms: base + offset + 1_000,
            feature_observed_unix_ms: base + offset,
            increment_observed_unix_ms: base + offset + 1_000,
            running_utility_observed_unix_ms: base + offset + 1_000,
            conditioning_digest: digest(&format!("conditioning-{sequence}")),
            feature_provenance_digest: digest(&format!("feature-{index}-{sequence}")),
            increment_provenance_digest: digest(&format!("increment-{index}-{sequence}")),
            running_utility_provenance_digest: digest(&format!("running-{index}-{sequence}")),
            features_q24: vec![q24(feature_value)],
            increment_q24: vec![q24(increment)],
            running_utility_q24: vec![q24(0.25 * feature_value)],
        };
        trajectories.push(NduFbsdeTrajectoryV1 {
            trajectory_digest: digest(&format!("trajectory-{index:03}")),
            episode_digest: digest(&format!("episode-{index:03}")),
            principal_scope_digest: digest("principal"),
            fold,
            steps: vec![step(1, 0, feature), step(2, 2_000, feature + 0.25)],
            // Positive replay fixture has a realizable conditional value target.
            // Future-increment noise is tested separately as a rejected dataset.
            terminal_utility_q24: vec![q24(1.5 * feature)],
            terminal_outcome_digest: digest(&format!("outcome-{index}")),
            terminal_provenance_digest: digest(&format!("terminal-{index}")),
            terminal_observed_unix_ms: base + 4_000,
        });
    }
    seal_ndu_fbsde_dataset_v1(NduFbsdeDatasetSnapshotV1 {
        dataset_digest: Digest32::ZERO,
        immutable_locator_digest: digest(locator),
        provenance_digest: digest("dataset-provenance"),
        objective_class_digest: digest("objective"),
        feature_schema_digest: digest("feature-schema"),
        increment_schema_digest: digest("increment-schema"),
        outcome_schema_digest: digest("outcome-schema"),
        filtration_digest: digest("filtration"),
        normalization_digest: digest("normalization"),
        fold_assignment_digest: digest("split"),
        trusted_time_digest: digest("trusted-time"),
        snapshot_unix_ms: 1_700_000_200_000,
        feature_dimension: 1,
        driver_dimension: 1,
        utility_dimension: 1,
        horizon: 2,
        trajectories,
    })
}

fn profiles(
    snapshot: &NduFbsdeDatasetSnapshotV1,
) -> Result<
    (
        AdmittedNduFbsdeTrainingPolicyV1,
        AdmittedCovarianceProfileV1,
        AdmittedZConversionProfileV1,
    ),
    Box<dyn StdError>,
> {
    let units = digest("units");
    let covariance = admit_covariance_profile(NduCovarianceProfileV1 {
        units_digest: units,
        driver_dimension: 1,
        utility_dimension: 1,
        convention: CovarianceConventionV1::Increment,
        minimum_increment_eigenvalue: 1e-8,
        maximum_condition: 1_000.0,
        maximum_absolute_sample: 100.0,
        maximum_absolute_z: 100.0,
        maximum_relative_residual: 1e-8,
    })?;
    let z = admit_z_conversion_profile(NduZConversionProfileV1 {
        units_digest: units,
        driver_dimension: 1,
        utility_dimension: 1,
        source_coordinates: ZCoordinateConventionV1::OriginalIncrement,
        whitening_lower: Vec::new(),
        maximum_absolute_z: 100.0,
    })?;
    let policy = admit_ndu_fbsde_training_policy_v1(NduFbsdeTrainingPolicyV1 {
        dataset_digest: snapshot.dataset_digest,
        objective_class_digest: snapshot.objective_class_digest,
        feature_schema_digest: snapshot.feature_schema_digest,
        increment_schema_digest: snapshot.increment_schema_digest,
        outcome_schema_digest: snapshot.outcome_schema_digest,
        filtration_digest: snapshot.filtration_digest,
        normalization_digest: snapshot.normalization_digest,
        runtime_tuple_digest: digest("runtime"),
        units_digest: units,
        feature_dimension: 1,
        driver_dimension: 1,
        utility_dimension: 1,
        horizon: 2,
        maximum_epochs: 16,
        ridge_penalty: 1e-8,
        convergence_tolerance: 1e-7,
        maximum_absolute_input: 100.0,
        maximum_absolute_value: 100.0,
        maximum_step_seconds: 1.0,
        maximum_holdout_rmse: 0.1,
        maximum_calibration_error: 0.1,
        minimum_holdout_improvement: 0.01,
        generator_y: vec![0.0],
        generator_z: vec![vec![0.0]],
    })?;
    Ok((policy, covariance, z))
}

struct AcceptanceFixture {
    candidate: NduFbsdeTrainingCandidateV1,
    reference: NduFbsdeReferenceReceiptV1,
    publication: NduFbsdePublicationBindingV1,
}

fn acceptance_fixture(locator: &str) -> Result<AcceptanceFixture, Box<dyn StdError>> {
    let snapshot = fixture_snapshot(locator)?;
    let (policy, covariance, z) = profiles(&snapshot)?;
    let candidate = train_discrete_ndu_fbsde_v1(&snapshot, &policy, &covariance)?;
    let reference = reference_evaluate_ndu_fbsde_v1(&snapshot, &policy, &candidate)?;
    let coefficient = admit_ndu_coefficient_profile(
        NduCoefficientProfileV1 {
            artifact_manifest_digest: digest("registered-manifest"),
            normalization_digest: snapshot.normalization_digest,
            runtime_tuple_digest: policy.runtime_tuple_digest(),
            covariance_profile_digest: covariance.digest(),
            z_conversion_profile_digest: z.digest(),
            units_digest: policy.units_digest(),
            driver_dimension: 1,
            utility_dimension: 1,
            expires_unix_ms: 1_800_000_000_000,
        },
        &covariance,
        &z,
    )?;
    let (publication, _) = bind_ndu_fbsde_publication_v1(
        &candidate,
        candidate.artifact_bytes_digest(),
        &coefficient,
        &z,
        /*now_unix_ms*/ 1_700_000_300_000,
    )?;
    Ok(AcceptanceFixture {
        candidate,
        reference,
        publication,
    })
}

fn shadow(
    candidate_digest: Digest32,
    reference_receipt_digest: Digest32,
) -> Result<NduFbsdeShadowGateReceiptV1, NduFbsdeTrainingError> {
    // Synthetic local acceptance metadata exercises identity binding only.
    // It is not independent model qualification or effect authority.
    evaluate_ndu_fbsde_shadow_gate_v1(
        &NduFbsdeShadowPolicyV1 {
            policy_digest: digest("shadow-policy"),
            minimum_advisory_episodes: 1,
            minimum_advisory_decisions: 1,
            minimum_restricted_episodes: 2,
            minimum_restricted_decisions: 2,
            maximum_failures: 0,
        },
        &NduFbsdeShadowEvidenceV1 {
            candidate_digest,
            reference_receipt_digest,
            convergence_acceptance_digest: digest("fixture-convergence"),
            calibration_acceptance_digest: digest("fixture-calibration"),
            utility_improvement_acceptance_digest: digest("fixture-utility"),
            regression_acceptance_digest: digest("fixture-regression"),
            target_host_receipt_digest: digest("fixture-host"),
            observed_episode_count: 2,
            observed_decision_count: 20,
            observed_failure_count: 0,
            window_start_unix_ms: 1,
            window_end_unix_ms: 2,
        },
    )
}

fn rollback_policy(
    maximum_holdout_rmse_q24: i64,
) -> Result<NduFbsdeRollbackPolicyV1, NduFbsdeIndependentEvidenceErrorV2> {
    NduFbsdeRollbackPolicyV1::new(
        maximum_holdout_rmse_q24,
        /*maximum_calibration_error_q24*/ 50,
        /*minimum_utility_improvement_q24*/ 1,
        /*maximum_failures*/ 0,
        /*minimum_runtime_decisions*/ 1,
    )
}

fn rollback(
    candidate: &NduFbsdeTrainingCandidateV1,
    policy: &NduFbsdeRollbackPolicyV1,
) -> Result<NduFbsdeRollbackReceiptV1, NduFbsdeIndependentEvidenceErrorV2> {
    let observation = NduFbsdeRuntimeObservationV1::new(
        candidate.candidate_digest(),
        /*holdout_rmse_q24*/ 0,
        /*calibration_error_q24*/ 0,
        /*utility_improvement_q24*/ 2,
        /*observed_failure_count*/ 0,
        /*observed_episode_count*/ 2,
        /*observed_decision_count*/ 20,
        /*window_start_ms*/ 1,
        /*window_end_ms*/ 2,
    )?;
    evaluate_fbsde_rollback_v1(policy, &observation)
}

fn independent_evidence(
    candidate: &NduFbsdeTrainingCandidateV1,
    policy: &NduFbsdeRollbackPolicyV1,
) -> NduFbsdeIndependentEvidenceV2 {
    NduFbsdeIndependentEvidenceV2 {
        registered_dataset_digest: candidate.dataset_digest(),
        immutable_dataset_locator_binding_digest: digest("fixture-locator-binding"),
        filtration_audit_digest: digest("fixture-filtration"),
        leakage_audit_digest: digest("fixture-leakage"),
        independent_numerical_oracle_digest: digest("fixture-oracle"),
        convergence_envelope_digest: digest("fixture-envelope"),
        calibration_acceptance_digest: digest("fixture-calibration"),
        utility_improvement_acceptance_digest: digest("fixture-utility"),
        regression_acceptance_digest: digest("fixture-regression"),
        shadow_volume_receipt_digest: digest("fixture-shadow-volume"),
        advisory_runtime_receipt_digest: digest("fixture-advisory"),
        restricted_write_runtime_receipt_digest: digest("fixture-restricted"),
        target_host_receipt_digest: digest("fixture-host"),
        rollback_policy_digest: policy.policy_digest,
        observed_episode_count: 2,
        observed_decision_count: 20,
        minimum_episode_count: 1,
        minimum_decision_count: 1,
        window_start_ms: 1,
        window_end_ms: 2,
    }
}

fn assert_same_chain(fixture: &AcceptanceFixture) -> Result<(), Box<dyn StdError>> {
    let policy = rollback_policy(/*maximum_holdout_rmse_q24*/ 100)?;
    let shadow = shadow(
        fixture.candidate.candidate_digest(),
        fixture.reference.receipt_digest(),
    )?;
    let rollback = rollback(&fixture.candidate, &policy)?;
    let evidence = independent_evidence(&fixture.candidate, &policy);
    let accepted = seal_fbsde_independent_acceptance_v2(
        &fixture.candidate,
        &fixture.reference,
        &fixture.publication,
        &shadow,
        &rollback,
        &evidence,
    )?;
    accepted.validate()?;
    assert_eq!(
        accepted.candidate_digest(),
        fixture.candidate.candidate_digest()
    );
    assert_eq!(accepted.authority(), AuthorityPosture::DENY_ALL);
    assert!(!accepted.production_activation());
    Ok(())
}

#[test]
fn independent_acceptance_rejects_another_candidates_shadow_receipt()
-> Result<(), Box<dyn StdError>> {
    let first = acceptance_fixture("immutable-locator-a")?;
    let second = acceptance_fixture("immutable-locator-b")?;
    assert_ne!(
        first.candidate.candidate_digest(),
        second.candidate.candidate_digest()
    );
    assert_same_chain(&first)?;
    assert_same_chain(&second)?;
    let policy = rollback_policy(/*maximum_holdout_rmse_q24*/ 100)?;
    let wrong_shadow = shadow(
        second.candidate.candidate_digest(),
        second.reference.receipt_digest(),
    )?;
    assert_eq!(
        seal_fbsde_independent_acceptance_v2(
            &first.candidate,
            &first.reference,
            &first.publication,
            &wrong_shadow,
            &rollback(&first.candidate, &policy)?,
            &independent_evidence(&first.candidate, &policy),
        ),
        Err(NduFbsdeIndependentEvidenceErrorV2::ShadowGateMismatch)
    );
    Ok(())
}

#[test]
fn independent_acceptance_rejects_a_shadow_bound_to_another_reference()
-> Result<(), Box<dyn StdError>> {
    let first = acceptance_fixture("immutable-locator-a")?;
    let second = acceptance_fixture("immutable-locator-b")?;
    assert_ne!(
        first.reference.receipt_digest(),
        second.reference.receipt_digest()
    );
    assert_same_chain(&first)?;
    let policy = rollback_policy(/*maximum_holdout_rmse_q24*/ 100)?;
    let wrong_shadow = shadow(
        first.candidate.candidate_digest(),
        second.reference.receipt_digest(),
    )?;
    assert_eq!(
        seal_fbsde_independent_acceptance_v2(
            &first.candidate,
            &first.reference,
            &first.publication,
            &wrong_shadow,
            &rollback(&first.candidate, &policy)?,
            &independent_evidence(&first.candidate, &policy),
        ),
        Err(NduFbsdeIndependentEvidenceErrorV2::ShadowGateMismatch)
    );
    Ok(())
}

#[test]
fn independent_acceptance_rejects_a_different_rollback_policy() -> Result<(), Box<dyn StdError>> {
    let fixture = acceptance_fixture("immutable-locator-a")?;
    assert_same_chain(&fixture)?;
    let first = rollback_policy(/*maximum_holdout_rmse_q24*/ 100)?;
    let second = rollback_policy(/*maximum_holdout_rmse_q24*/ 101)?;
    assert_ne!(first.policy_digest, second.policy_digest);
    let evidence = independent_evidence(&fixture.candidate, &first);
    let first_rollback = rollback(&fixture.candidate, &first)?;
    let second_rollback = rollback(&fixture.candidate, &second)?;
    assert!(!first_rollback.triggered());
    assert!(!second_rollback.triggered());
    let shadow = shadow(
        fixture.candidate.candidate_digest(),
        fixture.reference.receipt_digest(),
    )?;
    assert_eq!(
        seal_fbsde_independent_acceptance_v2(
            &fixture.candidate,
            &fixture.reference,
            &fixture.publication,
            &shadow,
            &second_rollback,
            &evidence,
        ),
        Err(NduFbsdeIndependentEvidenceErrorV2::ReferenceMismatch)
    );
    Ok(())
}
