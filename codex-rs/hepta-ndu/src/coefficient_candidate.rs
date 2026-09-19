//! Q24 coefficient materialization for the native stochastic shadow candidate.
//!
//! This converts a crate-sealed covariance solve into a bounded fixed-point
//! candidate with explicit profile/manifest/region provenance. It is numerical
//! admission evidence only and never selects or activates a model.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::AdmittedCovarianceProfileV1;
use crate::AdmittedNduCoefficientManifestV1;
use crate::CovarianceError;
use crate::ZEstimateV1;

const Q24_SCALE: f64 = 16_777_216.0;
const I64_MAX_EXCLUSIVE_F64: f64 = 9_223_372_036_854_775_808.0;
const I64_MIN_INCLUSIVE_F64: f64 = -9_223_372_036_854_775_808.0;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduQ24CoefficientCandidateV1 {
    pub coefficient_manifest_digest: Digest32,
    pub coefficient_admission_digest: Digest32,
    pub operating_region_digest: Digest32,
    pub profile_digest: Digest32,
    pub source_estimate_digest: Digest32,
    pub units_digest: Digest32,
    pub utility_dimension: usize,
    pub driver_dimension: usize,
    /// Row-major utility x driver coefficients in signed Q24.
    pub coefficients_raw: Vec<i64>,
    /// Conservative nearest/ties-even bound: at most 1 / 2^25 in source units.
    pub maximum_absolute_conversion_error_numerator: u64,
    pub maximum_absolute_conversion_error_denominator: u64,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Convert a solver-produced native f64 shadow estimate into an immutable Q24
/// coefficient candidate. Profile identity, dimensions, units, manifest and
/// operating region are revalidated and digest-bound.
pub fn materialize_q24_coefficient_candidate_v1(
    estimate: &ZEstimateV1,
    profile: &AdmittedCovarianceProfileV1,
    coefficient_manifest: &AdmittedNduCoefficientManifestV1,
    operating_region_digest: Digest32,
) -> Result<NduQ24CoefficientCandidateV1, CovarianceError> {
    if operating_region_digest.is_zero() {
        return Err(CovarianceError::MissingDigest);
    }
    if estimate.profile_digest() != profile.digest() {
        return Err(CovarianceError::EstimateMismatch);
    }
    if coefficient_manifest.covariance_profile_digest() != profile.digest() {
        return Err(CovarianceError::ManifestMismatch);
    }
    if estimate.evidence_digest.is_zero() {
        return Err(CovarianceError::MissingDigest);
    }

    let spec = &profile.specification;
    if estimate.z.len() != spec.utility_dimension
        || estimate
            .z
            .iter()
            .any(|row| row.len() != spec.driver_dimension)
    {
        return Err(CovarianceError::Dimension);
    }

    let mut coefficients_raw = Vec::with_capacity(spec.utility_dimension * spec.driver_dimension);
    for value in estimate.z.iter().flatten() {
        if !value.is_finite() {
            return Err(CovarianceError::NonFinite);
        }
        if value.abs() > spec.maximum_absolute_z {
            return Err(CovarianceError::CoefficientBound);
        }
        coefficients_raw.push(quantize_q24_ties_even(*value)?);
    }

    let coefficient_manifest_digest = coefficient_manifest.manifest_digest();
    let coefficient_admission_digest = coefficient_manifest.admission_digest;
    let mut bytes = b"hepta.ndu.q24-coefficient-candidate.v2".to_vec();
    for digest in [
        coefficient_manifest_digest,
        coefficient_admission_digest,
        operating_region_digest,
        profile.digest(),
        estimate.evidence_digest,
        spec.units_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(spec.utility_dimension as u64).to_be_bytes());
    bytes.extend_from_slice(&(spec.driver_dimension as u64).to_be_bytes());
    for value in estimate.z.iter().flatten() {
        bytes.extend_from_slice(&value.to_bits().to_be_bytes());
    }
    for value in &coefficients_raw {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(&1_u64.to_be_bytes());
    bytes.extend_from_slice(&(1_u64 << 25).to_be_bytes());

    Ok(NduQ24CoefficientCandidateV1 {
        coefficient_manifest_digest,
        coefficient_admission_digest,
        operating_region_digest,
        profile_digest: profile.digest(),
        source_estimate_digest: estimate.evidence_digest,
        units_digest: spec.units_digest,
        utility_dimension: spec.utility_dimension,
        driver_dimension: spec.driver_dimension,
        coefficients_raw,
        maximum_absolute_conversion_error_numerator: 1,
        maximum_absolute_conversion_error_denominator: 1_u64 << 25,
        evidence_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn quantize_q24_ties_even(value: f64) -> Result<i64, CovarianceError> {
    let scaled = value * Q24_SCALE;
    if !scaled.is_finite() || !(I64_MIN_INCLUSIVE_F64..I64_MAX_EXCLUSIVE_F64).contains(&scaled) {
        return Err(CovarianceError::QuantizationRange);
    }

    let lower = scaled.floor();
    let fraction = scaled - lower;
    let lower_raw = lower as i64;
    let rounded = if fraction < 0.5 {
        lower_raw
    } else if fraction > 0.5 {
        lower_raw
            .checked_add(1)
            .ok_or(CovarianceError::QuantizationRange)?
    } else if lower_raw % 2 == 0 {
        lower_raw
    } else {
        lower_raw
            .checked_add(1)
            .ok_or(CovarianceError::QuantizationRange)?
    };
    Ok(rounded)
}

#[cfg(test)]
#[path = "coefficient_candidate_tests.rs"]
mod tests;
