use super::agent_timestamp;
use pretty_assertions::assert_eq;
use time::OffsetDateTime;
use time::UtcOffset;

#[test]
fn agent_timestamps_keep_utc_whole_seconds_without_rounding() {
    let cases = [
        (0, "1970-01-01T00:00:00Z"),
        (-1, "1969-12-31T23:59:59Z"),
        (999_999_999, "1970-01-01T00:00:00Z"),
        (1_000_000_000, "1970-01-01T00:00:01Z"),
        (1_709_251_199_123_456_789, "2024-02-29T23:59:59Z"),
        (-62_135_596_800_000_000_000, "0001-01-01T00:00:00Z"),
    ];

    for (nanoseconds, expected) in cases {
        let timestamp = OffsetDateTime::from_unix_timestamp_nanos(nanoseconds)
            .expect("valid timestamp fixture");
        assert_eq!(agent_timestamp(timestamp), expected);
        for offset_seconds in [-43_200, 19_800, 50_400] {
            let offset = UtcOffset::from_whole_seconds(offset_seconds).expect("valid UTC offset");
            assert_eq!(agent_timestamp(timestamp.to_offset(offset)), expected);
        }
    }
}
