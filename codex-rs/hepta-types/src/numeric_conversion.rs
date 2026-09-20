use crate::AuthorityPosture;
use crate::Digest32;
use crate::NumericConversionError;
use crate::NumericProfileV1;
use crate::NumericRoundingV1;
use crate::NumericSignalSchemaV1;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NumericSignalV1 {
    pub schema: NumericSignalSchemaV1,
    pub values: Vec<i64>,
}

/// Exact rational maximum absolute conversion error in the declared signal unit.
/// Denominator is source_scale * target_scale, and is always positive.
/// Round-trip error is bounded by the sum of the two receipt fractions.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct NumericErrorBoundV1 {
    pub numerator: u128,
    pub denominator: u128,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NumericConversionReceiptV1 {
    pub source_profile: NumericProfileV1,
    pub target_profile: NumericProfileV1,
    pub source_digest: Digest32,
    pub output_digest: Digest32,
    pub absolute_error_bound: NumericErrorBoundV1,
    pub evidence_digest: Digest32,
    pub authority: AuthorityPosture,
}

/// Rescales bounded numeric signals with the target profile's rounding.
/// Unit, shape and normalization must match exactly; this performs no unit
/// conversion, renormalization, projection or production-profile admission.
/// There are deliberately no conversions from exact authority/identity types.
pub fn rescale_signal(
    source: &NumericSignalV1,
    target: &NumericSignalSchemaV1,
) -> Result<(NumericSignalV1, NumericConversionReceiptV1), NumericConversionError> {
    let count = source.schema.element_count()?;
    target.element_count()?;
    if source.values.len() != count || source.schema.shape != target.shape {
        return Err(NumericConversionError::Shape);
    }
    if source.schema.unit != target.unit {
        return Err(NumericConversionError::UnitMismatch);
    }
    if source.schema.normalization_digest != target.normalization_digest {
        return Err(NumericConversionError::NormalizationMismatch);
    }
    if source
        .values
        .iter()
        .any(|value| *value < source.schema.minimum_raw || *value > source.schema.maximum_raw)
    {
        return Err(NumericConversionError::OutOfRange);
    }
    let source_scale = i128::from(source.schema.profile.scale());
    let target_scale = i128::from(target.profile.scale());
    let mut values = Vec::with_capacity(count);
    let mut maximum_error = 0;
    for value in &source.values {
        let wide = i128::from(*value)
            .checked_mul(target_scale)
            .ok_or(NumericConversionError::Overflow)?;
        let magnitude = wide.unsigned_abs();
        let divisor = source_scale as u128;
        let mut quotient = magnitude / divisor;
        let remainder = magnitude % divisor;
        match target.profile.rounding() {
            NumericRoundingV1::TowardZero => {}
            NumericRoundingV1::NearestTiesEven => {
                let twice = remainder
                    .checked_mul(2)
                    .ok_or(NumericConversionError::Overflow)?;
                if twice > divisor || (twice == divisor && quotient % 2 == 1) {
                    quotient = quotient
                        .checked_add(1)
                        .ok_or(NumericConversionError::Overflow)?;
                }
            }
        }
        let signed = i128::try_from(quotient).map_err(|_| NumericConversionError::Overflow)?;
        let signed = if wide < 0 { -signed } else { signed };
        let converted = i64::try_from(signed).map_err(|_| NumericConversionError::Overflow)?;
        if converted < target.minimum_raw || converted > target.maximum_raw {
            return Err(NumericConversionError::OutOfRange);
        }
        let reconstructed = signed
            .checked_mul(source_scale)
            .ok_or(NumericConversionError::Overflow)?;
        let error = wide
            .checked_sub(reconstructed)
            .ok_or(NumericConversionError::Overflow)?
            .unsigned_abs();
        maximum_error = maximum_error.max(error);
        values.push(converted);
    }
    let output = NumericSignalV1 {
        schema: target.clone(),
        values,
    };
    let source_digest = signal_digest(source);
    let output_digest = signal_digest(&output);
    let absolute_error_bound = NumericErrorBoundV1 {
        numerator: maximum_error,
        denominator: (source_scale as u128)
            .checked_mul(target_scale as u128)
            .ok_or(NumericConversionError::Overflow)?,
    };
    let mut bytes = b"hepta.numeric-signal.conversion.native.v1".to_vec();
    bytes.extend_from_slice(source_digest.as_array());
    bytes.extend_from_slice(output_digest.as_array());
    bytes.extend_from_slice(&absolute_error_bound.numerator.to_be_bytes());
    bytes.extend_from_slice(&absolute_error_bound.denominator.to_be_bytes());
    let receipt = NumericConversionReceiptV1 {
        source_profile: source.schema.profile,
        target_profile: target.profile,
        source_digest,
        output_digest,
        absolute_error_bound,
        evidence_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((output, receipt))
}

fn signal_digest(signal: &NumericSignalV1) -> Digest32 {
    let schema = &signal.schema;
    let mut bytes = b"hepta.numeric-signal.row-major.native.v1".to_vec();
    let id = schema.profile.id().as_bytes();
    bytes.extend_from_slice(&(id.len() as u64).to_be_bytes());
    bytes.extend_from_slice(id);
    bytes.extend_from_slice(&schema.profile.scale().to_be_bytes());
    bytes.push(match schema.profile.rounding() {
        NumericRoundingV1::TowardZero => 0,
        NumericRoundingV1::NearestTiesEven => 1,
    });
    bytes.push(0); // V1 overflow policy: reject, never saturate.
    bytes.push(schema.unit.tag());
    bytes.extend_from_slice(&(schema.shape.len() as u64).to_be_bytes());
    for dimension in &schema.shape {
        bytes.extend_from_slice(&(*dimension as u64).to_be_bytes());
    }
    bytes.extend_from_slice(&schema.minimum_raw.to_be_bytes());
    bytes.extend_from_slice(&schema.maximum_raw.to_be_bytes());
    bytes.extend_from_slice(schema.normalization_digest.as_array());
    bytes.extend_from_slice(&(signal.values.len() as u64).to_be_bytes());
    for value in &signal.values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

#[cfg(test)]
#[path = "numeric_conversion_tests.rs"]
mod tests;
