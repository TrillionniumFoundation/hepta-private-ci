use codex_hepta_types::Digest32;

use crate::AdmittedCovarianceProfileV1;
use crate::CovarianceConventionV1;
use crate::CovarianceError;

#[derive(Clone, Debug, PartialEq)]
pub struct ConditionalMomentSampleV1 {
    /// Identity of an externally defined, pre-boundary conditioning stratum.
    pub conditioning_digest: Digest32,
    pub duration_micros: u64,
    pub increment: Vec<f64>,
    pub utility: Vec<f64>,
}

/// Centered population moments (divisor n), not an unbiased n-1 estimator.
/// The cross moment always uses increment units; covariance uses the profile.
#[derive(Clone, Debug, PartialEq)]
pub struct ConditionalMomentsV1 {
    pub profile_digest: Digest32,
    pub conditioning_digest: Digest32,
    pub source_digest: Digest32,
    pub duration_micros: u64,
    pub sample_count: usize,
    pub mean_increment: Vec<f64>,
    pub mean_utility: Vec<f64>,
    pub covariance: Vec<Vec<f64>>,
    pub cross_moment: Vec<Vec<f64>>,
}

pub(crate) fn duration_seconds(duration_micros: u64) -> Result<f64, CovarianceError> {
    if !(1_000..=3_600_000_000).contains(&duration_micros) {
        return Err(CovarianceError::Duration);
    }
    Ok(duration_micros as f64 / 1_000_000.0)
}

/// Estimates one declared stratum with bounded, centered online moments.
/// Upstream must verify source provenance and that conditioning uses no future
/// features. Matching digests do not establish conditional identification.
pub fn estimate_conditional_moments(
    samples: &[ConditionalMomentSampleV1],
    source_digest: Digest32,
    profile: &AdmittedCovarianceProfileV1,
) -> Result<ConditionalMomentsV1, CovarianceError> {
    if !(2..=512).contains(&samples.len()) {
        return Err(CovarianceError::SampleCount);
    }
    let first = &samples[0];
    if source_digest.is_zero() || first.conditioning_digest.is_zero() {
        return Err(CovarianceError::MissingDigest);
    }
    let dt = duration_seconds(first.duration_micros)?;
    let spec = &profile.specification;
    let d = spec.driver_dimension;
    let u = spec.utility_dimension;
    for sample in samples {
        if sample.conditioning_digest != first.conditioning_digest {
            return Err(CovarianceError::ConditioningMismatch);
        }
        if sample.duration_micros != first.duration_micros {
            return Err(CovarianceError::Duration);
        }
        if sample.increment.len() != d || sample.utility.len() != u {
            return Err(CovarianceError::Dimension);
        }
        for value in sample.increment.iter().chain(&sample.utility) {
            if !value.is_finite() {
                return Err(CovarianceError::NonFinite);
            }
            if value.abs() > spec.maximum_absolute_sample {
                return Err(CovarianceError::SampleBound);
            }
        }
    }
    let mut result = ConditionalMomentsV1 {
        profile_digest: profile.digest,
        conditioning_digest: first.conditioning_digest,
        source_digest,
        duration_micros: first.duration_micros,
        sample_count: samples.len(),
        mean_increment: vec![0.0; d],
        mean_utility: vec![0.0; u],
        covariance: vec![vec![0.0; d]; d],
        cross_moment: vec![vec![0.0; d]; u],
    };
    for (index, sample) in samples.iter().enumerate() {
        let count = (index + 1) as f64;
        let mut delta = [0.0; 32];
        for (i, mean) in result.mean_increment.iter_mut().enumerate() {
            delta[i] = sample.increment[i] - *mean;
            *mean += delta[i] / count;
        }
        for (i, row) in result.covariance.iter_mut().enumerate() {
            for (j, value) in row.iter_mut().enumerate() {
                *value += delta[i] * (sample.increment[j] - result.mean_increment[j]);
            }
        }
        for (i, mean) in result.mean_utility.iter_mut().enumerate() {
            let utility_delta = sample.utility[i] - *mean;
            *mean += utility_delta / count;
            for (j, value) in result.cross_moment[i].iter_mut().enumerate() {
                *value += utility_delta * (sample.increment[j] - result.mean_increment[j]);
            }
        }
    }
    let covariance_divisor = samples.len() as f64
        * match spec.convention {
            CovarianceConventionV1::Increment => 1.0,
            CovarianceConventionV1::RatePerSecond => dt,
        };
    for i in 0..d {
        for j in 0..=i {
            let value =
                (result.covariance[i][j] + result.covariance[j][i]) / (2.0 * covariance_divisor);
            result.covariance[i][j] = value;
            result.covariance[j][i] = value;
        }
    }
    for value in result.cross_moment.iter_mut().flatten() {
        *value /= samples.len() as f64;
    }
    if result
        .covariance
        .iter()
        .flatten()
        .chain(result.cross_moment.iter().flatten())
        .any(|value| !value.is_finite())
    {
        return Err(CovarianceError::Arithmetic);
    }
    Ok(result)
}
