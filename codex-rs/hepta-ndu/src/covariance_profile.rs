use std::error::Error;
use std::fmt;

use codex_hepta_types::Digest32;

/// Native f64 shadow convention; never reinterprets a production wire profile.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CovarianceConventionV1 {
    Increment,
    RatePerSecond,
}

/// Numerical admission is separate from artifact approval and runtime selection.
/// All drivers use their original coordinates; whitening is not admitted by V1.
#[derive(Clone, Debug, PartialEq)]
pub struct NduCovarianceProfileV1 {
    pub units_digest: Digest32,
    pub driver_dimension: usize,
    pub utility_dimension: usize,
    pub convention: CovarianceConventionV1,
    /// Floor always uses increment covariance units, including for rate storage.
    pub minimum_increment_eigenvalue: f64,
    pub maximum_condition: f64,
    pub maximum_absolute_sample: f64,
    pub maximum_absolute_z: f64,
    pub maximum_relative_residual: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct AdmittedCovarianceProfileV1 {
    pub(crate) specification: NduCovarianceProfileV1,
    pub(crate) digest: Digest32,
}

impl AdmittedCovarianceProfileV1 {
    pub fn digest(&self) -> Digest32 {
        self.digest
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CovarianceError {
    InvalidProfile,
    MissingDigest,
    ProfileMismatch,
    ConditioningMismatch,
    Duration,
    SampleCount,
    Dimension,
    NonFinite,
    SampleBound,
    AsymmetricCovariance,
    NotPositiveDefinite,
    EigenvalueFloor,
    IllConditioned,
    CoefficientBound,
    Residual,
    Arithmetic,
}

impl fmt::Display for CovarianceError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for CovarianceError {}

/// Admits only a bounded numerical profile, not its provenance or deployment.
pub fn admit_covariance_profile(
    specification: NduCovarianceProfileV1,
) -> Result<AdmittedCovarianceProfileV1, CovarianceError> {
    let numeric = [
        specification.minimum_increment_eigenvalue,
        specification.maximum_condition,
        specification.maximum_absolute_sample,
        specification.maximum_absolute_z,
        specification.maximum_relative_residual,
    ];
    if specification.units_digest.is_zero()
        || !(1..=32).contains(&specification.driver_dimension)
        || !(1..=8).contains(&specification.utility_dimension)
        || numeric
            .iter()
            .any(|value| !value.is_finite() || *value <= 0.0)
        || !(1.0..=1e6).contains(&specification.maximum_condition)
        || specification.maximum_absolute_sample > 1e12
        || specification.maximum_absolute_z > 1e12
        || specification.maximum_relative_residual > 1e-8
    {
        return Err(CovarianceError::InvalidProfile);
    }
    let mut bytes = b"hepta.ndu.covariance.native-f64.shadow.v1".to_vec();
    bytes.extend_from_slice(specification.units_digest.as_array());
    bytes.extend_from_slice(&(specification.driver_dimension as u64).to_be_bytes());
    bytes.extend_from_slice(&(specification.utility_dimension as u64).to_be_bytes());
    bytes.push(match specification.convention {
        CovarianceConventionV1::Increment => 0,
        CovarianceConventionV1::RatePerSecond => 1,
    });
    for value in numeric {
        bytes.extend_from_slice(&value.to_bits().to_be_bytes());
    }
    Ok(AdmittedCovarianceProfileV1 {
        specification,
        digest: Digest32::of_bytes(&bytes),
    })
}
