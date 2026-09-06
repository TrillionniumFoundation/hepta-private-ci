use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::AdmittedCovarianceProfileV1;
use crate::ConditionalMomentsV1;
use crate::CovarianceConventionV1;
use crate::CovarianceError;
use crate::conditional_moments::duration_seconds;

#[derive(Clone, Debug, PartialEq)]
pub struct ZEstimateV1 {
    /// Utility x driver sensitivity in the original increment coordinates.
    pub z: Vec<Vec<f64>>,
    /// Conservative matrix 1-norm diagnostic, not a statistical certificate.
    pub condition_estimate: f64,
    pub increment_eigenvalue_lower_estimate: f64,
    pub maximum_relative_residual: f64,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Solves centered Z Sigma = B with a scaled Cholesky factorization.
/// Rate profiles solve Z Q = B / dt. No inverse matrix, regularization,
/// clipping, pseudoinverse, artifact selection or production activation occurs.
pub fn solve_backward_regression(
    moments: &ConditionalMomentsV1,
    profile: &AdmittedCovarianceProfileV1,
) -> Result<ZEstimateV1, CovarianceError> {
    let spec = &profile.specification;
    let d = spec.driver_dimension;
    let u = spec.utility_dimension;
    if moments.profile_digest != profile.digest {
        return Err(CovarianceError::ProfileMismatch);
    }
    if moments.conditioning_digest.is_zero() || moments.source_digest.is_zero() {
        return Err(CovarianceError::MissingDigest);
    }
    let dt = duration_seconds(moments.duration_micros)?;
    let covariance_time = match spec.convention {
        CovarianceConventionV1::Increment => 1.0,
        CovarianceConventionV1::RatePerSecond => dt,
    };
    if !(2..=512).contains(&moments.sample_count) {
        return Err(CovarianceError::SampleCount);
    }
    if moments.mean_increment.len() != d
        || moments.mean_utility.len() != u
        || moments.covariance.len() != d
        || moments.cross_moment.len() != u
        || moments
            .covariance
            .iter()
            .chain(&moments.cross_moment)
            .any(|row| row.len() != d)
    {
        return Err(CovarianceError::Dimension);
    }
    let moment_bound = 4.0 * spec.maximum_absolute_sample.powi(2);
    for (values, bound) in [
        (&moments.mean_increment, spec.maximum_absolute_sample),
        (&moments.mean_utility, spec.maximum_absolute_sample),
    ] {
        for value in values {
            validate_value(*value, bound)?;
        }
    }
    for row in &moments.covariance {
        for value in row {
            validate_value(*value, moment_bound / covariance_time)?;
        }
    }
    for row in &moments.cross_moment {
        for value in row {
            validate_value(*value, moment_bound)?;
        }
    }
    let scale = (0..d).map(|i| moments.covariance[i][i]).fold(0.0, f64::max);
    if scale <= 0.0 {
        return Err(CovarianceError::NotPositiveDefinite);
    }
    let mut matrix = vec![vec![0.0; d]; d];
    for (i, row) in matrix.iter_mut().enumerate() {
        for (j, value) in row.iter_mut().enumerate() {
            let left = moments.covariance[i][j] / scale;
            let right = moments.covariance[j][i] / scale;
            if (left - right).abs() > 1e-12 {
                return Err(CovarianceError::AsymmetricCovariance);
            }
            *value = (left + right) / 2.0;
        }
    }
    let mut factor = vec![vec![0.0; d]; d];
    for i in 0..d {
        for j in 0..=i {
            let inner: f64 = (0..j).map(|k| factor[i][k] * factor[j][k]).sum();
            let remainder = matrix[i][j] - inner;
            if !remainder.is_finite() {
                return Err(CovarianceError::Arithmetic);
            }
            factor[i][j] = if i == j {
                if remainder <= 0.0 {
                    return Err(CovarianceError::NotPositiveDefinite);
                }
                remainder.sqrt()
            } else {
                remainder / factor[j][j]
            };
        }
    }
    let matrix_norm = matrix
        .iter()
        .map(|row| row.iter().map(|v| v.abs()).sum())
        .fold(0.0, f64::max);
    let mut inverse_norm: f64 = 0.0;
    // Column solves estimate the inverse 1-norm without forming an inverse.
    for column in 0..d {
        let mut unit = vec![0.0; d];
        unit[column] = 1.0;
        let solution = factor_solve(&factor, unit)?;
        inverse_norm = inverse_norm.max(solution.iter().map(|v| v.abs()).sum());
    }
    let condition_estimate = matrix_norm * inverse_norm;
    let eigenvalue_floor = scale * covariance_time / inverse_norm;
    if !condition_estimate.is_finite() || !eigenvalue_floor.is_finite() {
        return Err(CovarianceError::Arithmetic);
    }
    if condition_estimate > spec.maximum_condition {
        return Err(CovarianceError::IllConditioned);
    }
    if eigenvalue_floor < spec.minimum_increment_eigenvalue {
        return Err(CovarianceError::EigenvalueFloor);
    }
    let mut z = Vec::with_capacity(u);
    let mut maximum_relative_residual: f64 = 0.0;
    for cross in &moments.cross_moment {
        let rhs: Vec<f64> = cross
            .iter()
            .map(|value| value / covariance_time / scale)
            .collect();
        let solution = factor_solve(&factor, rhs.clone())?;
        if solution
            .iter()
            .any(|value| value.abs() > spec.maximum_absolute_z)
        {
            return Err(CovarianceError::CoefficientBound);
        }
        let mut residual: f64 = 0.0;
        for (j, expected) in rhs.iter().enumerate() {
            let prediction: f64 = solution
                .iter()
                .enumerate()
                .map(|(i, value)| value * (moments.covariance[i][j] / scale))
                .sum();
            residual = residual.max((prediction - expected).abs());
        }
        let z_norm = solution.iter().map(|value| value.abs()).fold(0.0, f64::max);
        let b_norm = rhs.iter().map(|value| value.abs()).fold(0.0, f64::max);
        let denominator = z_norm * matrix_norm + b_norm;
        let relative = if denominator == 0.0 {
            0.0
        } else {
            residual / denominator
        };
        if !relative.is_finite() {
            return Err(CovarianceError::Arithmetic);
        }
        maximum_relative_residual = maximum_relative_residual.max(relative);
        z.push(solution);
    }
    if maximum_relative_residual > spec.maximum_relative_residual {
        return Err(CovarianceError::Residual);
    }
    let mut bytes = b"hepta.ndu.backward-regression.native-f64.shadow.v1".to_vec();
    for digest in [
        profile.digest,
        moments.conditioning_digest,
        moments.source_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&moments.duration_micros.to_be_bytes());
    bytes.extend_from_slice(&(moments.sample_count as u64).to_be_bytes());
    for value in moments
        .mean_increment
        .iter()
        .chain(&moments.mean_utility)
        .chain(moments.covariance.iter().flatten())
        .chain(moments.cross_moment.iter().flatten())
        .chain(z.iter().flatten())
        .chain(
            [
                condition_estimate,
                eigenvalue_floor,
                maximum_relative_residual,
            ]
            .iter(),
        )
    {
        bytes.extend_from_slice(&value.to_bits().to_be_bytes());
    }
    Ok(ZEstimateV1 {
        z,
        condition_estimate,
        increment_eigenvalue_lower_estimate: eigenvalue_floor,
        maximum_relative_residual,
        evidence_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_value(value: f64, bound: f64) -> Result<(), CovarianceError> {
    if !value.is_finite() {
        return Err(CovarianceError::NonFinite);
    }
    if value.abs() > bound {
        return Err(CovarianceError::SampleBound);
    }
    Ok(())
}

fn factor_solve(factor: &[Vec<f64>], mut rhs: Vec<f64>) -> Result<Vec<f64>, CovarianceError> {
    for i in 0..rhs.len() {
        let inner: f64 = (0..i).map(|j| factor[i][j] * rhs[j]).sum();
        rhs[i] = (rhs[i] - inner) / factor[i][i];
    }
    for i in (0..rhs.len()).rev() {
        let inner: f64 = (i + 1..rhs.len()).map(|j| factor[j][i] * rhs[j]).sum();
        rhs[i] = (rhs[i] - inner) / factor[i][i];
    }
    if rhs.iter().any(|value| !value.is_finite()) {
        return Err(CovarianceError::Arithmetic);
    }
    Ok(rhs)
}

#[cfg(test)]
#[path = "covariance_tests.rs"]
mod tests;
