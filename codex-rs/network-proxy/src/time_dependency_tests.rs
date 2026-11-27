//! Exercise the maintained time implementations through the real Rama API.

use rama_http::headers::x_robots_tag::DirectiveDateTime;
use rama_http::layer::har::spec::Cookie;
use rama_http::layer::har::spec::Page;
use serde_json::json;

#[test]
fn har_timestamps_retain_legacy_wire_precision_and_offset_style() {
    for input in [
        "1970-01-01T00:00:00+00:00",
        "1969-12-31T23:59:59.100+00:00",
        "2000-02-29T12:34:56.123400+00:00",
        "2026-11-24T00:00:00.123456789+00:00",
        "2016-12-31T23:59:60.500+00:00",
    ] {
        let page: Page = serde_json::from_value(json!({
            "startedDateTime": input,
            "id": "synthetic-page",
            "title": "synthetic time boundary",
            "pageTimings": {},
        }))
        .expect("legacy HAR timestamp remains accepted");
        let serialized = serde_json::to_value(page).expect("HAR page serialization");
        assert_eq!(serialized["startedDateTime"], input);

        let cookie: Cookie = serde_json::from_value(json!({
            "name": "synthetic",
            "value": "public-fixture",
            "expires": input,
        }))
        .expect("legacy cookie timestamp remains accepted");
        let serialized = serde_json::to_value(cookie).expect("HAR cookie serialization");
        assert_eq!(serialized["expires"], input.replace("+00:00", "Z"));
    }
}

#[test]
fn crawler_expiry_rejects_invalid_calendar_input_without_panicking() {
    for (year, month, day, hour, minute, second) in [
        (2026, 2, 30, 0, 0, 0),
        (2026, 0, 1, 0, 0, 0),
        (2026, 1, 1, 24, 0, 0),
        (2026, 1, 1, 0, 60, 0),
        (2026, 1, 1, 0, 0, 60),
        (400_000, 1, 1, 0, 0, 0),
    ] {
        assert!(
            DirectiveDateTime::try_new_ymd_and_hms(year, month, day, hour, minute, second).is_err()
        );
    }
}

#[test]
fn crawler_expiry_uses_the_upstream_timezone_correction() {
    for (input, expected) in [
        ("Wednesday, 03-Dec-25 13:09:53 GMT", "2025-12-03T13:09:53Z"),
        ("Wednesday, 03-Dec-25 13:09:53 PST", "2025-12-03T21:09:53Z"),
        ("Wednesday, 03-Dec-25 13:09:53 GIT", "2025-12-03T22:09:53Z"),
    ] {
        let value: DirectiveDateTime = input.parse().expect("documented expiry syntax");
        assert_eq!(
            value
                .date_time()
                .rfc3339_utc(codex_utils_time::Precision::Auto),
            expected
        );
    }
}

#[test]
fn crawler_expiry_preserves_extended_years_and_represented_leap_seconds() {
    for input in ["2016-12-31T23:59:60.500+00:00"] {
        let value: DirectiveDateTime = input.parse().expect("established timestamp range");
        assert_eq!(value.to_string(), input);
    }
    let value = DirectiveDateTime::try_new_ymd(40_000, 1, 1)
        .expect("constructor retains the established calendar range");
    assert_eq!(value.date_time().rfc3339(), "+40000-01-01T00:00:00+00:00");
}
