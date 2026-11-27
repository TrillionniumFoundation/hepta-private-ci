use super::audit_timestamp;
use pretty_assertions::assert_eq;
use time::OffsetDateTime;
use time::UtcOffset;

#[test]
fn audit_timestamps_keep_exactly_three_utc_fraction_digits_without_rounding() {
    let cases = [
        (0, "1970-01-01T00:00:00.000Z"),
        (-1, "1969-12-31T23:59:59.999Z"),
        (123_456_789, "1970-01-01T00:00:00.123Z"),
        (999_999_999, "1970-01-01T00:00:00.999Z"),
        (1_000_000_000, "1970-01-01T00:00:01.000Z"),
        (1_709_251_199_123_456_789, "2024-02-29T23:59:59.123Z"),
        (-62_135_596_800_000_000_000, "0001-01-01T00:00:00.000Z"),
    ];

    for (nanoseconds, expected) in cases {
        let timestamp = OffsetDateTime::from_unix_timestamp_nanos(nanoseconds)
            .expect("valid timestamp fixture");
        assert_eq!(audit_timestamp(timestamp), expected);
        for offset_seconds in [-43_200, 19_800, 50_400] {
            let offset = UtcOffset::from_whole_seconds(offset_seconds).expect("valid UTC offset");
            assert_eq!(audit_timestamp(timestamp.to_offset(offset)), expected);
        }
    }
}
