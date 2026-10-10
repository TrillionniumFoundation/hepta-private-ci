use super::*;
use crate::ConditionalMomentSampleV1;
use crate::NduCovarianceProfileV1;
use crate::admit_covariance_profile;
use crate::estimate_conditional_moments;
use pretty_assertions::assert_eq;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn profile(dimension: usize, convention: CovarianceConventionV1) -> AdmittedCovarianceProfileV1 {
    checked(admit_covariance_profile(NduCovarianceProfileV1 {
        units_digest: Digest32::of_bytes(b"driver-units-and-order"),
        driver_dimension: dimension,
        utility_dimension: 1,
        convention,
        minimum_increment_eigenvalue: 1e-12,
        maximum_condition: 1e6,
        maximum_absolute_sample: 1e6,
        maximum_absolute_z: 1e6,
        maximum_relative_residual: 1e-10,
    }))
}

fn sample(increment: Vec<f64>, utility: f64) -> ConditionalMomentSampleV1 {
    ConditionalMomentSampleV1 {
        conditioning_digest: Digest32::of_bytes(b"pre-boundary-stratum"),
        duration_micros: 1_000_000,
        increment,
        utility: vec![utility],
    }
}

fn estimate(
    samples: &[ConditionalMomentSampleV1],
    p: &AdmittedCovarianceProfileV1,
) -> ConditionalMomentsV1 {
    checked(estimate_conditional_moments(
        samples,
        Digest32::of_bytes(b"immutable-training-fold"),
        p,
    ))
}

fn close(actual: &[Vec<f64>], expected: &[Vec<f64>]) {
    assert_eq!(actual.len(), expected.len());
    for (actual, expected) in actual.iter().zip(expected) {
        assert_eq!(actual.len(), expected.len());
        for (actual, expected) in actual.iter().zip(expected) {
            assert!(
                (actual - expected).abs() < 1e-10,
                "actual {actual}, expected {expected}"
            );
        }
    }
}

fn correlated_samples() -> Vec<ConditionalMomentSampleV1> {
    let mut samples = Vec::new();
    for a in [-1.0, 1.0] {
        for b in [-1.0, 1.0] {
            for c in [-1.0, 1.0] {
                let x = a + b;
                let y = a + c;
                samples.push(sample(vec![x + 10.0, y + 20.0], 3.0 * x - y + 7.0));
            }
        }
    }
    samples
}

#[test]
fn scaled_covariance_recovers_three_instead_of_six_and_converts_microseconds() {
    for convention in [
        CovarianceConventionV1::Increment,
        CovarianceConventionV1::RatePerSecond,
    ] {
        let p = profile(/*dimension*/ 1, convention);
        for duration_micros in [250_000, 1_000_000] {
            let amplitude = if duration_micros == 250_000 { 1.0 } else { 2.0 };
            let samples: Vec<_> = [-amplitude, 0.0, 0.0, amplitude]
                .into_iter()
                .map(|m| {
                    let mut row = sample(vec![m], 3.0 * m);
                    row.duration_micros = duration_micros;
                    row
                })
                .collect();
            let moments = estimate(&samples, &p);
            let receipt = checked(solve_backward_regression(&moments, &p));
            close(&receipt.z, &[vec![3.0]]);
            assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
            let expected = match convention {
                CovarianceConventionV1::Increment => 2.0 * duration_micros as f64 / 1e6,
                CovarianceConventionV1::RatePerSecond => 2.0,
            };
            close(&moments.covariance, &[vec![expected]]);
        }
    }
}

#[test]
fn centers_both_terms_and_recovers_correlated_goldens() {
    let p = profile(/*dimension*/ 2, CovarianceConventionV1::Increment);
    let samples = correlated_samples();
    let original = samples.clone();
    let moments = estimate(&samples, &p);
    close(
        std::slice::from_ref(&moments.mean_increment),
        &[vec![10.0, 20.0]],
    );
    close(std::slice::from_ref(&moments.mean_utility), &[vec![7.0]]);
    close(&moments.covariance, &[vec![2.0, 1.0], vec![1.0, 2.0]]);
    close(&moments.cross_moment, &[vec![5.0, 1.0]]);
    let receipt = checked(solve_backward_regression(&moments, &p));
    close(&receipt.z, &[vec![3.0, -1.0]]);
    assert_eq!(samples, original);
    assert_eq!(solve_backward_regression(&moments, &p), Ok(receipt));
}

#[test]
fn identity_covariance_reduces_to_cross_moment_over_dt() {
    let p = profile(/*dimension*/ 2, CovarianceConventionV1::Increment);
    let mut samples = Vec::new();
    for x in [-0.5, 0.5] {
        for y in [-0.5, 0.5] {
            let mut row = sample(vec![x, y], 2.0 * x - 4.0 * y);
            row.duration_micros = 250_000;
            samples.push(row);
        }
    }
    let moments = estimate(&samples, &p);
    close(&moments.cross_moment, &[vec![0.5, -1.0]]);
    close(
        &checked(solve_backward_regression(&moments, &p)).z,
        &[vec![2.0, -4.0]],
    );
}

#[test]
fn zero_cross_moment_returns_zero_sensitivity() {
    let p = profile(/*dimension*/ 2, CovarianceConventionV1::Increment);
    let mut samples = correlated_samples();
    for row in &mut samples {
        row.utility = vec![12.0];
    }
    let moments = estimate(&samples, &p);
    close(
        &checked(solve_backward_regression(&moments, &p)).z,
        &[vec![0.0, 0.0]],
    );
}

#[test]
fn rejects_singular_indefinite_ill_conditioned_and_collapsed_covariance() {
    let p = profile(/*dimension*/ 2, CovarianceConventionV1::Increment);
    let original = estimate(&correlated_samples(), &p);
    for (covariance, error) in [
        (
            vec![vec![1.0, 1.0], vec![1.0, 1.0]],
            CovarianceError::NotPositiveDefinite,
        ),
        (
            vec![vec![1.0, 2.0], vec![2.0, 1.0]],
            CovarianceError::NotPositiveDefinite,
        ),
        (
            vec![vec![1.0, 0.0], vec![0.0, 1e-7]],
            CovarianceError::IllConditioned,
        ),
        (
            vec![vec![1e-14, 0.0], vec![0.0, 1e-14]],
            CovarianceError::EigenvalueFloor,
        ),
        (
            vec![vec![1.0, 0.0], vec![0.5, 1.0]],
            CovarianceError::AsymmetricCovariance,
        ),
    ] {
        let mut moments = original.clone();
        moments.covariance = covariance;
        assert_eq!(solve_backward_regression(&moments, &p), Err(error));
    }
}

#[test]
fn sample_preflight_rejects_nonfinite_shape_overflow_and_mixed_conditioning() {
    let p = profile(/*dimension*/ 2, CovarianceConventionV1::Increment);
    let original = correlated_samples();
    for value in [f64::NAN, f64::INFINITY, f64::NEG_INFINITY, 1e7] {
        let mut samples = original.clone();
        samples[0].increment[0] = value;
        let error = if value.is_finite() {
            CovarianceError::SampleBound
        } else {
            CovarianceError::NonFinite
        };
        assert_eq!(
            estimate_conditional_moments(&samples, Digest32::of_bytes(b"source"), &p),
            Err(error)
        );
    }
    for case in 0..3 {
        let mut samples = original.clone();
        let error = match case {
            0 => {
                samples[0].utility.clear();
                CovarianceError::Dimension
            }
            1 => {
                samples[0].duration_micros = 999;
                CovarianceError::Duration
            }
            _ => {
                samples[0].conditioning_digest = Digest32::of_bytes(b"future-stratum");
                CovarianceError::ConditioningMismatch
            }
        };
        assert_eq!(
            estimate_conditional_moments(&samples, Digest32::of_bytes(b"source"), &p),
            Err(error)
        );
    }
    for samples in [Vec::new(), vec![original[0].clone(); 513]] {
        assert_eq!(
            estimate_conditional_moments(&samples, Digest32::of_bytes(b"source"), &p),
            Err(CovarianceError::SampleCount)
        );
    }
}

#[test]
fn admission_binds_units_convention_and_bounds_without_silent_migration() {
    let p = profile(/*dimension*/ 2, CovarianceConventionV1::Increment);
    let moments = estimate(&correlated_samples(), &p);
    let rate = profile(/*dimension*/ 2, CovarianceConventionV1::RatePerSecond);
    assert_eq!(
        solve_backward_regression(&moments, &rate),
        Err(CovarianceError::ProfileMismatch)
    );
    for case in 0..5 {
        let mut spec = p.specification.clone();
        match case {
            0 => spec.maximum_condition = 1e6 + 1.0,
            1 => spec.minimum_increment_eigenvalue = 0.0,
            2 => spec.maximum_absolute_sample = f64::INFINITY,
            3 => spec.driver_dimension = 33,
            _ => spec.units_digest = Digest32::ZERO,
        }
        assert_eq!(
            admit_covariance_profile(spec),
            Err(CovarianceError::InvalidProfile)
        );
    }
    let mut spec = p.specification;
    spec.units_digest = Digest32::of_bytes(b"different-units");
    let other = checked(admit_covariance_profile(spec));
    assert_eq!(
        solve_backward_regression(&moments, &other),
        Err(CovarianceError::ProfileMismatch)
    );
}

#[test]
fn external_moments_are_revalidated_and_actual_values_are_digest_bound() {
    let p = profile(/*dimension*/ 2, CovarianceConventionV1::Increment);
    let original = estimate(&correlated_samples(), &p);
    let receipt = checked(solve_backward_regression(&original, &p));
    let mut changed = original.clone();
    changed.cross_moment[0][0] += 1.0;
    assert_ne!(
        checked(solve_backward_regression(&changed, &p)).evidence_digest,
        receipt.evidence_digest
    );
    changed = original.clone();
    changed.cross_moment[0][0] = f64::NAN;
    assert_eq!(
        solve_backward_regression(&changed, &p),
        Err(CovarianceError::NonFinite)
    );
    changed = original.clone();
    changed.covariance[0].clear();
    assert_eq!(
        solve_backward_regression(&changed, &p),
        Err(CovarianceError::Dimension)
    );
    changed = original;
    changed.cross_moment[0][0] = 1e12;
    assert_eq!(
        solve_backward_regression(&changed, &p),
        Err(CovarianceError::CoefficientBound)
    );
}

#[test]
fn full_pilot_dimensions_solve_multiple_utilities() {
    let mut spec = profile(/*dimension*/ 32, CovarianceConventionV1::Increment).specification;
    spec.utility_dimension = 8;
    let p = checked(admit_covariance_profile(spec));
    let mut samples = Vec::new();
    for index in 0..32 {
        for sign in [-1.0, 1.0] {
            let mut increment = vec![0.0; 32];
            increment[index] = sign;
            let mut row = sample(increment, /*utility*/ 0.0);
            row.utility = row.increment[..8].to_vec();
            samples.push(row);
        }
    }
    let moments = estimate(&samples, &p);
    let mut expected = vec![vec![0.0; 32]; 8];
    for (i, row) in expected.iter_mut().enumerate() {
        row[i] = 1.0;
    }
    close(
        &checked(solve_backward_regression(&moments, &p)).z,
        &expected,
    );
}
