use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

const Q24_SCALE: f64 = 16_777_216.0;
const Q24_HALF_ULP: f64 = 0.5 / Q24_SCALE;
/// Keep `value * 2^24` within the exact-integer range of binary64 so midpoint
/// parity for nearest/ties-to-even is reproducible rather than inferred after
/// integer spacing has already exceeded one raw Q24 unit.
const MAX_EXACT_Q24_Z: f64 = 536_870_912.0; // 2^29; scaled magnitude is 2^53.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ZCoordinateConventionV1 {
    OriginalIncrement,
    WhitenedIncrement,
}

#[derive(Clone, Debug, PartialEq)]
pub struct NduZConversionProfileV1 {
    pub units_digest: Digest32,
    pub driver_dimension: usize,
    pub utility_dimension: usize,
    pub source_coordinates: ZCoordinateConventionV1,
    /// Lower-triangular L in m = L xi. Empty for original-increment inputs.
    pub whitening_lower: Vec<Vec<f64>>,
    pub maximum_absolute_z: f64,
}

#[derive(Clone, Debug, PartialEq)]
pub struct AdmittedZConversionProfileV1 {
    pub(crate) specification: NduZConversionProfileV1,
    pub(crate) digest: Digest32,
}

impl AdmittedZConversionProfileV1 {
    #[must_use]
    pub const fn digest(&self) -> Digest32 {
        self.digest
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
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ZConversionError {
    InvalidProfile,
    MissingDigest,
    Dimension,
    NonFinite,
    CoefficientBound,
    SingularTransform,
    Q24Overflow,
    QuantizationError,
}

impl fmt::Display for ZConversionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ZConversionError {}

#[derive(Clone, Debug, PartialEq)]
pub struct ZQ24ConversionReceiptV1 {
    /// Utility x driver sensitivity in canonical original-increment coordinates.
    original_z: Vec<Vec<f64>>,
    /// Same coefficients encoded as signed Q24 nearest/ties-to-even raw integers.
    q24_raw: Vec<Vec<i64>>,
    maximum_absolute_quantization_error: f64,
    profile_digest: Digest32,
    source_digest: Digest32,
    receipt_digest: Digest32,
    authority: AuthorityPosture,
}

impl ZQ24ConversionReceiptV1 {
    #[must_use]
    pub fn original_z(&self) -> &[Vec<f64>] {
        &self.original_z
    }

    #[must_use]
    pub fn q24_raw(&self) -> &[Vec<i64>] {
        &self.q24_raw
    }

    #[must_use]
    pub const fn maximum_absolute_quantization_error(&self) -> f64 {
        self.maximum_absolute_quantization_error
    }

    #[must_use]
    pub const fn profile_digest(&self) -> Digest32 {
        self.profile_digest
    }

    #[must_use]
    pub const fn source_digest(&self) -> Digest32 {
        self.source_digest
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }

    #[must_use]
    pub const fn authority(&self) -> AuthorityPosture {
        self.authority
    }
}

/// Admits the coordinate/quantization convention only. Artifact provenance,
/// runtime selection, conditional identification and efficacy remain separate.
pub fn admit_z_conversion_profile(
    specification: NduZConversionProfileV1,
) -> Result<AdmittedZConversionProfileV1, ZConversionError> {
    if specification.units_digest.is_zero()
        || !(1..=32).contains(&specification.driver_dimension)
        || !(1..=8).contains(&specification.utility_dimension)
        || !specification.maximum_absolute_z.is_finite()
        || specification.maximum_absolute_z <= 0.0
        || specification.maximum_absolute_z > MAX_EXACT_Q24_Z
    {
        return Err(ZConversionError::InvalidProfile);
    }

    let dimension = specification.driver_dimension;
    match specification.source_coordinates {
        ZCoordinateConventionV1::OriginalIncrement => {
            if !specification.whitening_lower.is_empty() {
                return Err(ZConversionError::InvalidProfile);
            }
        }
        ZCoordinateConventionV1::WhitenedIncrement => {
            if specification.whitening_lower.len() != dimension
                || specification
                    .whitening_lower
                    .iter()
                    .any(|row| row.len() != dimension)
            {
                return Err(ZConversionError::InvalidProfile);
            }
            for (i, row) in specification.whitening_lower.iter().enumerate() {
                for (j, value) in row.iter().enumerate() {
                    if !value.is_finite() || value.abs() > 1e12 || (j > i && *value != 0.0) {
                        return Err(ZConversionError::InvalidProfile);
                    }
                }
                if row[i] <= 0.0 {
                    return Err(ZConversionError::SingularTransform);
                }
            }
        }
    }

    let mut bytes = b"hepta.ndu.z-coordinate-q24-profile.v1".to_vec();
    bytes.extend_from_slice(specification.units_digest.as_array());
    bytes.extend_from_slice(&(specification.driver_dimension as u64).to_be_bytes());
    bytes.extend_from_slice(&(specification.utility_dimension as u64).to_be_bytes());
    bytes.push(match specification.source_coordinates {
        ZCoordinateConventionV1::OriginalIncrement => 0,
        ZCoordinateConventionV1::WhitenedIncrement => 1,
    });
    bytes.extend_from_slice(&specification.maximum_absolute_z.to_bits().to_be_bytes());
    for value in specification.whitening_lower.iter().flatten() {
        bytes.extend_from_slice(&value.to_bits().to_be_bytes());
    }

    Ok(AdmittedZConversionProfileV1 {
        specification,
        digest: Digest32::of_bytes(&bytes),
    })
}

/// Converts a learned/shadow Z head into canonical original increment
/// coordinates and then signed Q24. With m = L xi and Z_xi = Z_m L, whitened
/// inputs are solved as Z_m L = Z_xi using the admitted lower-triangular L.
pub fn convert_z_to_original_q24(
    source_z: &[Vec<f64>],
    source_digest: Digest32,
    profile: &AdmittedZConversionProfileV1,
) -> Result<ZQ24ConversionReceiptV1, ZConversionError> {
    if source_digest.is_zero() {
        return Err(ZConversionError::MissingDigest);
    }
    let spec = &profile.specification;
    if source_z.len() != spec.utility_dimension
        || source_z
            .iter()
            .any(|row| row.len() != spec.driver_dimension)
    {
        return Err(ZConversionError::Dimension);
    }
    for value in source_z.iter().flatten() {
        validate_coefficient(*value, spec.maximum_absolute_z)?;
    }

    let original_z = match spec.source_coordinates {
        ZCoordinateConventionV1::OriginalIncrement => source_z.to_vec(),
        ZCoordinateConventionV1::WhitenedIncrement => source_z
            .iter()
            .map(|row| solve_row_against_lower(row, &spec.whitening_lower))
            .collect::<Result<Vec<_>, _>>()?,
    };
    for value in original_z.iter().flatten() {
        validate_coefficient(*value, spec.maximum_absolute_z)?;
    }

    let mut q24_raw = Vec::with_capacity(original_z.len());
    let mut maximum_absolute_quantization_error = 0.0_f64;
    for row in &original_z {
        let mut encoded = Vec::with_capacity(row.len());
        for value in row {
            let scaled = *value * Q24_SCALE;
            if !scaled.is_finite()
                || scaled < -((1_u64 << 53) as f64)
                || scaled > (1_u64 << 53) as f64
            {
                return Err(ZConversionError::Q24Overflow);
            }
            let rounded = round_ties_even(scaled);
            let raw = rounded as i64;
            let recovered = raw as f64 / Q24_SCALE;
            let error = (*value - recovered).abs();
            if !error.is_finite() || error > Q24_HALF_ULP + f64::EPSILON * value.abs().max(1.0) {
                return Err(ZConversionError::QuantizationError);
            }
            maximum_absolute_quantization_error = maximum_absolute_quantization_error.max(error);
            encoded.push(raw);
        }
        q24_raw.push(encoded);
    }

    let mut bytes = b"hepta.ndu.z-coordinate-q24-receipt.v1".to_vec();
    bytes.extend_from_slice(profile.digest.as_array());
    bytes.extend_from_slice(source_digest.as_array());
    for value in source_z.iter().flatten() {
        bytes.extend_from_slice(&value.to_bits().to_be_bytes());
    }
    for value in original_z.iter().flatten() {
        bytes.extend_from_slice(&value.to_bits().to_be_bytes());
    }
    for raw in q24_raw.iter().flatten() {
        bytes.extend_from_slice(&raw.to_be_bytes());
    }
    bytes.extend_from_slice(&maximum_absolute_quantization_error.to_bits().to_be_bytes());

    Ok(ZQ24ConversionReceiptV1 {
        original_z,
        q24_raw,
        maximum_absolute_quantization_error,
        profile_digest: profile.digest,
        source_digest,
        receipt_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn solve_row_against_lower(row: &[f64], lower: &[Vec<f64>]) -> Result<Vec<f64>, ZConversionError> {
    let dimension = row.len();
    let mut original = vec![0.0; dimension];
    for j in (0..dimension).rev() {
        let tail: f64 = (j + 1..dimension).map(|i| original[i] * lower[i][j]).sum();
        let diagonal = lower[j][j];
        if !diagonal.is_finite() || diagonal <= 0.0 {
            return Err(ZConversionError::SingularTransform);
        }
        original[j] = (row[j] - tail) / diagonal;
        if !original[j].is_finite() {
            return Err(ZConversionError::NonFinite);
        }
    }
    Ok(original)
}

fn validate_coefficient(value: f64, maximum_absolute_z: f64) -> Result<(), ZConversionError> {
    if !value.is_finite() {
        return Err(ZConversionError::NonFinite);
    }
    if value.abs() > maximum_absolute_z {
        return Err(ZConversionError::CoefficientBound);
    }
    Ok(())
}

fn round_ties_even(value: f64) -> f64 {
    let floor = value.floor();
    let fraction = value - floor;
    if fraction < 0.5 {
        floor
    } else if fraction > 0.5 {
        floor + 1.0
    } else if floor % 2.0 == 0.0 {
        floor
    } else {
        floor + 1.0
    }
}

#[cfg(test)]
#[path = "z_conversion_tests.rs"]
mod tests;
