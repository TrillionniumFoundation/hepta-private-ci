#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CalibrationObservationV1 {
    pub confidence: ProbabilityQ32,
    pub outcome: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct OodObservationV1 {
    pub score: ProbabilityQ32,
    pub in_domain: bool,
}

/// Deterministic fixed-point expected calibration error. The calculation uses
/// equal-width bins and exact integer accumulation; no caller-supplied ECE is
/// trusted by the V3 qualification test path.
pub fn expected_calibration_error_ppm_v1(
    observations: &[CalibrationObservationV1],
    bins: usize,
) -> Result<u32, QualificationError> {
    if observations.is_empty() {
        return Err(QualificationError::EmptyCalibrationDataset);
    }
    if bins == 0 || bins > MAX_CALIBRATION_BINS {
        return Err(QualificationError::InvalidCalibrationBins);
    }
    let one = u128::from(ProbabilityQ32::ONE.raw());
    let bins_u128 = u128::try_from(bins).map_err(|_| QualificationError::Arithmetic)?;
    let mut confidence_sum = vec![0u128; bins];
    let mut positives = vec![0u128; bins];
    for observation in observations {
        let raw = u128::from(observation.confidence.raw());
        let mut index = raw
            .checked_mul(bins_u128)
            .ok_or(QualificationError::Arithmetic)?
            / one;
        if index >= bins_u128 {
            index = bins_u128 - 1;
        }
        let index = usize::try_from(index).map_err(|_| QualificationError::Arithmetic)?;
        confidence_sum[index] = confidence_sum[index]
            .checked_add(raw)
            .ok_or(QualificationError::Arithmetic)?;
        if observation.outcome {
            positives[index] = positives[index]
                .checked_add(1)
                .ok_or(QualificationError::Arithmetic)?;
        }
    }
    let mut weighted_error_raw = 0u128;
    for index in 0..bins {
        let positive_mass = positives[index]
            .checked_mul(one)
            .ok_or(QualificationError::Arithmetic)?;
        weighted_error_raw = weighted_error_raw
            .checked_add(confidence_sum[index].abs_diff(positive_mass))
            .ok_or(QualificationError::Arithmetic)?;
    }
    let denominator = u128::try_from(observations.len())
        .map_err(|_| QualificationError::Arithmetic)?
        .checked_mul(one)
        .ok_or(QualificationError::Arithmetic)?;
    let numerator = weighted_error_raw
        .checked_mul(PPM)
        .ok_or(QualificationError::Arithmetic)?;
    let rounded = numerator
        .checked_add(denominator / 2)
        .ok_or(QualificationError::Arithmetic)?
        / denominator;
    u32::try_from(rounded).map_err(|_| QualificationError::Arithmetic)
}

pub fn ood_false_acceptance_ppm_v1(
    observations: &[OodObservationV1],
    maximum_in_domain_score: ProbabilityQ32,
) -> Result<u32, QualificationError> {
    if observations.is_empty() {
        return Err(QualificationError::EmptyOodDataset);
    }
    let mut out_of_domain = 0u128;
    let mut false_accepts = 0u128;
    for observation in observations {
        if observation.in_domain {
            continue;
        }
        out_of_domain = out_of_domain
            .checked_add(1)
            .ok_or(QualificationError::Arithmetic)?;
        if observation.score <= maximum_in_domain_score {
            false_accepts = false_accepts
                .checked_add(1)
                .ok_or(QualificationError::Arithmetic)?;
        }
    }
    if out_of_domain == 0 {
        return Err(QualificationError::MissingOodExamples);
    }
    let numerator = false_accepts
        .checked_mul(PPM)
        .ok_or(QualificationError::Arithmetic)?;
    let rounded = numerator
        .checked_add(out_of_domain / 2)
        .ok_or(QualificationError::Arithmetic)?
        / out_of_domain;
    u32::try_from(rounded).map_err(|_| QualificationError::Arithmetic)
}
