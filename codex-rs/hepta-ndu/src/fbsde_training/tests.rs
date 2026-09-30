use super::*;
use crate::CovarianceConventionV1;
use crate::NduCoefficientProfileV1;
use crate::NduCovarianceProfileV1;
use crate::NduZConversionProfileV1;
use crate::ZCoordinateConventionV1;
use crate::admit_covariance_profile;
use crate::admit_ndu_coefficient_profile;
use crate::admit_z_conversion_profile;

fn digest(label: &str) -> Digest32 {
    Digest32::of_bytes(label.as_bytes())
}

fn q24(value: f64) -> i64 {
    round_ties_even(value * Q24_SCALE) as i64
}

fn fixture_snapshot() -> Result<NduFbsdeDatasetSnapshotV1, NduFbsdeTrainingError> {
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
            running_utility_provenance_digest: digest(&format!(
                "running-{index}-{sequence}"
            )),
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
            terminal_utility_q24: vec![q24(1.5 * feature + 0.25 * increment)],
            terminal_outcome_digest: digest(&format!("outcome-{index}")),
            terminal_provenance_digest: digest(&format!("terminal-{index}")),
            terminal_observed_unix_ms: base + 4_000,
        });
    }
    seal_ndu_fbsde_dataset_v1(NduFbsdeDatasetSnapshotV1 {
        dataset_digest: Digest32::ZERO,
        immutable_locator_digest: digest("immutable-locator"),
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

#[test]
fn immutable_dataset_rejects_future_features_and_cross_fold_reuse()
-> Result<(), Box<dyn StdError>> {
    let snapshot = fixture_snapshot()?;
    let mut leaked = snapshot.clone();
    leaked.dataset_digest = Digest32::ZERO;
    leaked.trajectories[0].steps[0].feature_observed_unix_ms =
        leaked.trajectories[0].steps[0].start_unix_ms + 1;
    assert_eq!(
        seal_ndu_fbsde_dataset_v1(leaked),
        Err(NduFbsdeTrainingError::FutureFeature)
    );

    let mut duplicate = snapshot.clone();
    duplicate.dataset_digest = Digest32::ZERO;
    duplicate.trajectories[8].episode_digest = duplicate.trajectories[0].episode_digest;
    duplicate.trajectories[8].fold = NduFbsdeFoldV1::Holdout;
    assert_eq!(
        seal_ndu_fbsde_dataset_v1(duplicate),
        Err(NduFbsdeTrainingError::DuplicateTrajectory)
    );
    Ok(())
}

#[test]
fn bounded_fbsde_training_is_deterministic_and_reference_replay_matches()
-> Result<(), Box<dyn StdError>> {
    let snapshot = fixture_snapshot()?;
    let (policy, covariance, _) = profiles(&snapshot)?;
    let first = train_discrete_ndu_fbsde_v1(&snapshot, &policy, &covariance)?;
    let second = train_discrete_ndu_fbsde_v1(&snapshot, &policy, &covariance)?;
    assert_eq!(first.candidate_digest(), second.candidate_digest());
    assert_eq!(first.artifact_bytes(), second.artifact_bytes());
    assert!(!first.authority().grants_any());
    assert!(first.metrics().holdout_improvement_q24() > 0);

    let reference = reference_evaluate_ndu_fbsde_v1(&snapshot, &policy, &first)?;
    assert_eq!(reference.candidate_digest(), first.candidate_digest());
    assert_eq!(
        reference.artifact_bytes_digest(),
        first.artifact_bytes_digest()
    );
    Ok(())
}

#[test]
fn reference_replay_rejects_metric_substitution() -> Result<(), Box<dyn StdError>> {
    let snapshot = fixture_snapshot()?;
    let (policy, covariance, _) = profiles(&snapshot)?;
    let mut candidate = train_discrete_ndu_fbsde_v1(&snapshot, &policy, &covariance)?;
    candidate.metrics.holdout_rmse_q24 += 1;
    assert_eq!(
        reference_evaluate_ndu_fbsde_v1(&snapshot, &policy, &candidate),
        Err(NduFbsdeTrainingError::CandidateMismatch)
    );
    Ok(())
}

#[test]
fn publication_binds_registered_bytes_and_existing_stochastic_projection()
-> Result<(), Box<dyn StdError>> {
    let snapshot = fixture_snapshot()?;
    let (policy, covariance, z) = profiles(&snapshot)?;
    let candidate = train_discrete_ndu_fbsde_v1(&snapshot, &policy, &covariance)?;
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
    assert_eq!(
        bind_ndu_fbsde_publication_v1(
            &candidate,
            digest("wrong-bytes"),
            &coefficient,
            &z,
            1_700_000_300_000,
        ),
        Err(NduFbsdeTrainingError::ArtifactMismatch)
    );

    let (binding, projection) = bind_ndu_fbsde_publication_v1(
        &candidate,
        candidate.artifact_bytes_digest(),
        &coefficient,
        &z,
        1_700_000_300_000,
    )?;
    assert_eq!(
        binding.artifact_bytes_digest(),
        candidate.artifact_bytes_digest()
    );
    assert_eq!(
        binding.artifact_manifest_digest(),
        coefficient.artifact_manifest_digest()
    );
    assert!(!binding.authority().grants_any());
    assert!(!projection.authority.grants_any());
    Ok(())
}

#[test]
fn shadow_gate_never_activates_and_requires_independent_evidence()
-> Result<(), Box<dyn StdError>> {
    let policy = NduFbsdeShadowPolicyV1 {
        policy_digest: digest("shadow-policy"),
        minimum_advisory_episodes: 100,
        minimum_advisory_decisions: 1_000,
        minimum_restricted_episodes: 1_000,
        minimum_restricted_decisions: 10_000,
        maximum_failures: 0,
    };
    let mut evidence = NduFbsdeShadowEvidenceV1 {
        candidate_digest: digest("candidate"),
        reference_receipt_digest: digest("reference"),
        convergence_acceptance_digest: Digest32::ZERO,
        calibration_acceptance_digest: Digest32::ZERO,
        utility_improvement_acceptance_digest: Digest32::ZERO,
        regression_acceptance_digest: Digest32::ZERO,
        target_host_receipt_digest: Digest32::ZERO,
        observed_episode_count: 2_000,
        observed_decision_count: 20_000,
        observed_failure_count: 0,
        window_start_unix_ms: 10,
        window_end_unix_ms: 20,
    };
    let shadow = evaluate_ndu_fbsde_shadow_gate_v1(&policy, &evidence)?;
    assert_eq!(shadow.stage(), NduFbsdeShadowStageV1::ShadowOnly);
    assert!(!shadow.production_activation());

    evidence.convergence_acceptance_digest = digest("convergence");
    evidence.calibration_acceptance_digest = digest("calibration");
    evidence.utility_improvement_acceptance_digest = digest("utility");
    evidence.regression_acceptance_digest = digest("regression");
    let advisory = evaluate_ndu_fbsde_shadow_gate_v1(&policy, &evidence)?;
    assert_eq!(
        advisory.stage(),
        NduFbsdeShadowStageV1::AdvisoryEligible
    );

    evidence.target_host_receipt_digest = digest("host");
    let restricted = evaluate_ndu_fbsde_shadow_gate_v1(&policy, &evidence)?;
    assert_eq!(
        restricted.stage(),
        NduFbsdeShadowStageV1::RestrictedWriteEligible
    );
    assert!(!restricted.authority().grants_any());
    assert!(!restricted.production_activation());
    Ok(())
}
