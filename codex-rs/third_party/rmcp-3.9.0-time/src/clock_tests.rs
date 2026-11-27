use super::*;
use crate::model::Annotations;
use time::Date;
use time::Month;

#[test]
fn utc_format_keeps_the_established_fractional_precision() {
    for (nanos, expected) in [
        (0, "1970-01-01T00:00:00+00:00"),
        (100_000_000, "1970-01-01T00:00:00.100+00:00"),
        (10_000, "1970-01-01T00:00:00.000010+00:00"),
        (1, "1970-01-01T00:00:00.000000001+00:00"),
        (-1, "1969-12-31T23:59:59.999999999+00:00"),
        (-1_000_000, "1969-12-31T23:59:59.999+00:00"),
    ] {
        let timestamp = OffsetDateTime::from_unix_timestamp_nanos(nanos).unwrap();
        assert_eq!(format_utc_rfc3339(timestamp), expected);
        let annotations = Annotations::default().with_timestamp(timestamp);
        assert_eq!(
            serde_json::to_value(annotations).unwrap(),
            serde_json::json!({ "lastModified": expected }),
        );
    }
}

#[test]
fn utc_format_preserves_extended_years_and_calendar_boundaries() {
    for (year, month, day, expected) in [
        (-262_143, Month::January, 1, "-262143-01-01T00:00:00+00:00"),
        (-1, Month::January, 1, "-0001-01-01T00:00:00+00:00"),
        (0, Month::January, 1, "0000-01-01T00:00:00+00:00"),
        (2000, Month::February, 29, "2000-02-29T00:00:00+00:00"),
        (10_000, Month::January, 1, "+10000-01-01T00:00:00+00:00"),
        (262_142, Month::December, 31, "+262142-12-31T00:00:00+00:00"),
    ] {
        let timestamp = Date::from_calendar_date(year, month, day)
            .unwrap()
            .midnight()
            .assume_utc();
        assert_eq!(format_utc_rfc3339(timestamp), expected);
    }
}

#[test]
fn typed_timestamps_normalize_to_utc_across_the_date_boundary() {
    let timestamp = Date::from_calendar_date(/*year*/ 2024, Month::January, /*day*/ 1)
        .unwrap()
        .midnight()
        .assume_offset(UtcOffset::from_hms(/*hours*/ 5, /*minutes*/ 30, /*seconds*/ 0).unwrap());
    assert_eq!(format_utc_rfc3339(timestamp), "2023-12-31T18:30:00+00:00",);
}

#[test]
fn raw_last_modified_strings_keep_the_existing_wire_contract() {
    for value in [
        "2025-01-12",
        "2016-12-31T23:59:60Z",
        "2025-01-12T15:00:58.100Z",
        "not-a-date",
    ] {
        let json = serde_json::json!({ "lastModified": value });
        let annotations: Annotations = serde_json::from_value(json.clone()).unwrap();
        assert_eq!(serde_json::to_value(annotations).unwrap(), json);
    }
}

#[cfg(feature = "request-state")]
#[test]
fn millisecond_epochs_keep_floor_rounding_before_1970() {
    for (nanos, expected) in [
        (-1_000_000_001, -1_001),
        (-1_000_000, -1),
        (-1, -1),
        (0, 0),
        (999_999, 0),
        (1_000_000, 1),
    ] {
        let timestamp = OffsetDateTime::from_unix_timestamp_nanos(nanos).unwrap();
        assert_eq!(unix_millis(timestamp), expected);
    }
}

#[cfg(any(feature = "client", feature = "server"))]
#[test]
fn timeout_diagnostics_keep_seconds_fractions_and_overflow_behavior() {
    for (timeout, expected) in [
        (Duration::ZERO, "request timeout after P0D"),
        (
            Duration::from_nanos(/*nanos*/ 1),
            "request timeout after PT0.000000001S",
        ),
        (
            Duration::from_millis(/*millis*/ 100),
            "request timeout after PT0.1S",
        ),
        (
            Duration::from_secs(/*secs*/ 60),
            "request timeout after PT60S",
        ),
        (
            Duration::from_secs(/*secs*/ 86_400),
            "request timeout after PT86400S",
        ),
        (
            Duration::from_millis(i64::MAX as u64),
            "request timeout after PT9223372036854775.807S",
        ),
        (
            Duration::from_millis(i64::MAX as u64) + Duration::from_nanos(/*nanos*/ 1),
            "request timeout after P0D",
        ),
        (Duration::MAX, "request timeout after P0D"),
    ] {
        assert_eq!(
            crate::service::ServiceError::Timeout { timeout }.to_string(),
            expected,
        );
    }
}
