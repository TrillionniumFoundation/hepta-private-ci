use super::*;

pub(super) fn canonical_dataset_digest(snapshot: &NduFbsdeDatasetSnapshotV1) -> Digest32 {
    let mut payload = b"hepta.ndu.fbsde.dataset-snapshot.v1\0".to_vec();
    for digest in [
        snapshot.immutable_locator_digest,
        snapshot.provenance_digest,
        snapshot.objective_class_digest,
        snapshot.feature_schema_digest,
        snapshot.increment_schema_digest,
        snapshot.outcome_schema_digest,
        snapshot.filtration_digest,
        snapshot.normalization_digest,
        snapshot.fold_assignment_digest,
        snapshot.trusted_time_digest,
    ] {
        payload.extend_from_slice(digest.as_array());
    }
    payload.extend_from_slice(&snapshot.snapshot_unix_ms.to_be_bytes());
    append_usize(&mut payload, snapshot.feature_dimension);
    append_usize(&mut payload, snapshot.driver_dimension);
    append_usize(&mut payload, snapshot.utility_dimension);
    append_usize(&mut payload, snapshot.horizon);
    let mut indices: Vec<usize> = (0..snapshot.trajectories.len()).collect();
    indices.sort_by_key(|index| snapshot.trajectories[*index].trajectory_digest);
    append_usize(&mut payload, indices.len());
    for index in indices {
        let trajectory = &snapshot.trajectories[index];
        for digest in [
            trajectory.trajectory_digest,
            trajectory.episode_digest,
            trajectory.principal_scope_digest,
        ] {
            payload.extend_from_slice(digest.as_array());
        }
        payload.push(match trajectory.fold {
            NduFbsdeFoldV1::Train => 0,
            NduFbsdeFoldV1::Holdout => 1,
        });
        append_usize(&mut payload, trajectory.steps.len());
        for step in &trajectory.steps {
            payload.extend_from_slice(&step.sequence.to_be_bytes());
            for value in [
                step.start_unix_ms,
                step.end_unix_ms,
                step.feature_observed_unix_ms,
                step.increment_observed_unix_ms,
                step.running_utility_observed_unix_ms,
            ] {
                payload.extend_from_slice(&value.to_be_bytes());
            }
            for digest in [
                step.conditioning_digest,
                step.feature_provenance_digest,
                step.increment_provenance_digest,
                step.running_utility_provenance_digest,
            ] {
                payload.extend_from_slice(digest.as_array());
            }
            append_i64_slice(&mut payload, &step.features_q24);
            append_i64_slice(&mut payload, &step.increment_q24);
            append_i64_slice(&mut payload, &step.running_utility_q24);
        }
        append_i64_slice(&mut payload, &trajectory.terminal_utility_q24);
        payload.extend_from_slice(trajectory.terminal_outcome_digest.as_array());
        payload.extend_from_slice(trajectory.terminal_provenance_digest.as_array());
        payload.extend_from_slice(&trajectory.terminal_observed_unix_ms.to_be_bytes());
    }
    Digest32::of_bytes(&payload)
}

pub(super) fn canonical_policy_digest(specification: &NduFbsdeTrainingPolicyV1) -> Digest32 {
    let mut payload = b"hepta.ndu.fbsde.training-policy.v1\0".to_vec();
    for digest in [
        specification.dataset_digest,
        specification.objective_class_digest,
        specification.feature_schema_digest,
        specification.increment_schema_digest,
        specification.outcome_schema_digest,
        specification.filtration_digest,
        specification.normalization_digest,
        specification.runtime_tuple_digest,
        specification.units_digest,
    ] {
        payload.extend_from_slice(digest.as_array());
    }
    for value in [
        specification.feature_dimension,
        specification.driver_dimension,
        specification.utility_dimension,
        specification.horizon,
        specification.maximum_epochs,
    ] {
        append_usize(&mut payload, value);
    }
    for value in [
        specification.ridge_penalty,
        specification.convergence_tolerance,
        specification.maximum_absolute_input,
        specification.maximum_absolute_value,
        specification.maximum_step_seconds,
        specification.maximum_holdout_rmse,
        specification.maximum_calibration_error,
        specification.minimum_holdout_improvement,
    ] {
        payload.extend_from_slice(&canonical_f64_bits(value).to_be_bytes());
    }
    for value in specification
        .generator_y
        .iter()
        .chain(specification.generator_z.iter().flatten())
    {
        payload.extend_from_slice(&canonical_f64_bits(*value).to_be_bytes());
    }
    Digest32::of_bytes(&payload)
}

pub(super) fn time_slice_source_digest(
    snapshot: &NduFbsdeDatasetSnapshotV1,
    policy: &AdmittedNduFbsdeTrainingPolicyV1,
    train: &[usize],
    current: &[Vec<Vec<f64>>],
    time_index: usize,
    epoch: usize,
) -> Digest32 {
    let mut payload = b"hepta.ndu.fbsde.time-slice-source.v1\0".to_vec();
    payload.extend_from_slice(snapshot.dataset_digest.as_array());
    payload.extend_from_slice(policy.digest.as_array());
    append_usize(&mut payload, time_index);
    append_usize(&mut payload, epoch);
    for index in train {
        payload.extend_from_slice(snapshot.trajectories[*index].trajectory_digest.as_array());
        for value in &current[*index][time_index + 1] {
            payload.extend_from_slice(&canonical_f64_bits(*value).to_be_bytes());
        }
    }
    Digest32::of_bytes(&payload)
}

pub(super) fn encode_candidate_artifact(candidate: &NduFbsdeTrainingCandidateV1) -> Vec<u8> {
    let mut payload = b"hepta.ndu.fbsde.coefficient-artifact.v1\0".to_vec();
    for digest in [
        candidate.policy_digest,
        candidate.dataset_digest,
        candidate.objective_class_digest,
        candidate.feature_schema_digest,
        candidate.filtration_digest,
        candidate.normalization_digest,
        candidate.runtime_tuple_digest,
        candidate.units_digest,
        candidate.covariance_profile_digest,
    ] {
        payload.extend_from_slice(digest.as_array());
    }
    append_usize(&mut payload, candidate.feature_dimension);
    append_usize(&mut payload, candidate.driver_dimension);
    append_usize(&mut payload, candidate.utility_dimension);
    append_usize(&mut payload, candidate.time_slices.len());
    for slice in &candidate.time_slices {
        payload.extend_from_slice(slice.conditioning_digest.as_array());
        payload.extend_from_slice(&slice.duration_micros.to_be_bytes());
        append_i64_slice(&mut payload, &slice.value_intercepts_q24);
        append_i64_matrix(&mut payload, &slice.value_weights_q24);
        append_i64_slice(&mut payload, &slice.baseline_intercepts_q24);
        append_i64_matrix(&mut payload, &slice.z_q24);
        for value in [
            slice.condition_estimate,
            slice.increment_eigenvalue_lower_estimate,
            slice.maximum_relative_residual,
        ] {
            payload.extend_from_slice(&canonical_f64_bits(value).to_be_bytes());
        }
        payload.extend_from_slice(slice.source_evidence_digest.as_array());
    }
    append_metrics(&mut payload, &candidate.metrics);
    payload
}

pub(super) fn candidate_receipt_digest(candidate: &NduFbsdeTrainingCandidateV1) -> Digest32 {
    let mut payload = b"hepta.ndu.fbsde.training-candidate.v1\0".to_vec();
    for digest in [
        candidate.policy_digest,
        candidate.dataset_digest,
        candidate.artifact_bytes_digest,
        candidate.covariance_profile_digest,
    ] {
        payload.extend_from_slice(digest.as_array());
    }
    append_metrics(&mut payload, &candidate.metrics);
    Digest32::of_bytes(&payload)
}

pub(super) fn primary_projection_source_digest(
    candidate: &NduFbsdeTrainingCandidateV1,
    first: &NduFbsdeTimeSliceV1,
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ndu.fbsde.primary-z-source.v1\0",
        candidate.candidate_digest.as_array(),
        candidate.artifact_bytes_digest.as_array(),
        first.source_evidence_digest.as_array(),
    ])
}

pub(super) fn canonical_shadow_evidence_digest(evidence: &NduFbsdeShadowEvidenceV1) -> Digest32 {
    let mut payload = b"hepta.ndu.fbsde.shadow-evidence.v1\0".to_vec();
    for digest in [
        evidence.candidate_digest,
        evidence.reference_receipt_digest,
        evidence.convergence_acceptance_digest,
        evidence.calibration_acceptance_digest,
        evidence.utility_improvement_acceptance_digest,
        evidence.regression_acceptance_digest,
        evidence.target_host_receipt_digest,
    ] {
        payload.extend_from_slice(digest.as_array());
    }
    for value in [
        evidence.observed_episode_count,
        evidence.observed_decision_count,
        evidence.observed_failure_count,
        evidence.window_start_unix_ms,
        evidence.window_end_unix_ms,
    ] {
        payload.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&payload)
}

pub(super) fn append_metrics(payload: &mut Vec<u8>, metrics: &NduFbsdeMetricsV1) {
    for value in [
        metrics.train_rmse_q24,
        metrics.holdout_rmse_q24,
        metrics.holdout_calibration_q24,
        metrics.holdout_improvement_q24,
        metrics.maximum_residual_q24,
        metrics.maximum_update_q24,
    ] {
        payload.extend_from_slice(&value.to_be_bytes());
    }
    payload.extend_from_slice(&metrics.train_observation_count.to_be_bytes());
    payload.extend_from_slice(&metrics.holdout_observation_count.to_be_bytes());
    payload.extend_from_slice(&metrics.epochs.to_be_bytes());
}

pub(super) fn append_i64_matrix(payload: &mut Vec<u8>, values: &[Vec<i64>]) {
    append_usize(payload, values.len());
    for row in values {
        append_i64_slice(payload, row);
    }
}

pub(super) fn append_i64_slice(payload: &mut Vec<u8>, values: &[i64]) {
    append_usize(payload, values.len());
    for value in values {
        payload.extend_from_slice(&value.to_be_bytes());
    }
}

pub(super) fn append_usize(payload: &mut Vec<u8>, value: usize) {
    payload.extend_from_slice(&(value as u64).to_be_bytes());
}

pub(super) fn q24_to_f64(value: i64) -> f64 {
    value as f64 / Q24_SCALE
}

pub(super) fn f64_to_q24(
    value: f64,
    maximum_absolute: f64,
) -> Result<i64, NduFbsdeTrainingError> {
    if !value.is_finite() || value.abs() > maximum_absolute {
        return Err(NduFbsdeTrainingError::InputBound);
    }
    let scaled = value * Q24_SCALE;
    if !scaled.is_finite() || scaled.abs() > (1_u64 << 53) as f64 {
        return Err(NduFbsdeTrainingError::Arithmetic);
    }
    Ok(round_ties_even(scaled) as i64)
}

pub(super) fn metric_to_q24(value: f64) -> Result<i64, NduFbsdeTrainingError> {
    if !value.is_finite() || value < 0.0 {
        return Err(NduFbsdeTrainingError::Arithmetic);
    }
    f64_to_q24(value, 1e9)
}

pub(super) fn signed_metric_to_q24(value: f64) -> Result<i64, NduFbsdeTrainingError> {
    f64_to_q24(value, 1e9)
}

pub(super) fn round_ties_even(value: f64) -> f64 {
    let floor = value.floor();
    let fraction = value - floor;
    if fraction < 0.5 {
        floor
    } else if fraction > 0.5 {
        floor + 1.0
    } else if floor % 2.0 == 0.0 {
        floor
    } else {
        floor + 1.0
    }
}

pub(super) fn clamp_finite(
    value: f64,
    maximum_absolute: f64,
) -> Result<f64, NduFbsdeTrainingError> {
    finite(value).map(|finite_value| {
        canonical_zero(finite_value.clamp(-maximum_absolute, maximum_absolute))
    })
}

pub(super) fn finite(value: f64) -> Result<f64, NduFbsdeTrainingError> {
    if value.is_finite() {
        Ok(canonical_zero(value))
    } else {
        Err(NduFbsdeTrainingError::NonFinite)
    }
}

pub(super) fn canonical_zero(value: f64) -> f64 {
    if value == 0.0 { 0.0 } else { value }
}

pub(super) fn canonical_f64_bits(value: f64) -> u64 {
    canonical_zero(value).to_bits()
}

pub(super) fn require_digest(
    digest: Digest32,
    field: &'static str,
) -> Result<(), NduFbsdeTrainingError> {
    if digest.is_zero() {
        Err(NduFbsdeTrainingError::MissingDigest(field))
    } else {
        Ok(())
    }
}

pub(super) fn map_covariance(_error: CovarianceError) -> NduFbsdeTrainingError {
    NduFbsdeTrainingError::Covariance
}

pub(super) fn map_coefficient_profile(error: NduCoefficientProfileError) -> NduFbsdeTrainingError {
    match error {
        NduCoefficientProfileError::Expiry => NduFbsdeTrainingError::Expired,
        NduCoefficientProfileError::Authority => NduFbsdeTrainingError::Authority,
        NduCoefficientProfileError::MissingDigest => {
            NduFbsdeTrainingError::MissingDigest("coefficient_profile")
        }
        NduCoefficientProfileError::ProfileMismatch | NduCoefficientProfileError::Dimension => {
            NduFbsdeTrainingError::ProfileMismatch
        }
    }
}
