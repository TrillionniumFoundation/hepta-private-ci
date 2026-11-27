use super::*;
use codex_utils_time::Timestamp;

#[test]
fn annotations_keep_timestamp_bytes_for_negative_leap_and_wide_dates() {
    use crate::model::Annotations;
    for (input, expected) in [
        (
            "1969-12-31T23:59:59.999999999Z",
            "1969-12-31T23:59:59.999999999+00:00",
        ),
        ("2016-12-31T23:59:60.100Z", "2016-12-31T23:59:60.100+00:00"),
        ("+200000-01-01T00:00:00Z", "+200000-01-01T00:00:00+00:00"),
        (
            "2025-01-12T15:00:58.000001Z",
            "2025-01-12T15:00:58.000001+00:00",
        ),
    ] {
        let timestamp = input.parse::<Timestamp>().unwrap();
        let value = Annotations::for_resource(/*priority*/ 0.5, timestamp);
        assert_eq!(value.last_modified.as_deref(), Some(expected));
        assert_eq!(
            Annotations::default()
                .with_timestamp(timestamp)
                .last_modified,
            value.last_modified
        );
    }
}

#[test]
fn clock_keeps_numeric_utc_offset() {
    let value = now_rfc3339();
    assert!(value.ends_with("+00:00"));
    assert!(value.parse::<Timestamp>().is_ok());
}

#[cfg(feature = "request-state")]
#[test]
fn request_state_clock_is_in_milliseconds() {
    let before = Timestamp::now().epoch_milliseconds();
    let value = now_unix_millis();
    let after = Timestamp::now().epoch_milliseconds();
    assert!(value >= before && value <= after);
}

#[cfg(any(feature = "client", feature = "server"))]
#[test]
fn timeout_text_keeps_iso_duration_and_overflow_fallback() {
    use std::time::Duration;
    for (value, expected) in [
        (Duration::ZERO, "P0D"),
        (Duration::from_secs(30), "PT30S"),
        (Duration::from_millis(1_500), "PT1.5S"),
        (Duration::from_nanos(1), "PT0.000000001S"),
        (Duration::from_secs(5_400), "PT5400S"),
        (Duration::new(/*secs*/ 1, /*nanos*/ 10), "PT1.00000001S"),
        (
            Duration::new(
                /*secs*/ 9_223_372_036_854_775,
                /*nanos*/ 807_000_000,
            ),
            "PT9223372036854775.807S",
        ),
        (
            Duration::new(
                /*secs*/ 9_223_372_036_854_775,
                /*nanos*/ 807_000_001,
            ),
            "P0D",
        ),
        (Duration::MAX, "P0D"),
    ] {
        assert_eq!(Iso8601Duration(value).to_string(), expected);
        let error = crate::service::ServiceError::Timeout { timeout: value };
        assert_eq!(
            error.to_string(),
            format!("request timeout after {expected}")
        );
    }
}
