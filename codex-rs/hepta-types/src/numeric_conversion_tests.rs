use super::*;
use crate::FixedQ32;
use crate::SignalUnitV1;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn signal(profile: NumericProfileV1, values: Vec<i64>) -> NumericSignalV1 {
    NumericSignalV1 {
        schema: NumericSignalSchemaV1 {
            profile,
            unit: SignalUnitV1::Dimensionless,
            shape: vec![values.len()],
            minimum_raw: i64::MIN,
            maximum_raw: i64::MAX,
            normalization_digest: Digest32::of_bytes(b"immutable-normalizer"),
        },
        values,
    }
}

#[test]
fn signed_half_ties_round_to_even_target_bins() {
    let source = signal(
        NumericProfileV1::SignedQ32NearestTiesEven,
        vec![640, 896, -640, -896, 128, -128],
    );
    let target = NumericSignalSchemaV1 {
        profile: NumericProfileV1::SignedQ24NearestTiesEven,
        ..source.schema.clone()
    };
    let (output, receipt) = checked(rescale_signal(&source, &target));
    assert_eq!(
        output,
        NumericSignalV1 {
            schema: target,
            values: vec![2, 4, -2, -4, 0, 0]
        }
    );
    assert_eq!(
        receipt.absolute_error_bound,
        NumericErrorBoundV1 {
            numerator: 1 << 31,
            denominator: 1 << 56,
        }
    );
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn ppm_q24_roundtrip_reports_exact_error_instead_of_byte_equality() {
    let source = signal(
        NumericProfileV1::HnmfPpmTowardZero,
        vec![0, 1, 3, -1, -3, 123_456, -123_456, 1_000_000],
    );
    let target = NumericSignalSchemaV1 {
        profile: NumericProfileV1::SignedQ24NearestTiesEven,
        ..source.schema.clone()
    };
    let (q24, outward) = checked(rescale_signal(&source, &target));
    assert_eq!(
        q24.values,
        vec![0, 17, 50, -17, -50, 2_071_248, -2_071_248, 16_777_216]
    );
    let (back, inward) = checked(rescale_signal(&q24, &source.schema));
    assert_eq!(
        back.values,
        vec![0, 1, 2, -1, -2, 123_456, -123_456, 1_000_000]
    );
    assert_eq!(
        outward.absolute_error_bound,
        NumericErrorBoundV1 {
            numerator: 331_648,
            denominator: 16_777_216_000_000
        }
    );
    assert_eq!(
        inward.absolute_error_bound,
        NumericErrorBoundV1 {
            numerator: 16_445_568,
            denominator: 16_777_216_000_000
        }
    );
    assert_eq!(outward.output_digest, inward.source_digest);
    assert_ne!(outward.source_digest, inward.output_digest);
    // Sum of exact bounds is 1 ppm, bounding every returned component.
    let bound_numerator =
        outward.absolute_error_bound.numerator + inward.absolute_error_bound.numerator;
    for (initial, final_value) in source.values.iter().zip(back.values) {
        let error = (i128::from(*initial) - i128::from(final_value)).unsigned_abs();
        assert!(error * outward.absolute_error_bound.denominator <= bound_numerator * 1_000_000);
    }
}

#[test]
fn q24_to_q32_is_exact_and_legacy_multiply_keeps_toward_zero() {
    let source = signal(NumericProfileV1::SignedQ24NearestTiesEven, vec![-7, 0, 7]);
    let target = NumericSignalSchemaV1 {
        profile: NumericProfileV1::SignedQ32NearestTiesEven,
        ..source.schema.clone()
    };
    let (output, receipt) = checked(rescale_signal(&source, &target));
    assert_eq!(output.values, vec![-1792, 0, 1792]);
    assert_eq!(receipt.absolute_error_bound.numerator, 0);
    let half = FixedQ32::from_raw(1 << 31);
    assert_eq!(
        FixedQ32::from_raw(7).checked_mul(half),
        Ok(FixedQ32::from_raw(3))
    );
    assert_eq!(
        FixedQ32::from_raw(-7).checked_mul(half),
        Ok(FixedQ32::from_raw(-3))
    );
}

#[test]
fn checked_scaling_rejects_overflow_without_mutating_input() {
    let source = signal(NumericProfileV1::HnmfPpmTowardZero, vec![1, i64::MAX]);
    let original = source.clone();
    let target = NumericSignalSchemaV1 {
        profile: NumericProfileV1::SignedQ32NearestTiesEven,
        ..source.schema.clone()
    };
    assert_eq!(
        rescale_signal(&source, &target),
        Err(NumericConversionError::Overflow)
    );
    assert_eq!(source, original);
    let minimum = signal(
        NumericProfileV1::SignedQ32NearestTiesEven,
        vec![i64::MIN, i64::MAX],
    );
    assert_eq!(
        checked(rescale_signal(&minimum, &minimum.schema)).0,
        minimum
    );
    let negative = signal(NumericProfileV1::HnmfPpmTowardZero, vec![i64::MIN]);
    let target = NumericSignalSchemaV1 {
        profile: NumericProfileV1::SignedQ24NearestTiesEven,
        ..negative.schema.clone()
    };
    assert_eq!(
        rescale_signal(&negative, &target),
        Err(NumericConversionError::Overflow)
    );
}

#[test]
fn incompatible_units_normalization_shape_and_ranges_reject() {
    let source = signal(NumericProfileV1::HnmfPpmTowardZero, vec![1, 2]);
    for case in 0..5 {
        let mut target = source.schema.clone();
        let error = match case {
            0 => {
                target.unit = SignalUnitV1::Metres;
                NumericConversionError::UnitMismatch
            }
            1 => {
                target.normalization_digest = Digest32::of_bytes(b"other-normalizer");
                NumericConversionError::NormalizationMismatch
            }
            2 => {
                target.shape = vec![1, 2];
                NumericConversionError::Shape
            }
            3 => {
                target.maximum_raw = 1;
                NumericConversionError::OutOfRange
            }
            _ => {
                target.minimum_raw = 2;
                target.maximum_raw = 1;
                NumericConversionError::InvalidRange
            }
        };
        assert_eq!(rescale_signal(&source, &target), Err(error));
    }
    let mut source = source;
    source.schema.minimum_raw = 2;
    assert_eq!(
        rescale_signal(&source, &source.schema),
        Err(NumericConversionError::OutOfRange)
    );
}

#[test]
fn malformed_shape_and_unknown_profile_cannot_enter_conversion() {
    assert_eq!(
        NumericProfileV1::from_id("q32-v0"),
        Err(NumericConversionError::UnknownProfile)
    );
    let source = signal(NumericProfileV1::HnmfPpmTowardZero, vec![1]);
    for shape in [vec![0], vec![4097], vec![usize::MAX, 2], vec![1; 5]] {
        let malformed = NumericSignalV1 {
            schema: NumericSignalSchemaV1 {
                shape,
                ..source.schema.clone()
            },
            ..source.clone()
        };
        assert_eq!(
            rescale_signal(&malformed, &source.schema),
            Err(NumericConversionError::Shape)
        );
    }
    let mut missing = source.clone();
    missing.values.clear();
    assert_eq!(
        rescale_signal(&missing, &source.schema),
        Err(NumericConversionError::Shape)
    );
    missing = source.clone();
    missing.schema.normalization_digest = Digest32::ZERO;
    assert_eq!(
        rescale_signal(&missing, &source.schema),
        Err(NumericConversionError::MissingNormalization)
    );
    let mut scalar = source;
    scalar.schema.shape.clear();
    assert_eq!(checked(rescale_signal(&scalar, &scalar.schema)).0, scalar);
}

#[test]
fn digest_binds_numerical_profile_shape_range_units_and_normalization() {
    let source = signal(NumericProfileV1::HnmfPpmTowardZero, vec![0]);
    let target = NumericSignalSchemaV1 {
        profile: NumericProfileV1::SignedQ24NearestTiesEven,
        ..source.schema.clone()
    };
    let result = checked(rescale_signal(&source, &target));
    assert_ne!(result.1.source_digest, result.1.output_digest);
    assert_eq!(rescale_signal(&source, &target), Ok(result.clone()));
    for case in 0..5 {
        let mut changed = source.clone();
        match case {
            0 => changed.schema.shape.clear(),
            1 => changed.schema.minimum_raw += 1,
            2 => changed.schema.unit = SignalUnitV1::Utility,
            3 => changed.schema.normalization_digest = Digest32::of_bytes(b"new-normalizer"),
            _ => changed.values[0] = 1,
        }
        let target = NumericSignalSchemaV1 {
            profile: NumericProfileV1::SignedQ24NearestTiesEven,
            ..changed.schema.clone()
        };
        let receipt = checked(rescale_signal(&changed, &target)).1;
        assert_ne!(receipt.source_digest, result.1.source_digest);
        assert_ne!(receipt.evidence_digest, result.1.evidence_digest);
    }
}
