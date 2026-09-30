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
        for ²È="25¥±Ñ•È¡ñ¥¹‘•áðÍ¹…ÁÍ¡½Ð¹ÑÉ…©•Ñ½É¥•Íl©¥¹‘•át¹™½±€ôô9‘Õ‰Í‘•½±‘XÄèéQÉ…¥¸¤(€€€€€€€€¹½±±•Ð ¤ì(€€€±•Ð¡½±‘½ÕÐèY•ŒñÕÍ¥é”ø€ô½É‘•É•(€€€€€€€€¹¥Ñ•È ¤(€€€€€€€€¹½Á¥• ¤(€€€€€€€€¹™¥±Ñ•È¡ñ¥¹‘•áðÍ¹…ÁÍ¡½Ð¹ÑÉ…©•Ñ½É¥•Íl©¥¹‘•át¹™½±€ôô9‘Õ‰Í‘•½±‘XÄèé!½±‘½ÕÐ¤(€€€€€€€€¹½±±•Ð ¤ì(€€€±•Ðµ•ÑÉ¥Ì€ôÉ•™•É•¹•}µ•ÑÉ¥Ì¡Í¹…ÁÍ¡½Ð°Á½±¥ä°…¹‘¥‘…Ñ”°€™ÑÉ…¥¸°€™¡½±‘½ÕÐ¤üì(€€€¥˜µ•ÑÉ¥Ì€„ô…¹‘¥‘…Ñ”¹µ•ÑÉ¥Ìì(€€€€€€€É•ÑÕÉ¸ÉÈ¡9‘Õ‰Í‘•QÉ…¥¹¥¹ÉÉ½Èèé…¹‘¥‘…Ñ•5¥Íµ…Ñ ¤ì(€€€ô((€€€±•ÐµÕÐÁ…å±½…€ôˆ‰¡•ÁÑ„¹¹‘Ô¹™‰Í‘”¹É•™•É•¹”µÉ•Á±…ä¹ØÅpÀˆ¹Ñ½}Ù•Œ ¤ì(€€€™½È‘¥•ÍÐ¥¸l(€€€€€€€…¹‘¥‘…Ñ”¹…¹‘¥‘…Ñ•}‘¥•ÍÐ°(€€€€€€€…¹‘¥‘…Ñ”¹‘…Ñ…Í•Ñ}‘¥•ÍÐ°(€€€€€€€…ÉÑ¥™…Ñ}‰åÑ•Í}‘¥•ÍÐ°(€€€€€€€Á½±¥ä¹‘¥•ÍÐ°(€€€tì(€€€€€€€Á…å±½…¹•áÑ•¹‘}™É½µ}Í±¥”¡‘¥•ÍÐ¹…Í}…ÉÉ…ä ¤¤ì(€€€ô(€€€…ÁÁ•¹‘}µ•ÑÉ¥Ì ™µÕÐÁ…å±½…°€™µ•ÑÉ¥Ì¤ì(€€€±•ÐÉ••¥ÁÑ}‘¥•ÍÐ€ô¥•ÍÐÌÈèé½™}‰åÑ•Ì ™Á…å±½…¤ì(€€€=¬¡9‘Õ‰Í‘•I•™•É•¹•I••¥ÁÑXÄì(€€€€€€€…¹‘¥‘…Ñ•}‘¥•ÍÐè…¹‘¥‘…Ñ”¹…¹‘¥‘…Ñ•}‘¥•ÍÐ°(€€€€€€€‘…Ñ…Í•Ñ}‘¥•ÍÐè…¹‘¥‘…Ñ”¹‘…Ñ…Í•Ñ}‘¥•ÍÐ°(€€€€€€€…ÉÑ¥™…Ñ}‰åÑ•Í}‘¥•ÍÐ°(€€€€€€€µ•ÑÉ¥Ì°(€€€€€€€É••¥ÁÑ}‘¥•ÍÐ°(€€€€€€€…ÕÑ¡½É¥ÑäèÕÑ¡½É¥ÑåA½ÍÑÕÉ”èé9e}10°(€€€ô¤)ô((¼¼¼	¥¹‘Ì…±É•…‘äµÉ•¥ÍÑ•É•¥µµÕÑ…‰±”…ÉÑ¥™…Ð‰åÑ•ÌÑ¼Ñ¡”…‘µ¥ÑÑ•½•™™¥¥•¹Ð(¼¼¼ÁÉ½™¥±”…¹É•…Ñ•ÌÑ¡”•á¥ÍÑ¥¹œÁÉ¥µ…ÉähÁÉ½©•Ñ¥½¸ÕÍ•‰äÑ¡”ÍÑ½¡…ÍÑ¥Œ(¼¼¼…‘µ¥ÍÍ¥½¸Á…Ñ ¸Q¡¥Ì™Õ¹Ñ¥½¸‘½•Ì¹½ÐÉ•¥ÍÑ•È°Í•±•Ð½È…Ñ¥Ù…Ñ”‰åÑ•Ì¸)ÁÕˆ™¸‰¥¹‘}¹‘Õ}™‰Í‘•}ÁÕ‰±¥…Ñ¥½¹}ØÄ (€€€…¹‘¥‘…Ñ”è€™9‘Õ‰Í‘•QÉ…¥¹¥¹…¹‘¥‘…Ñ•XÄ°(€€€É•¥ÍÑ•É•‘}…ÉÑ¥™…Ñ}‰åÑ•Í}‘¥•ÍÐè¥•ÍÐÌÈ°(€€€½•™™¥¥•¹Ñ}ÁÉ½™¥±”è€™‘µ¥ÑÑ•‘9‘Õ½•™™¥¥•¹ÑAÉ½™¥±•XÄ°(€€€é}½¹Ù•ÉÍ¥½¹}ÁÉ½™¥±”è€™‘µ¥ÑÑ•‘i½¹Ù•ÉÍ¥½¹AÉ½™¥±•XÄ°(€€€¹½Ý}Õ¹¥á}µÌèÔØÐ°(¤€´øI•ÍÕ±Ðð¡9‘Õ‰Í‘•AÕ‰±¥…Ñ¥½¹	¥¹‘¥¹XÄ°9‘Õ½•™™¥¥•¹ÑAÉ½©•Ñ¥½¹XÄ¤°9‘Õ‰Í‘•QÉ…¥¹¥¹ÉÉ½Èøì(€€€¥˜…¹‘¥‘…Ñ”¹…ÕÑ¡½É¥Ñä¹É…¹ÑÍ}…¹ä ¤ì(€€€€€€€É•ÑÕÉ¸ÉÈ¡9‘Õ‰Í‘•QÉ…¥¹¥¹ÉÉ½ÈèéÕÑ¡½É¥Ñä¤ì(€€€ô(€€€¥˜É•¥ÍÑ•É•‘}…ÉÑ¥™…Ñ}‰åÑ•Í}‘¥•ÍÐ¹¥Í}é•É¼ ¤(€€€€€€€ñðÉ•¥ÍÑ•É•‘}…ÉÑ¥™…Ñ}‰åÑ•Í}‘¥•ÍÐ€„ô…¹‘¥‘…Ñ”¹…ÉÑ¥™…Ñ}‰åÑ•Í}‘¥•ÍÐ(€€€ì(€€€€€€€É•ÑÕÉ¸ÉÈ¡9‘Õ‰Í‘•QÉ…¥¹¥¹ÉÉ½ÈèéÉÑ¥™…Ñ5¥Íµ…Ñ ¤ì(€€€ô(€€€¥˜½•™™¥¥•¹Ñ}ÁÉ½™¥±”¹¹½Éµ…±¥é…Ñ¥½¹}‘¥•ÍÐ ¤€„ô…¹‘¥‘…Ñ”¹¹½Éµ…±¥é…Ñ¥½¹}‘¥•ÍÐ(€€€€€€€ñð½•™™¥¥•¹Ñ}ÁÉ½™¥±”¹ÉÕ¹Ñ¥µ•}ÑÕÁ±•}‘¥•ÍÐ ¤€„ô…¹‘¥‘…Ñ”¹ÉÕ¹Ñ¥µ•}ÑÕÁ±•}‘¥•ÍÐ(€€€€€€€ñð½•™™¥¥•¹Ñ}ÁÉ½™¥±”¹Õ¹¥ÑÍ}‘¥•ÍÐ ¤€„ô…¹‘¥‘…Ñ”¹Õ¹¥ÑÍ}‘¥•ÍÐ(€€€€€€€ñð½•™™¥¥•¹Ñ}ÁÉ½™¥±”¹½Ù…É¥…¹•}ÁÉ½™¥±•}‘¥•ÍÐ ¤(€€€€€€€€€€€€„ô…¹‘¥‘…Ñ”¹½Ù…É¥…¹•}ÁÉ½™¥±•}‘¥•ÍÐ(€€€€€€€ñð½•™™¥¥•¹Ñ}ÁÉ½™¥±”¹‘É¥Ù•É}‘¥µ•¹Í¥½¸ ¤€„ô…¹‘¥‘…Ñ”¹‘É¥Ù•É}‘¥µ•¹Í¥½¸(€€€€€€€ñð½•™™¥¥•¹Ñ}ÁÉ½™¥±”¹ÕÑ¥±¥Ñå}‘¥µ•¹Í¥½¸ ¤€„ô…¹‘¥‘…Ñ”¹ÕÑ¥±¥Ñå}‘¥µ•¹Í¥½¸(€€€ì(€€€€€€€É•ÑÕÉ¸ÉÈ¡9‘Õ‰Í‘•QÉ…¥¹¥¹ÉÉ½ÈèéAÉ½™¥±•5¥Íµ…Ñ ¤ì(€€€ô(€€€¥˜¹½Ý}Õ¹¥á}µÌ€øô½•™™¥¥•¹Ñ}ÁÉ½™¥±”¹•áÁ¥É•Í}Õ¹¥á}µÌ ¤ì(€€€€€€€É•ÑÕÉ¸ÉÈ¡9‘Õ‰Í‘•QÉ…¥¹¥¹ÉÉ½ÈèéáÁ¥É•¤ì(€€€ô(€€€±•Ð™¥ÉÍÐ€ô…¹‘¥‘…Ñ”(€€€€€€€€¹Ñ¥µ•}Í±¥•Ì(€€€€€€€€¹™¥ÉÍÐ ¤(€€€€€€€€¹½­}½È¡9‘Õ‰Í‘•QÉ…¥¹¥¹ÉÉ½Èèé%¹Ù…±¥‘!½É¥é½¸¤üì(€€€±•Ðè€ô™¥ÉÍÐ(€€€€€€€€¹é}ÄÈÐ(€€€€€€€€¹¥Ñ•È ¤(€€€€€€€€¹µ…À¡ñÉ½ÝðÉ½Ü¹¥Ñ•È ¤¹µ…À¡ñÙ…±Õ•ðÄÈÑ}Ñ½}˜ØÐ ©Ù…±Õ”¤¤¹½±±•Ð ¤¤(€€€€€€€€¹½±±•Ð ¤ì(€€€±•Ð•ÍÑ¥µ…Ñ”€ôiÍÑ¥µ…Ñ•XÄì(€€€€€€€è°(€€€€€€€½Ù…É¥…¹•}ÁÉ½™¥±•}‘¥•ÍÐè…¹‘¥‘…Ñ”¹½Ù…É¥…¹•}ÁÉ½™¥±•}‘¥•ÍÐ°(€€€€€€€½¹‘¥Ñ¥½¹}•ÍÑ¥µ…Ñ”è™¥ÉÍÐ¹½¹‘¥Ñ¥½¹}•ÍÑ¥µ…Ñ”°(€€€€€€€¥¹É•µ•¹Ñ}•¥•¹Ù…±Õ•}±½Ý•É}•ÍÑ¥µ…Ñ”è™¥ÉÍÐ¹¥¹É•µ•¹Ñ}•¥•¹Ù…±Õ•}±½Ý•É}•ÍÑ¥µ…Ñ”°(€€€€€€€µ…á¥µÕµ}É•±…Ñ¥Ù•}É•Í¥‘Õ…°è™¥ÉÍÐ¹µ…á¥µÕµ}É•±…Ñ¥Ù•}É•Í¥‘Õ…°°(€€€€€€€•Ù¥‘•¹•}‘¥•ÍÐèÁÉ¥µ…Éå}ÁÉ½©•Ñ¥½¹}Í½ÕÉ•}‘¥•ÍÐ¡…¹‘¥‘…Ñ”°™¥ÉÍÐ¤°(€€€€€€€…ÕÑ¡½É¥ÑäèÕÑ¡½É¥ÑåA½ÍÑÕÉ”èé9e}10°(€€€ôì(€€€±•ÐÁÉ½©•Ñ¥½¸€ôÁÉ½©•Ñ}é}•ÍÑ¥µ…Ñ•}Ñ½}½•™™¥¥•¹Ñ}ÄÈÐ (€€€€€€€€™•ÍÑ¥µ…Ñ”°(€€€€€€€½•™™¥¥•¹Ñ}ÁÉ½™¥±”°(€€€€€€€é}½¹Ù•ÉÍ¥½¹}ÁÉ½™¥±”°(€€€€€€€¹½Ý}Õ¹¥á}µÌ°(€€€€¤(€€€€¹µ…Á}•ÉÈ¡µ…Á}½•™™¥¥•¹Ñ}ÁÉ½™¥±”¤üì((€€€±•Ð…ÉÑ¥™…Ñ}µ…¹¥™•ÍÑ}‘¥•ÍÐ€ô½•™™¥¥•¹Ñ}ÁÉ½™¥±”¹…ÉÑ¥™…Ñ}µ…¹¥™•ÍÑ}‘¥•ÍÐ ¤ì(€€€±•ÐµÕÐÁ…å±½…€ôˆ‰¡•ÁÑ„¹¹‘Ô¹™‰Í‘”¹ÁÕ‰±¥…Ñ¥½¸µ‰¥¹‘¥¹œ¹ØÅpÀˆ¹Ñ½}Ù•Œ ¤ì(€€€™½È‘¥•ÍÐ¥¸l(€€€€€€€…ÉÑ¥™…Ñ}µ…¹¥™•ÍÑ}‘¥•ÍÐ°(€€€€€€€É•¥ÍÑ•É•‘}…ÉÑ¥™…Ñ}‰åÑ•Í}‘¥•ÍÐ°(€€€€€€€½•™™¥¥•¹Ñ}ÁÉ½™¥±”¹‘¥•ÍÐ ¤°(€€€€€€€ÁÉ½©•Ñ¥½¸¹½ÕÑÁÕÑ}‘¥•ÍÐ°(€€€€€€€…¹‘¥‘…Ñ”¹…¹‘¥‘…Ñ•}‘¥•ÍÐ°(€€€tì(€€€€€€€Á…å±½…¹•áÑ•¹‘}™É½µ}Í±¥”¡‘¥•ÍÐ¹…Í}…ÉÉ…ä ¤¤ì(€€€ô(€€€±•ÐÁÕ‰±¥…Ñ¥½¹}‘¥•ÍÐ€ô¥•ÍÐÌÈèé½™}‰åÑ•Ì ™Á…å±½…¤ì(€€€=¬  (€€€€€€€9‘Õ‰Í‘•AÕ‰±¥…Ñ¥½¹	¥¹‘¥¹XÄì(€€€€€€€€€€€…ÉÑ¥™…Ñ}µ…¹¥™•ÍÑ}‘¥•ÍÐ°(€€€€€€€€€€€…ÉÑ¥™…Ñ}‰åÑ•Í}‘¥•ÍÐèÉ•¥ÍÑ•É•‘}…ÉÑ¥™…Ñ}‰åÑ•Í}‘¥•ÍÐ°(€€€€€€€€€€€½•™™¥¥•¹Ñ}ÁÉ½™¥±•}‘¥•ÍÐè½•™™¥¥•¹Ñ}ÁÉ½™¥±”¹‘¥•ÍÐ ¤°(€€€€€€€€€€€ÁÉ¥µ…Éå}ÁÉ½©•Ñ¥½¹}‘¥•ÍÐèÁÉ½©•Ñ¥½¸¹½ÕÑÁÕÑ}‘¥•ÍÐ°(€€€€€€€€€€€…¹‘¥‘…Ñ•}‘¥•ÍÐè…¹‘¥‘…Ñ”¹…¹‘¥‘…Ñ•}‘¥•ÍÐ°(€€€€€€€€€€€ÁÕ‰±¥…Ñ¥½¹}‘¥•ÍÐ°(€€€€€€€€€€€…ÕÑ¡½É¥ÑäèÕÑ¡½É¥ÑåA½ÍÑÕÉ”èé9e}10°(€€€€€€€ô°(€€€€€€€ÁÉ½©•Ñ¥½¸°(€€€€¤¤)ô((¼¼¼½µÁ½Í•Ì…ÕÑ¡•¹Ñ¥…Ñ•¥¹‘•Á•¹‘•¹Ð•Ù¥‘•¹”¥‘•¹Ñ¥Ñ¥•Ì…¹½‰Í•ÉÙ•Í¡…‘½Ü(¼¼¼Ù½±Õµ”¥¹Ñ¼„9e}10ÍÑ…”µ•±¥¥‰¥±¥ÑäÉ••¥ÁÐ¸%Ð¹•Ù•È…Ñ¥Ù…Ñ•Ì„(¼¼¼ÝÉ¥Ñ•È¸ÁÉ½‘ÕÐ½Ý¹•ÈµÕÍÐ…ÕÑ¡•¹Ñ¥…Ñ”Ñ¡”ÍÕÁÁ±¥••Ù¥‘•¹”‘¥•ÍÑÌ¸)ÁÕˆ™¸•Ù…±Õ…Ñ•}¹‘Õ}™‰Í‘•}Í¡…‘½Ý}…Ñ•}ØÄ (€€€Á½±¥äè€™9‘Õ‰Í‘•M¡…‘½ÝA½±¥åXÄ°(€€€•Ù¥‘•¹”è€™9‘Õ‰Í‘•M¡…‘½ÝÙ¥‘•¹•XÄ°(¤€´øI•ÍÕ±Ðñ9‘Õ‰Í‘•M¡…‘½Ý…Ñ•I••¥ÁÑXÄ°9‘Õ‰Í‘•QÉ…¥¹¥¹ÉÉ½Èøì(€€€¥˜Á½±¥ä¹Á½±¥å}‘¥•ÍÐ¹¥Í}é•É¼ ¤(€€€€€€€ñðÁ½±¥ä¹µ¥¹¥µÕµ}…‘Ù¥Í½Éå}•Á¥Í½‘•Ì€ôô€À(€€€€€€€ñðÁ½±¥ä¹µ¥¹¥µÕµ}…‘Ù¥Í½Éå}‘•¥Í¥½¹Ì€ôô€À(€€€€€€€ñðÁ½±¥ä¹µ¥¹¥µÕµ}É•ÍÑÉ¥Ñ•‘}•Á¥Í½‘•Ì€ðÁ½±¥ä¹µ¥¹¥µÕµ}…‘Ù¥Í½Éå}•Á¥Í½‘•Ì(€€€€€€€ñðÁ½±¥ä¹µ¥¹¥µÕµ}É•ÍÑÉ¥Ñ•‘}‘•¥Í¥½¹Ì€ðÁ½±¥ä¹µ¥¹¥µÕµ}…‘Ù¥Í½Éå}‘•¥Í¥½¹Ì(€€€€€€€ñð•Ù¥‘•¹”¹…¹‘¥‘…Ñ•}‘¥•ÍÐ¹¥Í}é•É¼ ¤(€€€€€€€ñð•Ù¥‘•¹”¹É•™•É•¹•}É••¥ÁÑ}‘¥•ÍÐ¹¥Í}é•É¼ ¤(€€€€€€€ñð•Ù¥‘•¹”¹Ý¥¹‘½Ý}ÍÑ…ÉÑ}Õ¹¥á}µÌ€øô•Ù¥‘•¹”¹Ý¥¹‘½Ý}•¹‘}Õ¹¥á}µÌ(€€€ì(€€€€€€€É•ÑÕÉ¸ÉÈ¡9‘Õ‰Í‘•QÉ…¥¹¥¹ÉÉ½ÈèéM¡…‘½ÝÙ¥‘•¹”¤ì(€€€ô(€€€±•Ð¥¹‘•Á•¹‘•¹Ð€ôl(€€€€€€€•Ù¥‘•¹”¹½¹Ù•É•¹•}…•ÁÑ…¹•}‘¥•ÍÐ°(€€€€€€€•Ù¥‘•¹”¹…±¥‰É…Ñ¥½¹}…•ÁÑ…¹•}‘¥•ÍÐ°(€€€€€€€•Ù¥‘•¹”¹ÕÑ¥±¥Ñå}¥µÁÉ½Ù•µ•¹Ñ}…•ÁÑ…¹•}‘¥•ÍÐ°(€€€€€€€•Ù¥‘•¹”¹É•É•ÍÍ¥½¹}…•ÁÑ…¹•}‘¥•ÍÐ°(€€€tì(€€€±•Ð…±±}¥¹‘•Á•¹‘•¹Ð€ô¥¹‘•Á•¹‘•¹Ð¹¥Ñ•È ¤¹…±°¡ñ‘¥•ÍÑð€…‘¥•ÍÐ¹¥Í}é•É¼ ¤¤ì(€€€±•Ð™…¥±ÕÉ•Í}½¬€ô•Ù¥‘•¹”¹½‰Í•ÉÙ•‘}™…¥±ÕÉ•}½Õ¹Ð€ðôÁ½±¥ä¹µ…á¥µÕµ}™…¥±ÕÉ•Ìì(€€€±•Ð…‘Ù¥Í½Éå}Ù½±Õµ”€ô•Ù¥‘•¹”¹½‰Í•ÉÙ•‘}•Á¥Í½‘•}½Õ¹Ð€øôÁ½±¥ä¹µ¥¹¥µÕµ}…‘Ù¥Í½Éå}•Á¥Í½‘•Ì(€€€€€€€€˜˜•Ù¥‘•¹”¹½‰Í•ÉÙ•‘}‘•¥Í¥½¹}½Õ¹Ð€øôÁ½±¥ä¹µ¥¹¥µÕµ}…‘Ù¥Í½Éå}‘•¥Í¥½¹Ìì(€€€±•ÐÉ•ÍÑÉ¥Ñ•‘}Ù½±Õµ”€ô(€€€€€€€•Ù¥‘•¹”¹½‰Í•ÉÙ•‘}•Á¥Í½‘•}½Õ¹Ð€øôÁ½±¥ä¹µ¥¹¥µÕµ}É•ÍÑÉ¥Ñ•‘}•Á¥Í½‘•Ì(€€€€€€€€€€€€˜˜•Ù¥‘•¹”¹½‰Í•ÉÙ•‘}‘•¥Í¥½¹}½Õ¹Ð€øôÁ½±¥ä¹µ¥¹¥µÕµ}É•ÍÑÉ¥Ñ•‘}‘•¥Í¥½¹Ìì(€€€±•ÐÍÑ…”€ô¥˜…±±}¥¹‘•Á•¹‘•¹Ð(€€€€€€€€˜˜™…¥±ÕÉ•Í}½¬(€€€€€€€€˜˜É•ÍÑÉ¥Ñ•‘}Ù½±Õµ”(€€€€€€€€˜˜€…•Ù¥‘•¹”¹Ñ…É•Ñ}¡½ÍÑ}É••¥ÁÑ}‘¥•ÍÐ¹¥Í}é•É¼ ¤(€€€ì(€€€€€€€9‘Õ‰Í‘•M¡…‘½ÝMÑ…•XÄèéI•ÍÑÉ¥Ñ•‘]É¥Ñ•±¥¥‰±”(€€€ô•±Í”¥˜…±±}¥¹‘•Á•¹‘•¹Ð€˜˜™…¥±ÕÉ•Í}½¬€˜˜…‘Ù¥Í½Éå}Ù½±Õµ”ì(€€€€€€€9‘Õ‰Í‘•M¡…‘½ÝMÑ…•XÄèé‘Ù¥Í½Éå±¥¥‰±”(€€€ô•±Í”ì(€€€€€€€9‘Õ‰Í‘•M¡…‘½ÝMÑ…•XÄèéM¡…‘½Ý=¹±ä(€€€ôì((€€€±•Ð•Ù¥‘•¹•}‘¥•ÍÐ€ô…¹½¹¥…±}Í¡…‘½Ý}•Ù¥‘•¹•}‘¥•ÍÐ¡•Ù¥‘•¹”¤ì(€€€±•ÐµÕÐÁ…å±½…€ôˆ‰¡•ÁÑ„¹¹‘Ô¹™‰Í‘”¹Í¡…‘½Üµ…Ñ”¹ØÅpÀˆ¹Ñ½}Ù•Œ ¤ì(€€€Á…å±½…¹•áÑ•¹‘}™É½µ}Í±¥”¡Á½±¥ä¹Á½±¥å}‘¥•ÍÐ¹…Í}…ÉÉ…ä ¤¤ì(€€€Á…å±½…¹•áÑ•¹‘}™É½µ}Í±¥”¡•Ù¥‘•¹•}‘¥•ÍÐ¹…Í}…ÉÉ…ä ¤¤ì(€€€Á…å±½…¹ÁÕÍ ¡µ…Ñ ÍÑ…”ì(€€€€€€€9‘Õ‰Í‘•M¡…‘½ÝMÑ…•XÄèéM¡…‘½Ý=¹±ä€ôø€À°(€€€€€€€9‘Õ‰Í‘•M¡…‘½ÝMÑ…•XÄèé‘Ù¥Í½Éå±¥¥‰±”€ôø€Ä°(€€€€€€€9‘Õ‰Í‘•M¡…‘½ÝMÑ…•XÄèéI•ÍÑÉ¥Ñ•‘]É¥Ñ•±¥¥‰±”€ôø€È°(€€€ô¤ì(€€€±•ÐÉ••¥ÁÑ}‘¥•ÍÐ€ô¥•ÍÐÌÈèé½™}‰åÑ•Ì ™Á…å±½…¤ì(€€€=¬¡9‘Õ‰Í‘•M¡…‘½Ý…Ñ•I••¥ÁÑXÄì(€€€€€€€ÍÑ…”°(€€€€€€€…¹‘¥‘…Ñ•}‘¥•ÍÐè•Ù¥‘•¹”¹…¹‘¥‘…Ñ•}‘¥•ÍÐ°(€€€€€€€•Ù¥‘•¹•}‘¥•ÍÐ°(€€€€€€€É••¥ÁÑ}‘¥•ÍÐ°(€€€€€€€…ÕÑ¡½É¥ÑäèÕÑ¡½É¥ÑåA½ÍÑÕÉ”èé9e}10°(€€€€€€€ÁÉ½‘ÕÑ¥½¹}…Ñ¥Ù…Ñ¥½¸è™…±Í”°(€€€ô¤)ô((