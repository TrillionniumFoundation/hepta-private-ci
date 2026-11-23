//! Preserve the original telemetry timestamp wire format at UTC boundaries.
use super::format_timestamp;
use pretty_assertions::assert_eq;
use time::OffsetDateTime;

#[test]
fn formats_exactly_three_utc_millisecond_digits() {
    for (seconds, nanos, expected) in [
        (0, 0, "1970-01-01T00:00:00.000Z"),
        (0, 123_987_654, "1970-01-01T00:00:00.123Z"),
        (-1, 999_999_999, "1969-12-31T23:59:59.999Z"),
    ] {
        let instant = OffsetDateTime::from_unix_timestamp(seconds)
            .unwrap_or_else(|_| panic!("valid timestamp fixture"))
            .replace_nanosecond(nanos)
            .unwrap_or_else(|_| panic!("valid nanosecond fixture"));
        assert_eq!(format_timestamp(instant), expected);
    }
}
