use std::error::Error;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::NumericProfileV1;

use crate::AdmittedCovarianceProfileV1;
use crate::ZEstimateV1;

const Q24_SCALE: f64 = (1_u64 << 24) as f64;
const MAX_Q24_REAL: f64 = i64::MAX as f64 / Q24_SCALE;

/// Owner-local admission surface for a registered NDU coefficient manifest.
///
/// The canonical external manifest remains owned by the contract registry. This
/// native profile binds the immutable manifest, normalization, runtime,
/// coordinate and covariance identities needed before the shadow Z estimate can
/// cross into a fixed-point candidate representation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduCoefficientProfileV1 {
    pub manifest_digest: Digest32,
    pub normalization_digest: Digest32,
    pub runtime_tuple_digest: Digest32,
    pub coordinate_digest: Digest32,
    pub covariance_profile_digest: Digest32,
    pub units_digest: Digest32,
    pub driver_dimension: usize,
    pub utility_dimension: usize,
    pub expires_unix_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmittedNduCoefficientProfileV1 {
    specification: NduCoefficientProfileV1,
    digest: Digest32,
}

impl AdmittedNduCoefficientProfileV1 {
    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.digest
    }

    #[must_use]
    pub const fn manifest_digest(&self) -> Digest32 {
        self.specification.manifest_digest
    }

    #[must_use]
    pub const fn coordinate_digest(&self) -> Digest32 {
        self.specification.coordinate_digest
    }

    #[must_use]
    pub const fn expires_unix_ms(&self) -> u64 {
        self.specification.expires_unix_ms
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct NduZQ24ProjectionV1 {
    values: Vec<Vec<i64>>,
    source_evidence_digest: Digest32,
    coefficient_profile_digest: Digest32,
    output_digest: Digest32,
    maximum_absolute_error: f64,
    conversion_evidence_digest: Digest32,
    authority: AuthorityPosture,
}

impl NduZQ24ProjectionV1 {
    #[must_use]
    pub fn values(&self) -> &[Vec<i64>] {
        &self.values
    }

    #[must_use]
    pub const fn source_evidence_digest(&self) -> Digest32 {
        self.source_evidence_digest
    }

    #[must_use]
    pub const fn coefficient_profile_digest(&self) -> Digest32 {
        self.coefficient_profile_digest
    }

    #[must_use]
    pub const fn output_digest(&self) -> Digest32 {
        self.output_digest
    }

    #[must_use]
    pub const fn maximum_absolute_error(&self) -> f64 {
        self.maximum_absolute_error
    }

    #[must_use]
    pub const fn conversion_evidence_digest(&self) -> Digest32 {
        self.conversion_evidence_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduCoefficientProfileError {
    MissingDigest,
    ProfileMismatch,
    Dimension,
    Expiry,
    ConversionRange,
    NonFinite,
    Authority,
}

impl fmt::Display for NduCoefficientProfileError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for NduCoefficientProfileError {}

/// Admits the numeric/semantic portion of a coefficient profile against the
/// already-admitted covariance profile. This is not artifact selection,
/// signature verification, external protocol registration or activation.
pub fn admit_ndu_coefficient_profile(
    specification: NduCoefficientProfileV1,
    covariance: &AdmittedCovarianceProfileV1,
) -> Result<AdmittedNduCoefficientProfileV1, NduCoefficientProfileError> {
    let digests = [
        specification.manifest_digest,
        specification.normalization_digest,
        specification.runtime_tuple_digest,
        specification.coordinate_digest,
        specification.covariance_profile_digest,
        specification.units_digest,
    ];
    if digests.iter().any(Digest32::is_zero) {
        return Err(NduCoefficientProfileError::MissingDigest);
    }
    if specification.covariance_profile_digest != covariance.digest
        || specification.units_digest != covariance.specification.units_digest
    {
        return Err(NduCoefficientProfileError::ProfileMismatch);
    }
    if specification.driver_dimension != covariance.specification.driver_dimension
        || specification.utility_dimension != covariance.specification.utility_dimension
    {
        return Err(NduCoefficientProfileError::Dimension);
    }
    if specification.expires_unix_ms == 0 {
        return Err(NduCoefficientProfileError::Expiry);
    }
    // An admitted Q24 projection must be representable without saturation.
    if covariance.specification.maximum_absolute_z > MAX_Q24_REAL {
        return Err(NduCoefficientProfileError::ConversionRange);
    }

    let mut bytes = b"hepta.ndu.coefficient-profile.native-q24.v1".to_vec();
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(specification.driver_dimension as u64).to_be_bytes());
    bytes.extend_from_slice(&(specification.utility_dimension as u64).to_be_bytes());
    bytes.extend_from_slice(&specification.expires_unix_ms.to_be_bytes());
    bytes.extend_from_slice(NumericProfileV1::SignedQ24NearestTiesEven.id().as_bytes());
    Ok(AdmittedNduCoefficientProfileV1 {
        specification,
        digest: Digest32::of_bytes(&bytes),
    })
}

/// Converts an already bounded native-f64 shadow Z estimate into signed Q24
/// using round-to-nearest ties-to-even and emits explicit conversion evidence.
///
/// Original-coordinate semantics are bound by the coefficient profile's
/// coordinate digest. No whitening transform is inferred here.
pub fn quantize_z_to_q24(
    estimate: &ZEstimateV1,
    profile: &AdmittedNduCoefficientProfileV1,
    now_unix_ms: u64,
) -> Result<NduZQ24ProjectionV1, NduCoefficientProfileError> {
    if estimate.authority().grants_any() {
        return Err(NduCoefficientProfileError::Authority);
    }
    if now_unix_ms >= profile.specification.expires_unix_ms {
        return Err(NduCoefficientProfileError::Expiry);
    }
    if estimate.evidence_digest().is_zero() {
        return Err(NduCoefficientProfileError::MissingDigest);
    }
    if estimate.covariance_profile_digest() != profile.specification.covariance_profile_digest {
        return Err(NduCoefficientProfileError::ProfileMismatch);
    }
    if estimate.z().len() != profile.specification.utility_dimension
        || estimate
            .z()
            .iter()
            .any(|row| row.len() != profile.specification.driver_dimension)
    {
        return Err(NduCoefficientProfileError::Dimension);
    }

    let mut values = Vec::with_capacity(estimate.z.len());
    let mut maximum_absolute_error = 0.0_f64;
    for row in estimate.z() {
        let mut converted = Vec::with_capacity(row.len());
        for value in row {
            if !value.is_finite() {
                return Err(NduCoefficientProfileError::NonFinite);
            }
            if value.abs() > MAX_Q24_REAL {
                return Err(NduCoefficientProfileError::ConversionRange);
            }
            let scaled = value * Q24_SCALE;
            if !scaled.is_finite() || scaled < i64::MIN as f64 || scaled > i64::MAX as f64 {
                return Err(NduCoefficientProfileError::ConversionRange);
            }
            let rounded = scaled.round_ties_even();
            let raw = i64::try_from(rounded as i128)
                .map_err(|_| NduCoefficientProfileError::ConversionRange)?;
            let reconstructed = raw as f64 / Q24_SCALE;
            maximum_absolute_error =
                maximum_absolute_error.max((reconstructed - value).abs());
            converted.push(raw);
        }
        values.push(converted);
    }

    let theoretical_bound = 0.5 / Q24_SCALE;
    if maximum_absolute_error > theoretical_bound * (1.0 + 8.0 * f64::EPSILON) {
        return Err(NduCoefficientProfileError::ConversionRange);
    }

    let mut output_bytes = b"hepta.ndu.z-q24.original-coordinates.v1".to_vec();
    output_bytes.extend_from_slice(profile.specification.units_digest.as_array());
    output_bytes.extend_from_slice(profile.specification.coordinate_digest.as_array());
    output_bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
    for row in &values {
        output_bytes.extend_from_slice(&(row.len() as u64).to_be_bytes());
        for value in row {
            output_bytes.extend_from_slice(&value.to_be_bytes());
        }
    }
    let output_digest = Digest32::of_bytes(&output_bytes);

    let mut evidence = b"hepta.ndu.z-q24-conversion-evidence.v1".to_vec();
    evidence.extend_from_slice(estimate.evidence_digest().as_array());
    evidence.extend_from_slice(profile.digest.as_array());
    evidence.extend_from_slice(output_digest.as_array());
    evidence.extend_from_slice(&maximum_absolute_error.to_bits().to_be_bytes());
    evidence.extend_from_slice(&theoretical_bound.to_bits().to_be_bytes());

    Ok(NduZQ24ProjectionV1 {
        values,
        source_evidence_digest: estimate.evidence_digest(),
        coefficient_profile_digest: profile.digest,
        output_digest,
        maximum_absolute_error,
        conversion_evidence_digest: Digest32::of_bytes(&evidence),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "coefficient_profile_tests.rs"]
mod tests;
