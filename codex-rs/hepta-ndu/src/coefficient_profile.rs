use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::AdmittedCovarianceProfileV1;
use crate::AdmittedZConversionProfileV1;
use crate::ZEstimateV1;
use crate::convert_z_to_original_q24;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduCoefficientProfileV1 {
    pub artifact_manifest_digest: Digest32,
    pub normalization_digest: Digest32,
    pub runtime_tuple_digest: Digest32,
    pub covariance_profile_digest: Digest32,
    pub z_conversion_profile_digest: Digest32,
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
    pub const fn artifact_manifest_digest(&self) -> Digest32 {
        self.specification.artifact_manifest_digest
    }

    #[must_use]
    pub const fn normalization_digest(&self) -> Digest32 {
        self.specification.normalization_digest
    }

    #[must_use]
    pub const fn runtime_tuple_digest(&self) -> Digest32 {
        self.specification.runtime_tuple_digest
    }

    #[must_use]
    pub const fn covariance_profile_digest(&self) -> Digest32 {
        self.specification.covariance_profile_digest
    }

    #[must_use]
    pub const fn z_conversion_profile_digest(&self) -> Digest32 {
        self.specification.z_conversion_profile_digest
    }

    #[must_use]
    pub const fn units_digest(&self) -> Digest32 {
        self.specification.units_digest
    }

    #[must_use]
    pub const fn driver_dimension(&self) -> usize {
        self.specification.driver_dimension
    }

    #[must_use]
    pub const fn utility_dimension(&self) -> usize {
        self.specification.utility_dimension
    }

    #[must_use]
    pub const fn expires_unix_ms(&self) -> u64 {
        self.specification.expires_unix_ms
    }
}

#[derive(Clone, Debug, PartialEq)]
pub struct NduCoefficientProjectionV1 {
    pub q24_raw: Vec<Vec<i64>>,
    pub source_evidence_digest: Digest32,
    pub coefficient_profile_digest: Digest32,
    pub conversion_receipt_digest: Digest32,
    pub output_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduCoefficientProfileError {
    MissingDigest,
    ProfileMismatch,
    Dimension,
    Expiry,
    Authority,
}

impl fmt::Display for NduCoefficientProfileError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduCoefficientProfileError {}

/// Admits the semantic/numeric coefficient profile only. The artifact manifest
/// digest is verified against learning.artifacts by the product consumer; this
/// crate cannot self-authenticate artifact provenance or select an artifact.
pub fn admit_ndu_coefficient_profile(
    specification: NduCoefficientProfileV1,
    covariance: &AdmittedCovarianceProfileV1,
    z_conversion: &AdmittedZConversionProfileV1,
) -> Result<AdmittedNduCoefficientProfileV1, NduCoefficientProfileError> {
    let digests = [
        specification.artifact_manifest_digest,
        specification.normalization_digest,
        specification.runtime_tuple_digest,
        specification.covariance_profile_digest,
        specification.z_conversion_profile_digest,
        specification.units_digest,
    ];
    if digests.iter().any(|digest| digest.is_zero()) {
        return Err(NduCoefficientProfileError::MissingDigest);
    }
    if specification.covariance_profile_digest != covariance.digest
        || specification.z_conversion_profile_digest != z_conversion.digest
        || specification.units_digest != covariance.specification.units_digest
        || specification.units_digest != z_conversion.specification.units_digest
    {
        return Err(NduCoefficientProfileError::ProfileMismatch);
    }
    if specification.driver_dimension != covariance.specification.driver_dimension
        || specification.utility_dimension != covariance.specification.utility_dimension
        || specification.driver_dimension != z_conversion.specification.driver_dimension
        || specification.utility_dimension != z_conversion.specification.utility_dimension
    {
        return Err(NduCoefficientProfileError::Dimension);
    }
    if specification.expires_unix_ms == 0 {
        return Err(NduCoefficientProfileError::Expiry);
    }

    let mut bytes = b"hepta.ndu.coefficient-profile.v2\0".to_vec();
    for digest in digests {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&(specification.driver_dimension as u64).to_be_bytes());
    bytes.extend_from_slice(&(specification.utility_dimension as u64).to_be_bytes());
    bytes.extend_from_slice(&specification.expires_unix_ms.to_be_bytes());
    Ok(AdmittedNduCoefficientProfileV1 {
        specification,
        digest: Digest32::of_bytes(&bytes),
    })
}

/// Converts only a Z estimate from the exact covariance profile bound into the
/// admitted coefficient profile. Coordinate conversion and Q24 rounding are
/// delegated to the separately admitted Z conversion profile.
pub fn project_z_estimate_to_coefficient_q24(
    estimate: &ZEstimateV1,
    profile: &AdmittedNduCoefficientProfileV1,
    z_conversion: &AdmittedZConversionProfileV1,
    now_unix_ms: u64,
) -> Result<NduCoefficientProjectionV1, NduCoefficientProfileError> {
    if now_unix_ms >= profile.specification.expires_unix_ms {
        return Err(NduCoefficientProfileError::Expiry);
    }
    if estimate.authority.grants_any() {
        return Err(NduCoefficientProfileError::Authority);
    }
    if estimate.evidence_digest.is_zero() {
        return Err(NduCoefficientProfileError::MissingDigest);
    }
    if estimate.covariance_profile_digest != profile.specification.covariance_profile_digest
        || z_conversion.digest != profile.specification.z_conversion_profile_digest
        || z_conversion.specification.units_digest != profile.specification.units_digest
    {
        return Err(NduCoefficientProfileError::ProfileMismatch);
    }
    if estimate.z.len() != profile.specification.utility_dimension
        || estimate
            .z
            .iter()
            .any(|row| row.len() != profile.specification.driver_dimension)
    {
        return Err(NduCoefficientProfileError::Dimension);
    }

    let conversion = convert_z_to_original_q24(&estimate.z, estimate.evidence_digest, z_conversion)
        .map_err(|_| NduCoefficientProfileError::ProfileMismatch)?;
    if conversion.authority.grants_any()
        || conversion.profile_digest != profile.specification.z_conversion_profile_digest
    {
        return Err(NduCoefficientProfileError::Authority);
    }

    let mut bytes = b"hepta.ndu.coefficient-q24-projection.v1\0".to_vec();
    bytes.extend_from_slice(profile.digest.as_array());
    bytes.extend_from_slice(estimate.covariance_profile_digest.as_array());
    bytes.extend_from_slice(estimate.evidence_digest.as_array());
    bytes.extend_from_slice(conversion.receipt_digest.as_array());
    for raw in conversion.q24_raw.iter().flatten() {
        bytes.extend_from_slice(&raw.to_be_bytes());
    }
    let output_digest = Digest32::of_bytes(&bytes);

    Ok(NduCoefficientProjectionV1 {
        q24_raw: conversion.q24_raw,
        source_evidence_digest: estimate.evidence_digest,
        coefficient_profile_digest: profile.digest,
        conversion_receipt_digest: conversion.receipt_digest,
        output_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "coefficient_profile_tests.rs"]
mod tests;
