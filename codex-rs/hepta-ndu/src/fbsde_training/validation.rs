use super::*;

pub(super) fn validate_dataset(
    snapshot: &NduFbsdeDatasetSnapshotV1,
) -> Result<(), NduFbsdeTrainingError> {
    if snapshot.dataset_digest.is_zero() {
        return Err(NduFbsdeTrainingError::MissingDigest("dataset"));
    }
    validate_dataset_shape(snapshot)?;
    if canonical_dataset_digest(snapshot) != snapshot.dataset_digest {
        return Err(NduFbsdeTrainingError::DatasetDigestMismatch);
    }
    Ok(())
}

pub(super) fn validate_dataset_shape(
    snapshot: &NduFbsdeDatasetSnapshotV1,
) -> Result<(), NduFbsdeTrainingError> {
    for (field, digest) in [
        ("immutable_locator", snapshot.immutable_locator_digest),
        ("provenance", snapshot.provenance_digest),
        ("objective_class", snapshot.objective_class_digest),
        ("feature_schema", snapshot.feature_schema_digest),
        ("increment_schema", snapshot.increment_schema_digest),
        ("outcome_schema", snapshot.outcome_schema_digest),
        ("filtration", snapshot.filtration_digest),
        ("normalization", snapshot.normalization_digest),
        ("fold_assignment", snapshot.fold_assignment_digest),
        ("trusted_time", snapshot.trusted_time_digest),
    ] {
        require_digest(digest, field)?;
    }
    if snapshot.snapshot_unix_ms == 0 {
        return Err(NduFbsdeTrainingError::Time);
    }
    if !(1..=MAX_FEATURES).contains(&snapshot.feature_dimension)
        || !(1..=MAX_DRIVERS).contains(&snapshot.driver_dimension)
        || !(1..=MAX_UTILITIES).contains(&snapshot.utility_dimension)
    {
        return Err(NduFbsdeTrainingError::InvalidDimension);
    }
    if !(1..=MAX_HORIZON).contains(&snapshot.horizon) {
        return Err(NduFbsdeTrainingError::InvalidHorizon);
    }
    if !(MIN_TRAIN_TRAJECTORIES + MIN_HOLDOUT_TRAJECTORIES..=MAX_TRAJECTORIES)
        .contains(&snapshot.trajectories.len())
    {
        return Err(NduFbsdeTrainingError::InvalidFold);
    }

    let mut seen_trajectories = BTreeSet::new();
    let mut seen_episodes = BTreeSet::new();
    let mut train_count = 0_usize;
    let mut holdout_count = 0_usize;
    let mut conditioning = vec![None; snapshot.horizon];
    let mut durations = vec![None; snapshot.horizon];
    for trajectory in &snapshot.trajectories {
        for (field, digest) in [
            ("trajectory", trajectory.trajectory_digest),
            ("episode", trajectory.episode_digest),
            ("principal_scope", trajectory.principal_scope_digest),
            ("terminal_outcome", trajectory.terminal_outcome_digest),
            ("terminal_provenance", trajectory.terminal_provenance_digest),
        ] {
            require_digest(digest, field)?;
        }
        if !seen_trajectories.insert(trajectory.trajectory_digest)
            || !seen_episodes.insert(trajectory.episode_digest)
        {
            return Err(NduFbsdeTrainingError::DuplicateTrajectory);
        }
        match trajectory.fold {
            NduFbsdeFoldV1::Train => train_count += 1,
            NduFbsdeFoldV1::Holdout => holdout_count += 1,
        }
        if trajectory.steps.len() != snapshot.horizon
            || trajectory.terminal_utility_q24.len() != snapshot.utility_dimension
        {
            return Err(NduFbsdeTrainingError::InvalidDimension);
        }
        let mut previous_end = 0_u64;
        for (index, step) in trajectory.steps.iter().enumerate() {
            if step.sequence
                != u32::try_from(index + 1).map_err(|_| NduFbsdeTrainingError::Sequence)?
            {
                return Err(NduFbsdeTrainingError::Sequence);
            }
            if step.start_unix_ms == 0
                || step.start_unix_ms >= step.end_unix_ms
                || (index > 0 && step.start_unix_ms < previous_end)
            {
                return Err(NduFbsdeTrainingError::Time);
            }
            if step.feature_observed_unix_ms > step.start_unix_ms {
                return Err(NduFbsdeTrainingError::FutureFeature);
            }
            if step.increment_observed_unix_ms < step.end_unix_ms
                || step.running_utility_observed_unix_ms < step.end_unix_ms
            {
                return Err(NduFbsdeTrainingError::Time);
            }
            if step.feature_observed_unix_ms > snapshot.snapshot_unix_ms
                || step.increment_observed_unix_ms > snapshot.snapshot_unix_ms
                || step.running_utility_observed_unix_ms > snapshot.snapshot_unix_ms
                || step.end_unix_ms > snapshot.snapshot_unix_ms
            {
                return Err(NduFbsdeTrainingError::ObservationAfterSnapshot);
            }
            for (field, digest) in [
                ("conditioning", step.conditioning_digest),
                ("feature_provenance", step.feature_provenance_digest),
                ("increment_provenance", step.increment_provenance_digest),
                (
                    "running_utility_provenance",
                    step.running_utility_provenance_digest,
                ),
            ] {
                require_digest(digest, field)?;
            }
            if step.features_q24.len() != snapshot.feature_dimension
                || step.increment_q24.len() != snapshot.driver_dimension
                || step.running_utility_q24.len() != snapshot.utility_dimension
            {
                return Err(NduFbsdeTrainingError::InvalidDimension);
            }
            let duration = duration_micros(step)?;
            match conditioning[index] {
                Some(value) if value != step.conditioning_digest => {
                    return Err(NduFbsdeTrainingError::ConditioningMismatch);
                }
                None => conditioning[index] = Some(step.conditioning_digest),
                _ => {}
            }
            match durations[index] {
                Some(value) if value != duration => {
                    return Err(NduFbsdeTrainingError::DurationMismatch);
                }
                None => durations[index] = Some(duration),
                _ => {}
            }
            previous_end = step.end_unix_ms;
        }
        if trajectory.terminal_observed_unix_ms < previous_end
            || trajectory.terminal_observed_unix_ms > snapshot.snapshot_unix_ms
        {
            return Err(NduFbsdeTrainingError::ObservationAfterSnapshot);
        }
    }
    if train_count < MIN_TRAIN_TRAJECTORIES || holdout_count < MIN_HOLDOUT_TRAJECTORIES {
        return Err(NduFbsdeTrainingError::InvalidFold);
    }
    Ok(())
}

pub(super) fn validate_policy(
    specification: &NduFbsdeTrainingPolicyV1,
) -> Result<(), NduFbsdeTrainingError> {
    for (field, digest) in [
        ("dataset", specification.dataset_digest),
        ("objective_class", specification.objective_class_digest),
        ("feature_schema", specification.feature_schema_digest),
        ("increment_schema", specification.increment_schema_digest),
        ("outcome_schema", specification.outcome_schema_digest),
        ("filtration", specification.filtration_digest),
        ("normalization", specification.normalization_digest),
        ("runtime_tuple", specification.runtime_tuple_digest),
        ("units", specification.units_digest),
    ] {
        require_digest(digest, field)?;
    }
    if !(1..=MAX_FEATURES).contains(&specification.feature_dimension)
        || !(1..=MAX_DRIVERS).contains(&specification.driver_dimension)
        || !(1..=MAX_UTILITIES).contains(&specification.utility_dimension)
    {
        return Err(NduFbsdeTrainingError::InvalidDimension);
    }
    if !(1..=MAX_HORIZON).contains(&specification.horizon)
        || !(2..=MAX_EPOCHS).contains(&specification.maximum_epochs)
    {
        return Err(NduFbsdeTrainingError::InvalidHorizon);
    }
    let numeric = [
        specification.ridge_penalty,
        specification.convergence_tolerance,
        specification.maximum_absolute_input,
        specification.maximum_absolute_value,
        specification.maximum_step_seconds,
        specification.maximum_holdout_rmse,
        specification.maximum_calibration_error,
        specification.minimum_holdout_improvement,
    ];
    if numeric.iter().any(|value| !value.is_finite())
        || !(1e-12..=1e6).contains(&specification.ridge_penalty)
        || !(1e-12..=1.0).contains(&specification.convergence_tolerance)
        || !(1e-9..=1e9).contains(&specification.maximum_absolute_input)
        || !(1e-9..=1e9).contains(&specification.maximum_absolute_value)
        || !(0.001..=3600.0).contains(&specification.maximum_step_seconds)
        || specification.maximum_holdout_rmse <= 0.0
        || specification.maximum_calibration_error <= 0.0
        || specification.minimum_holdout_improvement < 0.0
        || specification.generator_y.len() != specification.utility_dimension
        || specification.generator_z.len() != specification.utility_dimension
        || specification
            .generator_z
            .iter()
            .any(|row| row.len() != specification.driver_dimension)
    {
        return Err(NduFbsdeTrainingError::InvalidPolicy);
    }
    if specification
        .generator_y
        .iter()
        .chain(specification.generator_z.iter().flatten())
        .any(|value| !value.is_finite() || value.abs() > 1e6)
    {
        return Err(NduFbsdeTrainingError::InvalidPolicy);
    }
    let contraction = specification
        .generator_y
        .iter()
        .map(|value| value.abs() * specification.maximum_step_seconds)
        .fold(0.0, f64::max);
    if contraction >= 0.95 {
        return Err(NduFbsdeTrainingError::InvalidPolicy);
    }
    Ok(())
}

pub(super) fn validate_policy_binding(
    snapshot: &NduFbsdeDatasetSnapshotV1,
    policy: &AdmittedNduFbsdeTrainingPolicyV1,
    covariance_profile: &AdmittedCovarianceProfileV1,
) -> Result<(), NduFbsdeTrainingError> {
    let specification = &policy.specification;
    for (field, expected, actual) in [
        ("dataset", specification.dataset_digest, snapshot.dataset_digest),
        (
            "objective_class",
            specification.objective_class_digest,
            snapshot.objective_class_digest,
        ),
        (
            "feature_schema",
            specification.feature_schema_digest,
            snapshot.feature_schema_digest,
        ),
        (
            "increment_schema",
            specification.increment_schema_digest,
            snapshot.increment_schema_digest,
        ),
        (
            "outcome_schema",
            specification.outcome_schema_digest,
            snapshot.outcome_schema_digest,
        ),
        (
            "filtration",
            specification.filtration_digest,
            snapshot.filtration_digest,
        ),
        (
            "normalization",
            specification.normalization_digest,
            snapshot.normalization_digest,
        ),
    ] {
        if expected != actual {
            return Err(NduFbsdeTrainingError::PolicyMismatch(field));
        }
    }
    if specification.feature_dimension != snapshot.feature_dimension
        || specification.driver_dimension != snapshot.driver_dimension
        || specification.utility_dimension != snapshot.utility_dimension
        || specification.horizon != snapshot.horizon
        || covariance_profile.specification.driver_dimension != snapshot.driver_dimension
        || covariance_profile.specification.utility_dimension != snapshot.utility_dimension
        || covariance_profile.specification.units_digest != specification.units_digest
    {
        return Err(NduFbsdeTrainingError::InvalidDimension);
    }
    for trajectory in &snapshot.trajectories {
        for step in &trajectory.steps {
            let duration = duration_seconds(step)?;
            if duration > specification.maximum_step_seconds {
                return Err(NduFbsdeTrainingError::Time);
            }
            for raw in step
                .features_q24
                .iter()
                .chain(&step.increment_q24)
                .chain(&step.running_utility_q24)
            {
                if q24_to_f64(*raw).abs() > specification.maximum_absolute_input {
                    return Err(NduFbsdeTrainingError::InputBound);
                }
            }
        }
        for raw in &trajectory.terminal_utility_q24 {
            if q24_to_f64(*raw).abs() > specification.maximum_absolute_value {
                return Err(NduFbsdeTrainingError::InputBound);
            }
        }
    }
    Ok(())
}

pub(super) fn validate_candidate_identity(
    snapshot: &NduFbsdeDatasetSnapshotV1,
    policy: &AdmittedNduFbsdeTrainingPolicyV1,
    candidate: &NduFbsdeTrainingCandidateV1,
) -> Result<(), NduFbsdeTrainingError> {
    if candidate.authority.grants_any() {
        return Err(NduFbsdeTrainingError::Authority);
    }
    if candidate.policy_digest != policy.digest
        || candidate.dataset_digest != snapshot.dataset_digest
        || candidate.objective_class_digest != snapshot.objective_class_digest
        || candidate.feature_schema_digest != snapshot.feature_schema_digest
        || candidate.filtration_digest != snapshot.filtration_digest
        || candidate.normalization_digest != snapshot.normalization_digest
        || candidate.feature_dimension != snapshot.feature_dimension
        || candidate.driver_dimension != snapshot.driver_dimension
        || candidate.utility_dimension != snapshot.utility_dimension
        || candidate.time_slices.len() != snapshot.horizon
        || candidate.candidate_digest != candidate_receipt_digest(candidate)
    {
        return Err(NduFbsdeTrainingError::CandidateMismatch);
    }
    Ok(())
}

pub(super) fn ordered_trajectory_indices(
    snapshot: &NduFbsdeDatasetSnapshotV1,
) -> Result<Vec<usize>, NduFbsdeTrainingError> {
    let mut indices: Vec<usize> = (0..snapshot.trajectories.len()).collect();
    indices.sort_by_key(|index| snapshot.trajectories[*index].trajectory_digest);
    for pair in indices.windows(2) {
        if snapshot.trajectories[pair[0]].trajectory_digest
            == snapshot.trajectories[pair[1]].trajectory_digest
        {
            return Err(NduFbsdeTrainingError::DuplicateTrajectory);
        }
    }
    Ok(indices)
}

pub(super) fn duration_micros(step: &NduFbsdeStepV1) -> Result<u64, NduFbsdeTrainingError> {
    step.end_unix_ms
        .checked_sub(step.start_unix_ms)
        .and_then(|milliseconds| milliseconds.checked_mul(1000))
        .filter(|value| *value > 0)
        .ok_or(NduFbsdeTrainingError::Time)
}

pub(super) fn duration_seconds(step: &NduFbsdeStepV1) -> Result<f64, NduFbsdeTrainingError> {
    finite(duration_micros(step)? as f64 / 1_000_000.0)
}
