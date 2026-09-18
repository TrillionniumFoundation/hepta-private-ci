use crate::AuthorityPosture;
use crate::CanonicalFieldV1;
use crate::CanonicalValueV1;
use crate::ContractRegistryV1;
use crate::Digest32;
use crate::NumericConversionError;
use crate::NumericProfileV1;
use crate::NumericRoundingV1;
use crate::NumericSignalSchemaV1;
use crate::RegistryKindV1;
use crate::StableId;
use crate::canonical_digest_v1;

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
    let source_digest = signal_digest(source)?;
    let output_digest = signal_digest(&output)?;
    let absolute_error_bound = NumericErrorBoundV1 {
        numerator: maximum_error,
        denominator: (source_scale as u128)
            .checked_mul(target_scale as u128)
            .ok_or(NumericConversionError::Overflow)?,
    };
    let evidence_digest = conversion_digest(
        source.schema.profile,
        target.profile,
        source_digest,
        output_digest,
        absolute_error_bound,
    )?;
    let receipt = NumericConversionReceiptV1 {
        source_profile: source.schema.profile,
        target_profile: target.profile,
        source_digest,
        output_digest,
        absolute_error_bound,
        evidence_digest,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok((output, receipt))
}

/// Registry-enforced conversion. The normalization contract must resolve to an
/// immutable V1 normalization definition before numeric conversion begins.
pub fn rescale_signal_registered(
    source: &NumericSignalV1,
    target: &NumericSignalSchemaV1,
    registry: &ContractRegistryV1,
) -> Result<(NumericSignalV1, NumericConversionReceiptV1), NumericConversionError> {
    if source.schema.normalization_digest.is_zero() || target.normalization_digest.is_zero() {
        return Err(NumericConversionError::MissingNormalization);
    }
    if source.schema.normalization_digest != target.normalization_digest {
        return Err(NumericConversionError::NormalizationMismatch);
    }
    if registry
        .resolve_digest(
            RegistryKindV1::Normalization,
            source.schema.normalization_digest,
        )
        .is_none()
    {
        return Err(NumericConversionError::UnknownNormalization);
    }
    rescale_signal(source, target)
}

fn signal_digest(signal: &NumericSignalV1) -> Result<Digest32, NumericConversionError> {
    let schema = &signal.schema;
    let type_id = StableId::new("hepta.numeric-signal:row-major-native-v1")
        .map_err(|_| NumericConversionError::CanonicalEncoding)?;
    let shape: Vec<CanonicalValueV1<'_>> = schema
        .shape
        .iter()
        .map(|dimension| {
            u64::try_from(*dimension)
                .map(CanonicalValueV1::U64)
                .map_err(|_| NumericConversionError::CanonicalEncoding)
        })
        .collect::<Result<_, _>>()?;
    let values: Vec<CanonicalValueV1<'_>> = signal
        .values
        .iter()
        .copied()
        .map(CanonicalValueV1::I64)
        .collect();
    let fields = [
        CanonicalFieldV1 {
            name: "maximum_raw",
            value: CanonicalValueV1::I64(schema.maximum_raw),
        },
        CanonicalFieldV1 {
            name: "minimum_raw",
            value: CanonicalValueV1::I64(schema.minimum_raw),
        },
        CanonicalFieldV1 {
            name: "normalization_digest",
            value: CanonicalValueV1::Digest(schema.normalization_digest),
        },
        CanonicalFieldV1 {
            name: "overflow_policy",
            value: CanonicalValueV1::Text("reject"),
        },
        CanonicalFieldV1 {
            name: "profile_id",
            value: CanonicalValueV1::Text(schema.profile.id()),
        },
        CanonicalFieldV1 {
            name: "rounding",
            value: CanonicalValueV1::Text(schema.profile.rounding().id()),
        },
        CanonicalFieldV1 {
            name: "scale",
            value: CanonicalValueV1::U64(schema.profile.scale()),
        },
        CanonicalFieldV1 {
            name: "shape",
            value: CanonicalValueV1::Array(&shape),
        },
        CanonicalFieldV1 {
            name: "unit",
            value: CanonicalValueV1::Text(schema.unit.id()),
        },
        CanonicalFieldV1 {
            name: "values",
            value: CanonicalValueV1::Array(&values),
        },
    ];
    canonical_digest_v1(&type_id, 1, &fields)
        .map_err(|_| NumericConversionError::CanonicalEncoding)
}

fn conversion_digest(
    source_profile: NumericProfileV1,
    target_profile: NumericProfileV1,
    source_digest: Digest32,
    output_digest: Digest32,
    error: NumericErrorBoundV1,
) -> Result<Digest32, NumericConversionError> {
    let type_id = StableId::new("hepta.numeric-signal:conversion-receipt-native-v1")
        .map_err(|_| NumericConversionError::CanonicalEncoding)?;
    let fields = [
        CanonicalFieldV1 {
            name: "error_denominator",
            value: CanonicalValueV1::U128(error.denominator),
        },
        CanonicalFieldV1 {
            name: "error_numerator",
            value: CanonicalValueV1::U128(error.numerator),
        },
        CanonicalFieldV1 {
            name: "output_digest",
            value: CanonicalValueV1::Digest(output_digest),
        },
        CanonicalFieldV1 {
            name: "source_digest",
            value: CanonicalValueV1::Digest(source_digest),
        },
        CanonicalFieldV1 {
            name: "source_profile",
            value: CanonicalValueV1::Text(source_profile.id()),
        },
        CanonicalFieldV1 {
            name: "target_profile",
            value: CanonicalValueV1::Text(target_profile.id()),
        },
    ];
    canonical_digest_v1(&type_id, 1, &fields)
        .map_err(|_| NumericConversionError::CanonicalEncoding)
}

#[cfg(test)]
#[path = "numeric_conversion_tests.rs"]
mod tests;
