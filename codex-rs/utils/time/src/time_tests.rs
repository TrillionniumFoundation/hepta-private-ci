use super::*;
use pretty_assertions::assert_eq;

#[test]
fn persisted_timestamps_keep_fraction_width_and_epoch_floor() {
    for (input, encoded, seconds, millis) in [
        (
            "2026-01-01T00:00:00.1Z",
            "\"2026-01-01T00:00:00.100Z\"",
            1_767_225_600,
            1_767_225_600_100,
        ),
        (
            "1969-12-31T23:59:59.999999999Z",
            "\"1969-12-31T23:59:59.999999999Z\"",
            -1,
            -1,
        ),
        (
            "1970-01-01T05:30:00.0001+05:30",
            "\"1970-01-01T00:00:00.000100Z\"",
            0,
            0,
        ),
    ] {
        let value: Timestamp = input.parse().expect("timestamp");
        assert_eq!(
            (
                serde_json::to_string(&value).unwrap(),
                value.epoch_seconds(),
                value.epoch_milliseconds()
            ),
            (encoded.to_string(), seconds, millis)
        );
    }
}

#[test]
fn persisted_leap_seconds_and_expanded_years_round_trip() {
    for input in [
        "2016-12-31T23:59:60Z",
        "2016-12-31T23:59:60.123456789Z",
        "+10000-01-01T00:00:00Z",
        "-0001-01-01T00:00:00Z",
    ] {
        let encoded = format!("\"{input}\"");
        let value: Timestamp = serde_json::from_str(&encoded).expect("persisted timestamp");
        assert_eq!(serde_json::to_string(&value).unwrap(), encoded);
    }
    assert!(OffsetTimestamp::parse_rfc3339("+10000-01-01T00:00:00Z").is_err());
}

#[test]
fn represented_leap_second_arithmetic_preserves_its_extra_second() {
    let leap: Timestamp = "2016-12-31T23:59:60.500Z".parse().unwrap();
    assert_eq!(
        (leap - SignedDuration::seconds(1)).rfc3339_utc(Precision::Auto),
        "2016-12-31T23:59:59.500Z"
    );
    assert_eq!(
        (leap + SignedDuration::seconds(1)).rfc3339_utc(Precision::Auto),
        "2017-01-01T00:00:00.500Z"
    );
    assert_eq!(
        (leap - SignedDuration::milliseconds(750)).rfc3339_utc(Precision::Auto),
        "2016-12-31T23:59:59.750Z"
    );
    assert_eq!(
        (leap + SignedDuration::milliseconds(250)).rfc3339_utc(Precision::Auto),
        "2016-12-31T23:59:60.750Z"
    );
}

#[test]
fn system_zone_lookup_respects_dst_and_offset_arithmetic_is_explicit() {
    let zone = jiff::tz::TimeZone::get("America/New_York").expect("IANA zone");
    let before: Timestamp = "2024-03-10T06:30:00Z".parse().unwrap();
    let after = before + SignedDuration::hours(1);
    let local_before = OffsetTimestamp::in_time_zone(before, &zone).unwrap();
    let local_after = OffsetTimestamp::in_time_zone(after, &zone).unwrap();
    assert_eq!(local_before.rfc3339(), "2024-03-10T01:30:00-05:00");
    assert_eq!(local_after.rfc3339(), "2024-03-10T03:30:00-04:00");
    assert_eq!(
        (local_before + SignedDuration::hours(1)).rfc3339(),
        "2024-03-10T02:30:00-05:00"
    );
    assert_eq!(local_after.to_utc(), after);
    for (month, day, hour, minute) in [(3, 10, 2, 30), (11, 3, 1, 30)] {
        let civil = jiff::civil::DateTime::new(
            2024, month, day, hour, minute, /*second*/ 0, /*subsec_nanosecond*/ 0,
        )
        .unwrap();
        assert!(zone.to_ambiguous_timestamp(civil).unambiguous().is_err());
    }
}

#[test]
fn timestamp_parsers_reject_extra_time_zone_syntax() {
    for input in [
        "2026-11-24T12:34Z",
        "2026-11-24T12:34:56Z[UTC]",
        "2026-11-24T12:34:56+05:30:30",
    ] {
        assert!(input.parse::<Timestamp>().is_err());
        assert!(OffsetTimestamp::parse_rfc3339(input).is_err());
    }
    let long_fraction: Timestamp = "2026-11-24T12:34:56.123456789123Z".parse().unwrap();
    assert_eq!(
        long_fraction.rfc3339_utc(Precision::Auto),
        "2026-11-24T12:34:56.123456789Z"
    );
}

#[test]
fn calendar_formatting_preserves_expanded_year_and_leap_second() {
    let expanded: Timestamp = "+10000-02-29T12:34:56.100Z".parse().unwrap();
    assert_eq!(
        expanded.format("%Y-%m-%d %H:%M:%S%.f %Z"),
        "+10000-02-29 12:34:56.100 UTC"
    );
    let leap: Timestamp = "2016-12-31T23:59:60.100Z".parse().unwrap();
    assert_eq!(
        leap.format("%Y-%m-%dT%H-%M-%S%.3f"),
        "2016-12-31T23-59-60.100"
    );
    assert_eq!(
        parse_utc("2026-01-27T12-34-56", "%Y-%m-%dT%H-%M-%S").unwrap(),
        Timestamp::from_ymd_hms(
            /*year*/ 2026, /*month*/ 1, /*day*/ 27, /*hour*/ 12,
            /*min*/ 34, /*sec*/ 56
        )
        .unwrap()
    );
}

#[test]
fn persisted_input_keeps_relaxed_syntax_without_widening_the_rfc_boundary() {
    for input in [
        " 2026-1-2T1:2:3Z ",
        "2026-01-02 01:02:03 UTC",
        "2026-01-02T01:02:03 +0000",
    ] {
        let timestamp: Timestamp = input.parse().expect("legacy timestamp");
        assert_eq!(
            timestamp.rfc3339_utc(Precision::Auto),
            "2026-01-02T01:02:03Z"
        );
        assert!(OffsetTimestamp::parse_rfc3339(input).is_err());
    }
    for input in ["2026-01-02X01:02:03Z", "2026-01-02\t01:02:03Z"] {
        assert!(input.parse::<Timestamp>().is_err());
        assert!(OffsetTimestamp::parse_rfc3339(input).is_err());
    }
    assert_eq!(
        OffsetTimestamp::parse_rfc3339("2026-01-02T01:02:03−05:30")
            .unwrap()
            .rfc3339(),
        "2026-01-02T01:02:03-05:30",
    );
}

#[test]
fn numeric_calendar_inputs_preserve_padding_and_leap_rules() {
    assert_eq!(
        parse_utc("2016-12-31T23-59-60", "%Y-%m-%dT%H-%M-%S")
            .unwrap()
            .rfc3339_utc(Precision::Auto),
        "2016-12-31T23:59:60Z",
    );
    assert_eq!(
        parse_date(" 2026- 1- 2", "%Y-%m-%d").unwrap(),
        civil_date(/*year*/ 2026, /*month*/ 1, /*day*/ 2).unwrap()
    );
    for input in ["2026 -1-2", "2026-1-2 ", "2026-02-29", "+262143-01-01"] {
        assert!(parse_date(input, "%Y-%m-%d").is_err());
    }
}

#[test]
fn local_zone_arithmetic_refreshes_dst_without_changing_fixed_offset_arithmetic() {
    const WORKER: &str = "CODEX_TIME_ZONE_TEST_WORKER";
    if std::env::var(WORKER).as_deref() == Ok("new-york") {
        for (input, expected) in [
            ("2024-03-10T06:30:00Z", "2024-03-10T03:30:00-04:00"),
            ("2024-11-03T05:30:00Z", "2024-11-03T01:30:00-05:00"),
        ] {
            let local = input.parse::<Timestamp>().unwrap().to_local();
            assert_eq!(
                (local + SignedDuration::hours(/*hours*/ 1)).rfc3339(),
                expected
            );
        }
        let fixed = OffsetTimestamp::parse_rfc3339("2024-03-10T01:30:00-05:00").unwrap();
        assert_eq!(
            (fixed + SignedDuration::hours(/*hours*/ 1)).rfc3339(),
            "2024-03-10T02:30:00-05:00"
        );
        for (month, day, hour) in [(3, 10, 2), (11, 3, 1)] {
            assert!(
                OffsetTimestamp::from_local_ymd_hms(
                    /*year*/ 2024, month, day, hour, /*min*/ 30, /*sec*/ 0
                )
                .is_none()
            );
        }
        let expanded = OffsetTimestamp::from_local_ymd_hms(
            /*year*/ 10_000, /*month*/ 1, /*day*/ 1, /*hour*/ 7,
            /*min*/ 34, /*sec*/ 56,
        )
        .unwrap();
        assert_eq!(
            expanded.to_utc().rfc3339_utc(Precision::Auto),
            "+10000-01-01T12:34:56Z"
        );
        return;
    }
    // Set the zone only in a fresh child, before either library can cache it.
    // No process-global environment is mutated while the test runner has threads.
    let output = std::process::Command::new(std::env::current_exe().unwrap())
        .args([
            "--exact",
            "tests::local_zone_arithmetic_refreshes_dst_without_changing_fixed_offset_arithmetic",
            "--nocapture",
        ])
        .env("TZ", "America/New_York")
        .env(WORKER, "new-york")
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

#[test]
fn local_display_preserves_expanded_years_without_jiff_range_panics() {
    let zone = jiff::tz::TimeZone::get("America/New_York").unwrap();
    for (input, expected) in [
        ("+10000-01-01T12:34:56Z", "+10000-01-01T07:34:56-05:00"),
        ("+10000-07-01T12:34:56Z", "+10000-07-01T08:34:56-04:00"),
        ("-200000-07-01T12:34:56Z", "-200000-07-01T07:38:54-04:56"),
    ] {
        let instant = input.parse::<Timestamp>().unwrap();
        assert_eq!(
            OffsetTimestamp::in_time_zone(instant, &zone)
                .unwrap()
                .rfc3339(),
            expected
        );
    }
}
