use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

const MAX_VALUES: usize = 256;
const Q32_TO_Q24_SHIFT: u32 = 8;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct FixedQ24(i64);

impl FixedQ24 {
    #[must_use]
    pub const fn from_raw(raw: i64) -> Self {
        Self(raw)
    }

    #[must_use]
    pub const fn raw(self) -> i64 {
        self.0
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NduCoordinateConversionReceiptV1 {
    pub units_digest: Digest32,
    pub source_profile_digest: Digest32,
    pub target_profile_digest: Digest32,
    pub rounding_profile_digest: Digest32,
    pub source_digest: Digest32,
    pub output_digest: Digest32,
    pub maximum_absolute_error_q32_raw: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NduCoordinateConversionError {
    EmptyValues,
    ValueLimitExceeded,
    MissingDigest,
    Arithmetic,
}

impl fmt::Display for NduCoordinateConversionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NduCoordinateConversionError {}

/// Convert signed Q32 values to signed Q24 using nearest/ties-even.
///
/// The receipt binds units, source/target numerical profiles, rounding profile,
/// source bytes identity, converted values and the observed maximum absolute
/// Q32 reconstruction error. Identifier/authority/deletion/fence fields must
/// never be passed through this approximate conversion.
pub fn convert_q32_to_q24(
    values: &[FixedQ32],
    units_digest: Digest32,
    source_profile_digest: Digest32,
    target_profile_digest: Digest32,
    source_digest: Digest32,
) -> Result<(Vec<FixedQ24>, NduCoordinateConversionReceiptV1), NduCoordinateConversionError> {
    if values.is_empty() {
        return Err(NduCoordinateConversionError::EmptyValues);
    }
    if values.len() > MAX_VALUES {
        return Err(NduCoordinateConversionError::ValueLimitExceeded);
    }
    if [
        units_digest,
        source_profile_digest,
        target_profile_digest,
        source_digest,
    ]
    .iter()
    .any(|digest| digest.is_zero())
    {
        return Err(NduCoordinateConversionError::MissingDigest);
    }

    let rounding_profile_digest =
        Digest32::of_bytes(b"hepta.ndu.q32-to-q24-nearest-ties-even.v1");
    let mut converted = Vec::with_capacity(values.len());
    let mut maximum_error = 0_u64;
    for value in values {
        let raw = i128::from(value.raw());
        let negative = raw < 0;
        let magnitude = raw.checked_abs().ok_or(NduCoordinateConversionError::Arithmetic)?;
        let divisor = 1_i128 << Q32_TO_Q24_SHIFT;
        let mut quotient = magnitude / divisor;
        let remainder = magnitude % divisor;
        let half = divisor / 2;
        if remainder > half || (remainder == half && quotient & 1 == 1) {
            quotient = quotient
                .checked_add(1)
                .ok_or(NduCoordinateConversionError::Arithmetic)?;
        }
        let signed = if negative { -quotient } else { quotient };
        let q24 = i64::try_from(signed).map_err(|_| NduCoordinateConversionError::Arithmetic)?;
        let reconstructed = signed
            .checked_mul(divisor)
            .ok_or(NduCoordinateConversionError::Arithmetic)?;
        let error = raw
            .checked_sub(reconstructed)
            .and_then(i128::checked_abs)
            .ok_or(NduCoordinateConversionError::Arithmetic)?;
        maximum_error = maximum_error.max(
            u64::try_from(error).map_err(|_| NduCoordinateConversionError::Arithmetic)?,
        );
        converted.push(FixedQ24::from_raw(q24));
    }

    let mut output_bytes = b"hepta.ndu.q24-vector.v1".to_vec();
    for value in &converted {
        output_bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    let output_digest = Digest32::of_bytes(&output_bytes);

    let mut receipt_bytes = b"hepta.ndu.coordinate-conversion-receipt.v1".to_vec();
    for digest in [
        units_digest,
        source_profile_digest,
        target_profile_digest,
        rounding_profile_digest,
        source_digest,
        output_digest,
    ] {
        receipt_bytes.extend_from_slice(digest.as_array());
    }
    receipt_bytes.extend_from_slice(&maximum_error.to_be_bytes());
    let receipt_digest = Digest32::of_bytes(&receipt_bytes);

    Ok((
        converted,
        NduCoordinateConversionReceiptV1 {
            units_digest,
            source_profile_digest,
            target_profile_digest,
            rounding_profile_digest,
            source_digest,
            output_digest,
            maximum_absolute_error_q32_raw: maximum_error,
            receipt_digest,
            authority: AuthorityPosture::DENY_ALL,
        },
    ))
}

#[cfg(test)]
#[path = "coordinate_conversion_tests.rs"]
mod tests;
