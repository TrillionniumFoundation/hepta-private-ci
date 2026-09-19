//! Native admission for the canonical NduCoefficientManifestV1 semantics.
//!
//! The canonical wire contract remains docs/contracts/PROTOCOL_SCHEMAS.json.
//! Bounded-object fields are represented here by their canonical object digest
//! and encoded byte count so this crate does not invent unregistered V1 fields.
//! The separately registered covariance-profile reference is bound by the
//! admission receipt rather than being smuggled into the manifest.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AdmittedCovarianceProfileV1;
use crate::SubjectClass;

const MAX_PREFERENCE_DIMENSIONS: u16 = 64;
const MAX_UTILITY_DIMENSIONS: u16 = 8;
const MAX_DRIVER_DIMENSIONS: u16 = 32;
const MAX_DIMENSIONS_OBJECT_BYTES: u32 = 4_096;
const MAX_SCALES_OBJECT_BYTES: u32 = 4_096;
const MAX_COEFFICIENT_BOUNDS_BYTES: u32 = 16_384;
const MAX_LIPSCHITZ_BOUNDS_BYTES: u32 = 16_384;
const MAX_MONOTONICITY_BOUNDS_BYTES: u32 = 8_192;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NduCoefficientDimensionsV1 {
    pub preference: u16,
    pub utility: u16,
    pub driver: u16,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NduFixedPointScalesV1 {
    pub preference_fractional_bits: u8,
    pub utility_fractional_bits: u8,
    pub coefficient_fractional_bits: u8,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NduBoundedObjectRefV1 {
    pub canonical_digest: Digest32,
    pub encoded_bytes: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduCoefficientManifestV1 {
    pub artifact_id: StableId,
    pub subject_class: SubjectClass,
    pub objective_class_digest: Digest32,
    pub dimensions: NduCoefficientDimensionsV1,
    pub dimensions_encoded_bytes: u32,
    pub fixed_point_scales: NduFixedPointScalesV1,
    pub fixed_point_scales_encoded_bytes: u32,
    pub coefficient_bounds: NduBoundedObjectRefV1,
    pub lipschitz_bounds: NduBoundedObjectRefV1,
    pub monotonicity_bounds: NduBoundedObjectRefV1,
    pub normalization_digest: Digest32,
    pub runtime_tuple_digest: Digest32,
    pub predecessor_artifact_id: Option<StableId>,
    pub expires_unix_ms: u64,
    pub rollback_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmittedNduCoefficientManifestV1 {
    pub manifest: NduCoefficientManifestV1,
    pub manifest_digest: Digest32,
    pub covariance_profile_digest: Digest32,
    pub admission_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl AdmittedNduCoefficientManifestV1 {
    #[must_use]
    pub const fn manifest_digest(&self) -> Digest32 {
        self.manifest_digest
    }

    #[must_use]
    pub const fn covariance_profile_digest(&self) -> Digest32 {
        self.covariance_profile_digest
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduCoefficientManifestError {
    MissingDigest(&'static str),
    InvalidDimensions,
    InvalidFixedPointScale,
    BoundedObjectSize(&'static str),
    Expired,
    CovarianceDimensionMismatch,
}

impl fmt::Display for NduCoefficientManifestError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduCoefficientManifestError {}

pub fn admit_coefficient_manifest_v1(
    manifest: NduCoefficientManifestV1,
    covariance_profile: &AdmittedCovarianceProfileV1,
    now_unix_ms: u64,
) -> Result<AdmittedNduCoefficientManifestV1, NduCoefficientManifestError> {
    require_digest(manifest.objective_class_digest, "objective class")?;
    require_digest(manifest.normalization_digest, "normalization")?;
    require_digest(manifest.runtime_tuple_digest, "runtime tuple")?;
    require_digest(manifest.rollback_digest, "rollback")?;

    let dimensions = manifest.dimensions;
    if !(1..=MAX_PREFERENCE_DIMENSIONS).contains(&dimensions.preference)
        || !(1..=MAX_UTILITY_DIMENSIONS).contains(&dimensions.utility)
        || !(1..=MAX_DRIVER_DIMENSIONS).contains(&dimensions.driver)
    {
        return Err(NduCoefficientManifestError::InvalidDimensions);
    }
    if manifest.dimensions_encoded_bytes == 0
        || manifest.dimensions_encoded_bytes > MAX_DIMENSIONS_OBJECT_BYTES
    {
        return Err(NduCoefficientManifestError::BoundedObjectSize("dimensions"));
    }

    if manifest.fixed_point_scales
        != (NduFixedPointScalesV1 {
            preference_fractional_bits: 32,
            utility_fractional_bits: 32,
            coefficient_fractional_bits: 24,
        })
    {
        return Err(NduCoefficientManifestError::InvalidFixedPointScale);
    }
    if manifest.fixed_point_scales_encoded_bytes == 0
        || manifest.fixed_point_scales_encoded_bytes > MAX_SCALES_OBJECT_BYTES
    {
        return Err(NduCoefficientManifestError::BoundedObjectSize(
            "fixed point scales",
        ));
    }

    validate_object(
        manifest.coefficient_bounds,
        MAX_COEFFICIENT_BOUNDS_BYTES,
        "coefficient bounds",
    )?;
    validate_object(
        manifest.lipschitz_bounds,
        MAX_LIPSCHITZ_BOUNDS_BYTES,
        "lipschitz bounds",
    )?;
    validate_object(
        manifest.monotonicity_bounds,
        MAX_MONOTONICITY_BOUNDS_BYTES,
        "monotonicity bounds",
    )?;

    if now_unix_ms > manifest.expires_unix_ms {
        return Err(NduCoefficientManifestError::Expired);
    }
    if usize::from(dimensions.utility) != covariance_profile.specification.utility_dimension
        || usize::from(dimensions.driver) != covariance_profile.specification.driver_dimension
    {
        return Err(NduCoefficientManifestError::CovarianceDimensionMismatch);
    }

    let manifest_digest = digest_manifest(&manifest);
    let covariance_profile_digest = covariance_profile.digest();
    let mut admission = b"hepta.ndu.coefficient-manifest-admission.v1".to_vec();
    admission.extend_from_slice(manifest_digest.as_array());
    admission.extend_from_slice(covariance_profile_digest.as_array());
    let admission_digest = Digest32::of_bytes(&admission);

    Ok(AdmittedNduCoefficientManifestV1 {
        manifest,
        manifest_digest,
        covariance_profile_digest,
        admission_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_object(
    object: NduBoundedObjectRefV1,
    maximum: u32,
    field: &'static str,
) -> Result<(), NduCoefficientManifestError> {
    require_digest(object.canonical_digest, field)?;
    if object.encoded_bytes == 0 || object.encoded_bytes > maximum {
        return Err(NduCoefficientManifestError::BoundedObjectSize(field));
    }
    Ok(())
}

fn require_digest(
    digest: Digest32,
    field: &'static str,
) -> Result<(), NduCoefficientManifestError> {
    if digest.is_zero() {
        Err(NduCoefficientManifestError::MissingDigest(field))
    } else {
        Ok(())
    }
}

fn digest_manifest(manifest: &NduCoefficientManifestV1) -> Digest32 {
    let mut bytes = b"hepta.ndu.coefficient-manifest.native.v1".to_vec();
    push_id(&mut bytes, &manifest.artifact_id);
    bytes.push(subject_class_tag(manifest.subject_class));
    bytes.extend_from_slice(manifest.objective_class_digest.as_array());
    bytes.extend_from_slice(&manifest.dimensions.preference.to_be_bytes());
    bytes.extend_from_slice(&manifest.dimensions.utility.to_be_bytes());
    bytes.extend_from_slice(&manifest.dimensions.driver.to_be_bytes());
    bytes.extend_from_slice(&manifest.dimensions_encoded_bytes.to_be_bytes());
    bytes.push(manifest.fixed_point_scales.preference_fractional_bits);
    bytes.push(manifest.fixed_point_scales.utility_fractional_bits);
    bytes.push(manifest.fixed_point_scales.coefficient_fractional_bits);
    bytes.extend_from_slice(&manifest.fixed_point_scales_encoded_bytes.to_be_bytes());
    for object in [
        manifest.coefficient_bounds,
        manifest.lipschitz_bounds,
        manifest.monotonicity_bounds,
    ] {
        bytes.extend_from_slice(object.canonical_digest.as_array());
        bytes.extend_from_slice(&object.encoded_bytes.to_be_bytes());
    }
    bytes.extend_from_slice(manifest.normalization_digest.as_array());
    bytes.extend_from_slice(manifest.runtime_tuple_digest.as_array());
    match manifest.predecessor_artifact_id.as_ref() {
        Some(predecessor) => {
            bytes.push(1);
            push_id(&mut bytes, predecessor);
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&manifest.expires_unix_ms.to_be_bytes());
    bytes.extend_from_slice(manifest.rollback_digest.as_array());
    Digest32::of_bytes(&bytes)
}

const fn subject_class_tag(value: SubjectClass) -> u8 {
    match value {
        SubjectClass::System => 0,
        SubjectClass::Domain => 1,
        SubjectClass::Agent => 2,
        SubjectClass::Episode => 3,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "coefficient_manifest_tests.rs"]
mod tests;
