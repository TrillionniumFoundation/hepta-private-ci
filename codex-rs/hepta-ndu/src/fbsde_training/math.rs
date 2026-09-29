use super::*;

pub(super) fn design_row(step: &NduFbsdeStepV1) -> Vec<f64> {
    let mut row = Vec::with_capacity(step.features_q24.len() + 1);
    row.push(1.0);
    row.extend(step.features_q24.iter().map(|value| q24_to_f64(*value)));
    row
}

pub(super) fn fit_ridge(
    design: &[Vec<f64>],
    targets: &[Vec<f64>],
    ridge_penalty: f64,
) -> Result<(Vec<f64>, Vec<Vec<f64>>), NduFbsdeTrainingError> {
    if design.is_empty()
        || design.len() != targets.len()
        || targets.is_empty()
        || targets[0].is_empty()
    {
        return Err(NduFbsdeTrainingError::InvalidFold);
    }
    let width = design[0].len();
    let utilities = targets[0].len();
    if width == 0
        || design.iter().any(|row| row.len() != width)
        || targets.iter().any(|row| row.len() != utilities)
    {
        return Err(NduFbsdeTrainingError::InvalidDimension);
    }
    let mut gram = vec![vec![0.0; width]; width];
    let mut rhs = vec![vec![0.0; width]; utilities];
    for (features, target) in design.iter().zip(targets) {
        for (left, left_value) in features.iter().enumerate() {
            for (right, right_value) in features.iter().enumerate() {
                gram[left][right] += left_value * right_value;
            }
            for utility in 0..utilities {
                rhs[utility][left] += left_value * target[utility];
            }
        }
    }
    for (index, row) in gram.iter_mut().enumerate() {
        row[index] += ridge_penalty;
    }
    let factor = cholesky(&gram)?;
    let mut intercepts = Vec::with_capacity(utilities);
    let mut weights = Vec::with_capacity(utilities);
    for utility_rhs in rhs {
        let solution = solve_cholesky(&factor, utility_rhs)?;
        intercepts.push(solution[0]);
        weights.push(solution[1..].to_vec());
    }
    Ok((intercepts, weights))
}

pub(super) fn cholesky(matrix: &[Vec<f64>]) -> Result<Vec<Vec<f64>>, NduFbsdeTrainingError> {
    let dimension = matrix.len();
    if dimension == 0 || matrix.iter().any(|row| row.len() != dimension) {
        return Err(NduFbsdeTrainingError::InvalidDimension);
    }
    let mut factor = vec![vec![0.0; dimension]; dimension];
    for row in 0..dimension {
        for column in 0..=row {
            let inner: f64 = (0..column)
                .map(|index| factor[row][index] * factor[column][index])
                .sum();
            let remainder = matrix[row][column] - inner;
            if !remainder.is_finite() {
                return Err(NduFbsdeTrainingError::Arithmetic);
            }
            factor[row][column] = if row == column {
                if remainder <= 1e-18 {
                    return Err(NduFbsdeTrainingError::SingularRegression);
                }
                remainder.sqrt()
            } else {
                remainder / factor[column][column]
            };
        }
    }
    Ok(factor)
}

pub(super) fn solve_cholesky(
    factor: &[Vec<f64>],
    mut rhs: Vec<f64>,
) -> Result<Vec<f64>, NduFbsdeTrainingError> {
    for row in 0..rhs.len() {
        let inner: f64 = (0..row)
            .map(|column| factor[row][column] * rhs[column])
            .sum();
        rhs[row] = (rhs[row] - inner) / factor[row][row];
    }
    for row in (0..rhs.len()).rev() {
        let inner: f64 = (row + 1..rhs.len())
            .map(|column| factor[column][row] * rhs[column])
            .sum();
        rhs[row] = (rhs[row] - inner) / factor[row][row];
    }
    if rhs.iter().any(|value| !value.is_finite()) {
        return Err(NduFbsdeTrainingError::Arithmetic);
    }
    Ok(rhs)
}

pub(super) fn column_means(targets: &[Vec<f64>]) -> Result<Vec<f64>, NduFbsdeTrainingError> {
    if targets.is_empty() || targets[0].is_empty() {
        return Err(NduFbsdeTrainingError::InvalidFold);
    }
    let width = targets[0].len();
    let mut means = vec![0.0; width];
    for row in targets {
        if row.len() != width {
            return Err(NduFbsdeTrainingError::InvalidDimension);
        }
        for (mean, value) in means.iter_mut().zip(row) {
            *mean += *value;
        }
    }
    for mean in &mut means {
        *mean = finite(*mean / targets.len() as f64)?;
    }
    Ok(means)
}

pub(super) fn predict(
    intercept: f64,
    weights: &[f64],
    features_q24: &[i64],
) -> Result<f64, NduFbsdeTrainingError> {
    if weights.len() != features_q24.len() {
        return Err(NduFbsdeTrainingError::InvalidDimension);
    }
    let mut value = intercept;
    for (weight, feature) in weights.iter().zip(features_q24) {
        value += weight * q24_to_f64(*feature);
    }
    finite(value)
}

pub(super) fn dot(left: &[f64], right: &[f64]) -> Result<f64, NduFbsdeTrainingError> {
    if left.len() != right.len() {
        return Err(NduFbsdeTrainingError::InvalidDimension);
    }
    finite(left.iter().zip(right).map(|(a, b)| a * b).sum())
}

pub(super) fn dot_q24(
    left: &[f64],
    right_q24: &[i64],
) -> Result<f64, NduFbsdeTrainingError> {
    if left.len() != right_q24.len() {
        return Err(NduFbsdeTrainingError::InvalidDimension);
    }
    finite(
        left.iter()
            .zip(right_q24)
            .map(|(left_value, right_value)| left_value * q24_to_f64(*right_value))
            .sum(),
    )
}

pub(super) fn predict_q24(
    intercept_q24: i64,
    weights_q24: &[i64],
    features_q24: &[i64],
) -> Result<f64, NduFbsdeTrainingError> {
    if weights_q24.len() != features_q24.len() {
        return Err(NduFbsdeTrainingError::InvalidDimension);
    }
    let value = weights_q24.iter().zip(features_q24).fold(
        q24_to_f64(intercept_q24),
        |accumulator, (weight, feature)| {
            accumulator + q24_to_f64(*weight) * q24_to_f64(*feature)
        },
    );
    finite(value)
}

pub(super) fn quantize_slices(
    slices: &[FittedSlice],
    maximum_absolute_value: f64,
) -> Result<Vec<NduFbsdeTimeSliceV1>, NduFbsdeTrainingError> {
    slices
        .iter()
        .map(|slice| {
            let value_intercepts_q24 = slice
                .value_intercepts
                .iter()
                .map(|value| f64_to_q24(*value, maximum_absolute_value))
                .collect::<Result<Vec<_>, _>>()?;
            let value_weights_q24 = slice
                .value_weights
                .iter()
                .map(|row| {
                    row.iter()
                        .map(|value| f64_to_q24(*value, maximum_absolute_value))
                        .collect::<Result<Vec<_>, _>>()
                })
                .collect::<Result<Vec<_>, _>>()?;
            let baseline_intercepts_q24 = slice
                .baseline_intercepts
                .iter()
                .map(|value| f64_to_q24(*value, maximum_absolute_value))
                .collect::<Result<Vec<_>, _>>()?;
            let z_q24 = slice
                .z
                .iter()
                .map(|row| {
                    row.iter()
                        .map(|value| f64_to_q24(*value, maximum_absolute_value))
                        .collect::<Result<Vec<_>, _>>()
                })
                .collect::<Result<Vec<_>, _>>()?;
            Ok(NduFbsdeTimeSliceV1 {
                conditioning_digest: slice.conditioning_digest,
                duration_micros: slice.duration_micros,
                value_intercepts_q24,
                value_weights_q24,
                baseline_intercepts_q24,
                z_q24,
                condition_estimate: canonical_zero(slice.condition_estimate),
                increment_eigenvalue_lower_estimate: canonical_zero(
                    slice.increment_eigenvalue_lower_estimate,
                ),
                maximum_relative_residual: canonical_zero(slice.maximum_relative_residual),
                source_evidence_digest: slice.source_evidence_digest,
            })
        })
        .collect()
}

pub(super) fn candidate_without_metrics(
    snapshot: &NduFbsdeDatasetSnapshotV1,
    policy: &AdmittedNduFbsdeTrainingPolicyV1,
    covariance_profile: &AdmittedCovarianceProfileV1,
    time_slices: Vec<NduFbsdeTimeSliceV1>,
) -> NduFbsdeTrainingCandidateV1 {
    NduFbsdeTrainingCandidateV1 {
        policy_digest: policy.digest,
        dataset_digest: snapshot.dataset_digest,
        objective_class_digest: snapshot.objective_class_digest,
        feature_schema_digest: snapshot.feature_schema_digest,
        filtration_digest: snapshot.filtration_digest,
        normalization_digest: snapshot.normalization_digest,
        runtime_tuple_digest: policy.specification.runtime_tuple_digest,
        units_digest: policy.specification.units_digest,
        covariance_profile_digest: covariance_profile.digest,
        feature_dimension: snapshot.feature_dimension,
        driver_dimension: snapshot.driver_dimension,
        utility_dimension: snapshot.utility_dimension,
        time_slices,
        metrics: NduFbsdeMetricsV1 {
            train_rmse_q24: 0,
            holdout_rmse_q24: 0,
            holdout_calibration_q24: 0,
            holdout_improvement_q24: 0,
            maximum_residual_q24: 0,
            maximum_update_q24: 0,
            train_observation_count: 0,
            holdout_observation_count: 0,
            epochs: 0,
        },
        artifact_bytes_digest: Digest32::ZERO,
        candidate_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    }
}

pub(super) fn evaluate_candidate_metrics(
    snapshot: &NduFbsdeDatasetSnapshotV1,
    policy: &AdmittedNduFbsdeTrainingPolicyV1,
    candidate: &NduFbsdeTrainingCandidateV1,
    train: &[usize],
    holdout: &[usize],
    maximum_update: f64,
    epochs: u32,
) -> Result<NduFbsdeMetricsV1, NduFbsdeTrainingError> {
    let train_metrics = evaluate_fold(snapshot, policy, candidate, train)?;
    let holdout_metrics = evaluate_fold(snapshot, policy, candidate, holdout)?;
    metrics_from_accumulators(train_metrics, holdout_metrics, maximum_update, epochs)
}

pub(super) fn reference_metrics(
    snapshot: &NduFbsdeDatasetSnapshotV1,
    policy: &AdmittedNduFbsdeTrainingPolicyV1,
    candidate: &NduFbsdeTrainingCandidateV1,
    train: &[usize],
    holdout: &[usize],
) -> Result<NduFbsdeMetricsV1, NduFbsdeTrainingError> {
    let train_metrics = reference_fold(snapshot, policy, candidate, train)?;
    let holdout_metrics = reference_fold(snapshot, policy, candidate, holdout)?;
    let maximum_update = q24_to_f64(candidate.metrics.maximum_update_q24);
    metrics_from_accumulators(
        train_metrics,
        holdout_metrics,
        maximum_update,
        candidate.metrics.epochs,
    )
}

pub(super) fn evaluate_fold(
    snapshot: &NduFbsdeDatasetSnapshotV1,
    policy: &AdmittedNduFbsdeTrainingPolicyV1,
    candidate: &NduFbsdeTrainingCandidateV1,
    indices: &[usize],
) -> Result<MetricAccumulator, NduFbsdeTrainingError> {
    let predictions = predict_all(snapshot, candidate, indices)?;
    let mut accumulator = MetricAccumulator::default();
    for (position, index) in indices.iter().enumerate() {
        let trajectory = &snapshot.trajectories[*index];
        for time_index in 0..snapshot.horizon {
            let step = &trajectory.steps[time_index];
            let slice = &candidate.time_slices[time_index];
            let dt = duration_seconds(step)?;
            for utility in 0..snapshot.utility_dimension {
                let predicted = predictions[position][time_index][utility];
                let next = predictions[position][time_index + 1][utility];
                let generator = policy.specification.generator_y[utility] * predicted
                    + dot_q24(
                        &policy.specification.generator_z[utility],
                        &slice.z_q24[utility],
                    )?;
                let target = clamp_finite(
                    q24_to_f64(step.running_utility_q24[utility]) + next + dt * generator,
                    policy.specification.maximum_absolute_value,
                )?;
                let baseline = q24_to_f64(slice.baseline_intercepts_q24[utility]);
                accumulator.observe(predicted - target, baseline - target);
            }
        }
    }
    Ok(accumulator)
}

pub(super) fn reference_fold(
    snapshot: &NduFbsdeDatasetSnapshotV1,
    policy: &AdmittedNduFbsdeTrainingPolicyV1,
    candidate: &NduFbsdeTrainingCandidateV1,
    indices: &[usize],
) -> Result<MetricAccumulator, NduFbsdeTrainingError> {
    let mut accumulator = MetricAccumulator::default();
    for index in indices {
        let trajectory = &snapshot.trajectories[*index];
        let mut values = vec![vec![0.0; snapshot.utility_dimension]; snapshot.horizon + 1];
        values[snapshot.horizon] = trajectory
            .terminal_utility_q24
            .iter()
            .map(|value| q24_to_f64(*value))
            .collect();
        for time_index in (0..snapshot.horizon).rev() {
            let slice = &candidate.time_slices[time_index];
            for utility in 0..snapshot.utility_dimension {
                values[time_index][utility] = q24_to_f64(slice.value_intercepts_q24[utility]);
                for (weight, feature) in slice.value_weights_q24[utility]
                    .iter()
                    .zip(&trajectory.steps[time_index].features_q24)
                {
                    values[time_index][utility] += q24_to_f64(*weight) * q24_to_f64(*feature);
                }
                values[time_index][utility] = values[time_index][utility].clamp(
                    -policy.specification.maximum_absolute_value,
                    policy.specification.maximum_absolute_value,
                );
            }
        }
        for time_index in 0..snapshot.horizon {
            let step = &trajectory.steps[time_index];
            let slice = &candidate.time_slices[time_index];
            let dt = duration_seconds(step)?;
            for utility in 0..snapshot.utility_dimension {
                let mut z_generator = 0.0;
                for driver in 0..snapshot.driver_dimension {
                    z_generator += policy.specification.generator_z[utility][driver]
                        * q24_to_f64(slice.z_q24[utility][driver]);
                }
                let predicted = values[time_index][utility];
                let target = clamp_finite(
                    q24_to_f64(step.running_utility_q24[utility])
                        + values[time_index + 1][utility]
                        + dt
                            * (policy.specification.generator_y[utility] * predicted
                                + z_generator),
                    policy.specification.maximum_absolute_value,
                )?;
                let baseline = q24_to_f64(slice.baseline_intercepts_q24[utility]);
                accumulator.observe(predicted - target, baseline - target);
            }
        }
    }
    Ok(accumulator)
}

pub(super) fn predict_all(
    snapshot: &NduFbsdeDatasetSnapshotV1,
    candidate: &NduFbsdeTrainingCandidateV1,
    indices: &[usize],
) -> Result<Vec<Vec<Vec<f64>>>, NduFbsdeTrainingError> {
    let mut all = Vec::with_capacity(indices.len());
    for index in indices {
        let trajectory = &snapshot.trajectories[*index];
        let mut values = vec![vec![0.0; snapshot.utility_dimension]; snapshot.horizon + 1];
        values[snapshot.horizon] = trajectory
            .terminal_utility_q24
            .iter()
            .map(|value| q24_to_f64(*value))
            .collect();
        for time_index in (0..snapshot.horizon).rev() {
            let slice = &candidate.time_slices[time_index];
            for utility in 0..snapshot.utility_dimension {
                values[time_index][utility] = predict_q24(
                    slice.value_intercepts_q24[utility],
                    &slice.value_weights_q24[utility],
                    &trajectory.steps[time_index].features_q24,
                )?;
            }
        }
        all.push(values);
    }
    Ok(all)
}

pub(super) fn metrics_from_accumulators(
    train: MetricAccumulator,
    holdout: MetricAccumulator,
    maximum_update: f64,
    epochs: u32,
) -> Result<NduFbsdeMetricsV1, NduFbsdeTrainingError> {
    let train_rmse = train.rmse()?;
    let holdout_rmse = holdout.rmse()?;
    let holdout_calibration = holdout.calibration()?;
    let holdout_improvement = holdout.baseline_rmse()? - holdout_rmse;
    Ok(NduFbsdeMetricsV1 {
        train_rmse_q24: metric_to_q24(train_rmse)?,
        holdout_rmse_q24: metric_to_q24(holdout_rmse)?,
        holdout_calibration_q24: metric_to_q24(holdout_calibration)?,
        holdout_improvement_q24: signed_metric_to_q24(holdout_improvement)?,
        maximum_residual_q24: metric_to_q24(
            train
                .maximum_absolute_residual
                .max(holdout.maximum_absolute_residual),
        )?,
        maximum_update_q24: metric_to_q24(maximum_update)?,
        train_observation_count: train.count,
        holdout_observation_count: holdout.count,
        epochs,
    })
}

pub(super) fn enforce_candidate_thresholds(
    policy: &AdmittedNduFbsdeTrainingPolicyV1,
    metrics: &NduFbsdeMetricsV1,
) -> Result<(), NduFbsdeTrainingError> {
    if q24_to_f64(metrics.holdout_rmse_q24) > policy.specification.maximum_holdout_rmse {
        return Err(NduFbsdeTrainingError::HoldoutRmse);
    }
    if q24_to_f64(metrics.holdout_calibration_q24)
        > policy.specification.maximum_calibration_error
    {
        return Err(NduFbsdeTrainingError::Calibration);
    }
    if q24_to_f64(metrics.holdout_improvement_q24)
        < policy.specification.minimum_holdout_improvement
    {
        return Err(NduFbsdeTrainingError::UtilityImprovement);
    }
    Ok(())
}
