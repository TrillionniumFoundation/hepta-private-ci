use super::*;

/// Seals an immutable snapshot after validating its exact content and
/// train/holdout boundary. The caller must supply `Digest32::ZERO` in the
/// `dataset_digest` field; resealing is rejected.
pub fn seal_ndu_fbsde_dataset_v1(
    mut snapshot: NduFbsdeDatasetSnapshotV1,
) -> Result<NduFbsdeDatasetSnapshotV1, NduFbsdeTrainingError> {
    if !snapshot.dataset_digest.is_zero() {
        return Err(NduFbsdeTrainingError::AlreadySealed);
    }
    validate_dataset_shape(&snapshot)?;
    snapshot.dataset_digest = canonical_dataset_digest(&snapshot);
    Ok(snapshot)
}

/// Admits a bounded linear generator and regression policy. This validates the
/// numeric/search envelope; it is not a convergence or efficacy decision.
pub fn admit_ndu_fbsde_training_policy_v1(
    specification: NduFbsdeTrainingPolicyV1,
) -> Result<AdmittedNduFbsdeTrainingPolicyV1, NduFbsdeTrainingError> {
    validate_policy(&specification)?;
    let digest = canonical_policy_digest(&specification);
    Ok(AdmittedNduFbsdeTrainingPolicyV1 {
        specification,
        digest,
    })
}

/// Fits a complete bounded discrete-time linear FBSDE candidate. The fit uses
/// an explicit immutable train fold, preserves a separate holdout fold, solves
/// every Z head through the admitted covariance kernel, and emits canonical
/// Q24 artifact bytes. The result remains DENY_ALL.
pub fn train_discrete_ndu_fbsde_v1(
    snapshot: &NduFbsdeDatasetSnapshotV1,
    policy: &AdmittedNduFbsdeTrainingPolicyV1,
    covariance_profile: &AdmittedCovarianceProfileV1,
) -> Result<NduFbsdeTrainingCandidateV1, NduFbsdeTrainingError> {
    validate_dataset(snapshot)?;
    validate_policy_binding(snapshot, policy, covariance_profile)?;

    let ordered = ordered_trajectory_indices(snapshot)?;
    let train: Vec<usize> = ordered
        .iter()
        .copied()
        .filter(|index| snapshot.trajectories[*index].fold == NduFbsdeFoldV1::Train)
        .collect();
    let holdout: Vec<usize> = ordered
        .iter()
        .copied()
        .filter(|index| snapshot.trajectories[*index].fold == NduFbsdeFoldV1::Holdout)
        .collect();
    if train.len() < MIN_TRAIN_TRAJECTORIES || holdout.len() < MIN_HOLDOUT_TRAJECTORIES {
        return Err(NduFbsdeTrainingError::InvalidFold);
    }

    let trajectory_count = snapshot.trajectories.len();
    let horizon = snapshot.horizon;
    let utility_dimension = snapshot.utility_dimension;
    let mut previous =
        vec![vec![vec![0.0; utility_dimension]; horizon + 1]; trajectory_count];
    for (index, trajectory) in snapshot.trajectories.iter().enumerate() {
        previous[index][horizon] = trajectory
            .terminal_utility_q24
            .iter()
            .map(|value| q24_to_f64(*value))
            .collect();
    }

    let mut converged_slices = Vec::new();
    let mut maximum_update = f64::INFINITY;
    let mut epochs = 0_u32;
    for epoch in 0..policy.specification.maximum_epochs {
        let mut current =
            vec![vec![vec![0.0; utility_dimension]; horizon + 1]; trajectory_count];
        for (index, trajectory) in snapshot.trajectories.iter().enumerate() {
            current[index][horizon] = trajectory
                .terminal_utility_q24
                .iter()
                .map(|value| q24_to_f64(*value))
                .collect();
        }

        let mut reverse_slices = Vec::with_capacity(horizon);
        for time_index in (0..horizon).rev() {
            let source_digest = time_slice_source_digest(
                snapshot,
                policy,
                &train,
                &current,
                time_index,
                epoch,
            );
            let samples: Vec<ConditionalMomentSampleV1> = train
                .iter()
                .map(|index| {
                    let step = &snapshot.trajectories[*index].steps[time_index];
                    Ok(ConditionalMomentSampleV1 {
                        conditioning_digest: step.conditioning_digest,
                        duration_micros: duration_micros(step)?,
                        increment: step
                            .increment_q24
                            .iter()
                            .map(|value| q24_to_f64(*value))
                            .collect(),
                        utility: current[*index][time_index + 1].clone(),
                    })
                })
                .collect::<Result<_, NduFbsdeTrainingError>>()?;
            let moments = estimate_conditional_moments(
                &samples,
                source_digest,
                covariance_profile,
            )
            .map_err(map_covariance)?;
            let z_estimate =
                solve_backward_regression(&moments, covariance_profile).map_err(map_covariance)?;

            let mut design = Vec::with_capacity(train.len());
            let mut targets = Vec::with_capacity(train.len());
            for index in &train {
                let trajectory = &snapshot.trajectories[*index];
                let step = &trajectory.steps[time_index];
                design.push(design_row(step));
                let dt = duration_seconds(step)?;
                let mut row = Vec::with_capacity(utility_dimension);
                for utility in 0..utility_dimension {
                    let running = q24_to_f64(step.running_utility_q24[utility]);
                    let next = current[*index][time_index + 1][utility];
                    let old_current = previous[*index][time_index][utility];
                    let generator = policy.specification.generator_y[utility] * old_current
                        + dot(
                            &policy.specification.generator_z[utility],
                            &z_estimate.z[utility],
                        )?;
                    row.push(clamp_finite(
                        running + next + dt * generator,
                        policy.specification.maximum_absolute_value,
                    )?);
                }
                targets.push(row);
            }
            let (intercepts, weights) =
                fit_ridge(&design, &targets, policy.specification.ridge_penalty)?;
            let baseline_intercepts = column_means(&targets)?;

            for index in &ordered {
                let features = &snapshot.trajectories[*index].steps[time_index].features_q24;
                for utility in 0..utility_dimension {
                    current[*index][time_index][utility] = clamp_finite(
                        predict(intercepts[utility], &weights[utility], features)?,
                        policy.specification.maximum_absolute_value,
                    )?;
                }
            }

            reverse_slices.push(FittedSlice {
                conditioning_digest: samples[0].conditioning_digest,
                duration_micros: samples[0].duration_micros,
                value_intercepts: intercepts,
                value_weights: weights,
                baseline_intercepts,
                z: z_estimate.z,
                condition_estimate: z_estimate.condition_estimate,
                increment_eigenvalue_lower_estimate:
                    z_estimate.increment_eigenvalue_lower_estimate,
                maximum_relative_residual: z_estimate.maximum_relative_residual,
                source_evidence_digest: z_estimate.evidence_digest,
            });
        }
        reverse_slices.reverse();

        maximum_update = 0.0;
        for index in &ordered {
            for time_index in 0..horizon {
                for utility in 0..utility_dimension {
                    maximum_update = maximum_update.max(
                        (current[*index][time_index][utility]
                            - previous[*index][time_index][utility])
                            .abs(),
                    );
                }
            }
        }
        maximum_update = finite(maximum_update)?;
        epochs = u32::try_from(epoch + 1).map_err(|_| NduFbsdeTrainingError::Arithmetic)?;
        converged_slices = reverse_slices;
        previous = current;
        if maximum_update <= policy.specification.convergence_tolerance {
            break;
        }
    }

    if converged_slices.len() != horizon
        || maximum_update > policy.specification.convergence_tolerance
    {
        return Err(NduFbsdeTrainingError::DidNotConverge);
    }

    let time_slices = quantize_slices(
        &converged_slices,
        policy.specification.maximum_absolute_value,
    )?;
    let mut candidate =
        candidate_without_metrics(snapshot, policy, covariance_profile, time_slices);
    candidate.metrics = evaluate_candidate_metrics(
        snapshot,
        policy,
        &candidate,
        &train,
        &holdout,
        maximum_update,
        epochs,
    )?;
    enforce_candidate_thresholds(policy, &candidate.metrics)?;
    candidate.artifact_bytes_digest = Digest32::of_bytes(&encode_candidate_artifact(&candidate));
    candidate.candidate_digest = candidate_receipt_digest(&candidate);
    validate_candidate_identity(snapshot, policy, &candidate)?;
    Ok(candidate)
}

/// Independently replays the quantized artifact and metrics without using the
/// floating-point fit state. A metric, artifact or identity substitution fails
/// closed and cannot produce a reference receipt.
pub fn reference_evaluate_ndu_fbsde_v1(
    snapshot: &NduFbsdeDatasetSnapshotV1,
    policy: &AdmittedNduFbsdeTrainingPolicyV1,
    candidate: &NduFbsdeTrainingCandidateV1,
) -> Result<NduFbsdeReferenceReceiptV1, NduFbsdeTrainingError> {
    validate_dataset(snapshot)?;
    validate_policy(&policy.specification)?;
    if canonical_policy_digest(&policy.specification) != policy.digest {
        return Err(NduFbsdeTrainingError::PolicyMismatch("policy_digest"));
    }
    validate_candidate_identity(snapshot, policy, candidate)?;
    if candidate.runtime_tuple_digest != policy.specification.runtime_tuple_digest
        || candidate.units_digest != policy.specification.units_digest
        || candidate.artifact_bytes_digest
            != Digest32::of_bytes(&encode_candidate_artifact(candidate))
    {
        return Err(NduFbsdeTrainingError::CandidateMismatch);
    }

    let ordered = ordered_trajectory_indices(snapshot)?;
    let train: Vec<usize> = ordered
        .iter()
        .copied()
        .filter(|index| snapshot.trajectories[*index].fold == NduFbsdeFoldV1::Train)
        .collect();
    let holdout: Vec<usize> = ordered
        .iter()
        .copied()
        .filter(|index| snapshot.trajectories[*index].fold == NduFbsdeFoldV1::Holdout)
        .collect();
    let metrics = reference_metrics(snapshot, policy, candidate, &train, &holdout)?;
    if metrics != candidate.metrics {
        return Err(NduFbsdeTrainingError::CandidateMismatch);
    }

    let receipt_digest = reference_receipt_digest(
        candidate.candidate_digest,
        snapshot.dataset_digest,
        candidate.artifact_bytes_digest,
        &metrics,
    );
    Ok(NduFbsdeReferenceReceiptV1 {
        candidate_digest: candidate.candidate_digest,
        dataset_digest: snapshot.dataset_digest,
        artifact_bytes_digest: candidate.artifact_bytes_digest,
        metrics,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

/// Binds a candidate to the exact registered artifact bytes and projects the
/// first Z slice through the already admitted coefficient/Z profiles. This is
/// publication evidence only; it never registers, selects or activates.
pub fn bind_ndu_fbsde_publication_v1(
    candidate: &NduFbsdeTrainingCandidateV1,
    registered_artifact_bytes_digest: Digest32,
    coefficient_profile: &AdmittedNduCoefficientProfileV1,
    z_conversion_profile: &AdmittedZConversionProfileV1,
    now_unix_ms: u64,
) -> Result<
    (NduFbsdePublicationBindingV1, NduCoefficientProjectionV1),
    NduFbsdeTrainingError,
> {
    require_digest(registered_artifact_bytes_digest, "registered_artifact")?;
    if candidate.authority.grants_any() {
        return Err(NduFbsdeTrainingError::Authority);
    }
    if candidate.artifact_bytes_digest != registered_artifact_bytes_digest
        || candidate.artifact_bytes_digest
            != Digest32::of_bytes(&encode_candidate_artifact(candidate))
        || candidate.candidate_digest != candidate_receipt_digest(candidate)
    {
        return Err(NduFbsdeTrainingError::ArtifactMismatch);
    }
    if candidate.normalization_digest != coefficient_profile.normalization_digest()
        || candidate.runtime_tuple_digest != coefficient_profile.runtime_tuple_digest()
        || candidate.covariance_profile_digest
            != coefficient_profile.covariance_profile_digest()
        || candidate.units_digest != coefficient_profile.units_digest()
        || candidate.driver_dimension != coefficient_profile.driver_dimension()
        || candidate.utility_dimension != coefficient_profile.utility_dimension()
        || coefficient_profile.z_conversion_profile_digest()
            != z_conversion_profile.digest()
    {
        return Err(NduFbsdeTrainingError::ProfileMismatch);
    }
    let first = candidate
        .time_slices
        .first()
        .ok_or(NduFbsdeTrainingError::CandidateMismatch)?;
    let estimate = ZEstimateV1 {
        z: first
            .z_q24
            .iter()
            .map(|row| row.iter().map(|value| q24_to_f64(*value)).collect())
            .collect(),
        covariance_profile_digest: candidate.covariance_profile_digest,
        condition_estimate: first.condition_estimate,
        increment_eigenvalue_lower_estimate: first.increment_eigenvalue_lower_estimate,
        maximum_relative_residual: first.maximum_relative_residual,
        evidence_digest: primary_projection_source_digest(candidate, first),
        authority: AuthorityPosture::DENY_ALL,
    };
    let projection = project_z_estimate_to_coefficient_q24(
        &estimate,
        coefficient_profile,
        z_conversion_profile,
        now_unix_ms,
    )
    .map_err(map_coefficient_profile)?;
    if projection.authority.grants_any() {
        return Err(NduFbsdeTrainingError::Authority);
    }

    let publication_digest = publication_binding_digest(
        coefficient_profile.artifact_manifest_digest(),
        candidate.artifact_bytes_digest,
        coefficient_profile.digest(),
        projection.output_digest,
        candidate.candidate_digest,
    );
    let binding = NduFbsdePublicationBindingV1 {
        artifact_manifest_digest: coefficient_profile.artifact_manifest_digest(),
        artifact_bytes_digest: candidate.artifact_bytes_digest,
        coefficient_profile_digest: coefficient_profile.digest(),
        primary_projection_digest: projection.output_digest,
        candidate_digest: candidate.candidate_digest,
        publication_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((binding, projection))
}

/// Evaluates independent shadow evidence into a monotone eligibility stage.
/// Missing independent acceptances keep the candidate in shadow; no stage ever
/// carries production activation or effect authority.
pub fn evaluate_ndu_fbsde_shadow_gate_v1(
    policy: &NduFbsdeShadowPolicyV1,
    evidence: &NduFbsdeShadowEvidenceV1,
) -> Result<NduFbsdeShadowGateReceiptV1, NduFbsdeTrainingError> {
    require_digest(policy.policy_digest, "shadow_policy")?;
    require_digest(evidence.candidate_digest, "candidate")?;
    require_digest(evidence.reference_receipt_digest, "reference_receipt")?;
    if policy.minimum_advisory_episodes == 0
        || policy.minimum_advisory_decisions == 0
        || policy.minimum_restricted_episodes < policy.minimum_advisory_episodes
        || policy.minimum_restricted_decisions < policy.minimum_advisory_decisions
    {
        return Err(NduFbsdeTrainingError::ShadowEvidence);
    }
    if evidence.window_start_unix_ms == 0
        || evidence.window_end_unix_ms <= evidence.window_start_unix_ms
    {
        return Err(NduFbsdeTrainingError::ShadowEvidence);
    }

    let independent_acceptance = !evidence.convergence_acceptance_digest.is_zero()
        && !evidence.calibration_acceptance_digest.is_zero()
        && !evidence.utility_improvement_acceptance_digest.is_zero()
        && !evidence.regression_acceptance_digest.is_zero();
    let advisory_volume = evidence.observed_episode_count >= policy.minimum_advisory_episodes
        && evidence.observed_decision_count >= policy.minimum_advisory_decisions;
    let restricted_volume = evidence.observed_episode_count >= policy.minimum_restricted_episodes
        && evidence.observed_decision_count >= policy.minimum_restricted_decisions;
    let within_failure_budget = evidence.observed_failure_count <= policy.maximum_failures;

    let stage = if independent_acceptance
        && advisory_volume
        && restricted_volume
        && within_failure_budget
        && !evidence.target_host_receipt_digest.is_zero()
    {
        NduFbsdeShadowStageV1::RestrictedWriteEligible
    } else if independent_acceptance && advisory_volume && within_failure_budget {
        NduFbsdeShadowStageV1::AdvisoryEligible
    } else {
        NduFbsdeShadowStageV1::ShadowOnly
    };
    let evidence_digest = canonical_shadow_evidence_digest(evidence);
    let receipt_digest = shadow_gate_receipt_digest(
        policy.policy_digest,
        evidence.candidate_digest,
        evidence_digest,
        stage,
    );
    Ok(NduFbsdeShadowGateReceiptV1 {
        stage,
        candidate_digest: evidence.candidate_digest,
        evidence_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
        production_activation: false,
    })
}

fn reference_receipt_digest(
    candidate_digest: Digest32,
    dataset_digest: Digest32,
    artifact_bytes_digest: Digest32,
    metrics: &NduFbsdeMetricsV1,
) -> Digest32 {
    let mut payload = b"hepta.ndu.fbsde.reference-receipt.v1\0".to_vec();
    payload.extend_from_slice(candidate_digest.as_array());
    payload.extend_from_slice(dataset_digest.as_array());
    payload.extend_from_slice(artifact_bytes_digest.as_array());
    append_metrics(&mut payload, metrics);
    Digest32::of_bytes(&payload)
}

fn publication_binding_digest(
    artifact_manifest_digest: Digest32,
    artifact_bytes_digest: Digest32,
    coefficient_profile_digest: Digest32,
    primary_projection_digest: Digest32,
    candidate_digest: Digest32,
) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.ndu.fbsde.publication-binding.v1\0",
        artifact_manifest_digest.as_array(),
        artifact_bytes_digest.as_array(),
        coefficient_profile_digest.as_array(),
        primary_projection_digest.as_array(),
        candidate_digest.as_array(),
    ])
}

fn shadow_gate_receipt_digest(
    policy_digest: Digest32,
    candidate_digest: Digest32,
    evidence_digest: Digest32,
    stage: NduFbsdeShadowStageV1,
) -> Digest32 {
    let stage_tag = [match stage {
        NduFbsdeShadowStageV1::ShadowOnly => 0,
        NduFbsdeShadowStageV1::AdvisoryEligible => 1,
        NduFbsdeShadowStageV1::RestrictedWriteEligible => 2,
    }];
    Digest32::of_parts(&[
        b"hepta.ndu.fbsde.shadow-gate-receipt.v1\0",
        policy_digest.as_array(),
        candidate_digest.as_array(),
        evidence_digest.as_array(),
        &stage_tag,
    ])
}
