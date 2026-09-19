use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use super::NduZConversionProfileV1;
use super::ZConversionError;
use super::ZCoordinateConventionV1;
use super::admit_z_conversion_profile;
use super::convert_z_to_original_q24;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn original_profile(driver_dimension: usize) -> super::AdmittedZConversionProfileV1 {
    checked(admit_z_conversion_profile(NduZConversionProfileV1 {
        units_digest: Digest32::of_bytes(b"z-units-and-order"),
        driver_dimension,
        utility_dimension: 1,
        source_coordinates: ZCoordinateConventionV1::OriginalIncrement,
        whitening_lower: Vec::new(),
        maximum_absolute_z: 100.0,
    }))
}

#[test]
fn original_coordinates_quantize_q24_with_nearest_ties_even() {
    let profile = original_profile(/*driver_dimension*/ 4);
    let scale = 16_777_216.0;
    let source = vec![vec![1.5 / scale, 2.5 / scale, -1.5 / scale, -2.5 / scale]];
    let receipt = checked(convert_z_to_original_q24(
        &source,
        Digest32::of_bytes(b"source-z"),
        &profile,
    ));

    assert_eq!(receipt.original_z, source);
    assert_eq!(receipt.q24_raw, vec![vec![2, 2, -2, -2]]);
    assert!(receipt.maximum_absolute_quantization_error <= 0.5 / scale);
    assert_eq!(receipt.profile_digest, profile.digest());
    assert!(!receipt.receipt_digest.is_zero());
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn whitened_head_is_converted_back_to_original_increment_coordinates() {
    let profile = checked(admit_z_conversion_profile(NduZConversionProfileV1 {
        units_digest: Digest32::of_bytes(b"whitened-z-units"),
        driver_dimension: 2,
        utility_dimension: 1,
        source_coordinates: ZCoordinateConventionV1::WhitenedIncrement,
        whitening_lower: vec![vec![2.0, 0.0], vec![1.0, 3.0]],
        maximum_absolute_z: 100.0,
    }));

    // m = L xi and Z_xi = Z_m L. For Z_m=[3,-1], Z_xi=[5,-3].
    let receipt = checked(convert_z_to_original_q24(
        &[vec![5.0, -3.0]],
        Digest32::of_bytes(b"whitened-head"),
        &profile,
    ));

    assert_eq!(receipt.original_z, vec![vec![3.0, -1.0]]);
    assert_eq!(receipt.q24_raw, vec![vec![50_331_648, -16_777_216]]);
    assert_eq!(receipt.maximum_absolute_quantization_error, 0.0);
}

#[test]
fn profile_admission_rejects_ambiguous_or_singular_coordinate_conventions() {
    let base = NduZConversionProfileV1 {
        units_digest: Digest32::of_bytes(b"z-units"),
        driver_dimension: 2,
        utility_dimension: 1,
        source_coordinates: ZCoordinateConventionV1::OriginalIncrement,
        whitening_lower: Vec::new(),
        maximum_absolute_z: 100.0,
    };

    let mut invalid = base.clone();
    invalid.whitening_lower = vec![vec![1.0, 0.0], vec![0.0, 1.0]];
    assert_eq!(
        admit_z_conversion_profile(invalid),
        Err(ZConversionError::InvalidProfile)
    );

    let mut invalid = base.clone();
    invalid.source_coordinates = ZCoordinateConventionV1::WhitenedIncrement;
    invalid.whitening_lower = vec![vec![1.0, 1.0], vec![0.0, 1.0]];
    assert_eq!(
        admit_z_conversion_profile(invalid),
        Err(ZConversionError::InvalidProfile)
    );

    let mut singular = base.clone();
    singular.source_coordinates = ZCoordinateConventionV1::WhitenedIncrement;
    singular.whitening_lower = vec![vec![1.0, 0.0], vec![0.0, 0.0]];
    assert_eq!(
        admit_z_conversion_profile(singular),
        Err(ZConversionError::SingularTransform)
    );

    // Q24 ties-to-even is admitted only while value*2^24 remains within the
    // exact integer range of binary64; this is a numerical convention failure.
    let mut inexact = base;
    inexact.maximum_absolute_z = 536_870_912.0 + 1.0;
    assert_eq!(
        admit_z_conversion_profile(inexact),
        Err(ZConversionError::InvalidProfile)
    );
}

#[test]
fn conversion_rejects_wrong_shape_nonfinite_bound_and_missing_source_identity() {
    let profile = original_profile(/*driver_dimension*/ 2);
    let source_digest = Digest32::of_bytes(b"source-z");

    assert_eq!(
        convert_z_to_original_q24(&[vec![1.0]], source_digest, &profile),
        Err(ZConversionError::Dimension)
    );
    assert_eq!(
        convert_z_to_original_q24(&[vec![f64::NAN, 0.0]], source_digest, &profile),
        Err(ZConversionError::NonFinite)
    );
    assert_eq!(
        convert_z_to_original_q24(&[vec![101.0, 0.0]], source_digest, &profile),
        Err(ZConversionError::CoefficientBound)
    );
    assert_eq!(
        convert_z_to_original_q24(&[vec![1.0, 0.0]], Digest32::ZERO, &profile),
        Err(ZConversionError::MissingDigest)
    );
}

#[test]
fn coordinate_profile_digest_binds_transform_and_convention() {
    let original = original_profile(/*driver_dimension*/ 2);
    let whitened = checked(admit_z_conversion_profile(NduZConversionProfileV1 {
        units_digest: Digest32::of_bytes(b"z-units-and-order"),
        driver_dimension: 2,
        utility_dimension: 1,
        source_coordinates: ZCoordinateConventionV1::WhitenedIncrement,
        whitening_lower: vec![vec![1.0, 0.0], vec![0.0, 1.0]],
        maximum_absolute_z: 100.0,
    }));
    assert_ne!(original.digest(), whitened.digest());

    let changed = checked(admit_z_conversion_profile(NduZConversionProfileV1 {
        units_digest: Digest32::of_bytes(b"z-units-and-order"),
        driver_dimension: 2,
        utility_dimension: 1,
        source_coordinates: ZCoordinateConventionV1::WhitenedIncrement,
        whitening_lower: vec![vec![2.0, 0.0], vec![0.0, 1.0]],
        maximum_absolute_z: 100.0,
    }));
    assert_ne!(whitened.digest(), changed.digest());
}
