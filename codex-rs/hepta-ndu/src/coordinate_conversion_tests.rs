use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

use super::convert_q32_to_q24;

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[test]
fn q32_to_q24_uses_nearest_ties_even_and_binds_error() {
    let half = 1_i64 << 7;
    let values = [
        FixedQ32::from_raw((2_i64 << 8) + half),
        FixedQ32::from_raw((3_i64 << 8) + half),
        FixedQ32::from_raw(-((3_i64 << 8) + half)),
    ];
    let (converted, receipt) = convert_q32_to_q24(
        &values,
        digest("units"),
        digest("q32-profile"),
        digest("q24-profile"),
        digest("source"),
    )
    .expect("valid conversion");

    assert_eq!(converted[0].raw(), 2);
    assert_eq!(converted[1].raw(), 4);
    assert_eq!(converted[2].raw(), -4);
    assert_eq!(receipt.maximum_absolute_error_q32_raw, 128);
    assert!(!receipt.receipt_digest.is_zero());
    assert!(!receipt.authority.grants_any());
}

#[test]
fn conversion_rejects_missing_profile_identity() {
    let error = convert_q32_to_q24(
        &[FixedQ32::ZERO],
        Digest32::ZERO,
        digest("q32-profile"),
        digest("q24-profile"),
        digest("source"),
    )
    .expect_err("missing units must reject");
    assert_eq!(error, super::NduCoordinateConversionError::MissingDigest);
}
