use super::Timestamp;
use super::parse;
use pretty_assertions::assert_eq;

#[test]
fn preserves_signed_utc_spelling_and_relaxed_legacy_inputs() {
    let vectors = [
        ("2026-11-19T12:34:56Z", "2026-11-19T12:34:56Z"),
        ("2026-11-19T12:34:56.1Z", "2026-11-19T12:34:56.100Z"),
        ("2026-11-19T12:34:56.1234Z", "2026-11-19T12:34:56.123400Z"),
        (
            "2026-11-19T12:34:56.1234567Z",
            "2026-11-19T12:34:56.123456700Z",
        ),
        (
            "2026-11-19T12:34:56.12345678999Z",
            "2026-11-19T12:34:56.123456789Z",
        ),
        ("2026-11-19T12:34:56.0000000009Z", "2026-11-19T12:34:56Z"),
        (
            "2026-11-19T12:34:56.000000001Z",
            "2026-11-19T12:34:56.000000001Z",
        ),
        ("2026-11-19T13:34:56+01:00", "2026-11-19T12:34:56Z"),
        ("2026-11-19T11:34:56−01:00", "2026-11-19T12:34:56Z"),
        ("2026-11-19T13:34:56+01:: 00", "2026-11-19T12:34:56Z"),
        ("2026-11-19t12:34:56z", "2026-11-19T12:34:56Z"),
        (" 2026 - 11 -19 12 : 34 : 56 UTC\n", "2026-11-19T12:34:56Z"),
        ("2026-1-2 3:4:5+0000", "2026-01-02T03:04:05Z"),
        ("0000-1-1T0:0:0Z", "0000-01-01T00:00:00Z"),
        ("-0001-1-1T0:0:0Z", "-0001-01-01T00:00:00Z"),
        ("+10000-1-1T0:0:0Z", "+10000-01-01T00:00:00Z"),
        ("-262143-1-1T0:0:0Z", "-262143-01-01T00:00:00Z"),
        ("+262142-12-31T23:59:59Z", "+262142-12-31T23:59:59Z"),
        ("2016-12-31T23:59:60.1Z", "2016-12-31T23:59:60.100Z"),
        ("2017-01-01T00:59:60+01:00", "2016-12-31T23:59:60Z"),
    ];
    for (input, canonical) in vectors {
        let parsed: Timestamp = serde_json::from_value(serde_json::json!(input)).expect(input);
        assert_eq!(
            parsed.to_rfc3339_opts(super::SecondsFormat::AutoSi, /*use_z*/ true),
            canonical,
            "{input}"
        );
        assert_eq!(
            serde_json::to_value(parsed).expect(input),
            serde_json::json!(canonical)
        );
        let reread: Timestamp = serde_json::from_value(serde_json::json!(canonical)).expect(input);
        assert_eq!(parsed, reread, "{input}");
    }
}

#[test]
fn rejects_original_clock_and_syntax_failures() {
    for input in [
        "2026-11-19T12:34:56",
        "2026-11-19T12:34:56+00",
        "2026-11-19T12:34:56+0:00",
        "2026-11-19T12:34:56+00:0",
        "2026-11-19T12:34:56+24:00",
        "2026-11-19T12:34:56+00:60",
        "2026-11-19T12:34:56.Z",
        "2026-11-19T12:34:56 .1Z",
        "2026-11-19\t12:34:56Z",
        "2026-11-19T24:00:00Z",
        "2026-11-19T12:60:00Z",
        "2026-11-19T12:34:61Z",
        "2026-02-29T00:00:00Z",
        "2026-04-31T00:00:00Z",
        "10000-01-01T00:00:00Z",
        "+ 2026-01-01T00:00:00Z",
        "-262144-01-01T00:00:00Z",
        "+262143-01-01T00:00:00Z",
        "-262143-01-01T00:00:00+00:01",
        "+262142-12-31T23:59:59-00:01",
        "2026-11-19T12:34:56Z trailing",
    ] {
        assert!(parse::timestamp(input).is_none(), "{input}");
        assert!(
            serde_json::from_value::<Timestamp>(serde_json::json!(input)).is_err(),
            "{input}"
        );
    }
    for value in [
        serde_json::json!(0),
        serde_json::json!(null),
        serde_json::json!({}),
    ] {
        assert!(serde_json::from_value::<Timestamp>(value).is_err());
    }
}

#[test]
fn preserves_leap_second_and_pre_epoch_ordering() {
    for (earlier, later) in [
        ("1969-12-31T23:59:59.999999999Z", "1970-01-01T00:00:00Z"),
        ("2016-12-31T23:59:59.999999999Z", "2016-12-31T23:59:60Z"),
        ("2016-12-31T23:59:60.999999999Z", "2017-01-01T00:00:00Z"),
        ("2026-11-19T12:34:56.000001Z", "2026-11-19T12:34:56.001Z"),
    ] {
        assert!(parse::timestamp(earlier).expect(earlier) < parse::timestamp(later).expect(later));
    }
}

#[test]
fn preserves_signed_epoch_and_duration_refusals() {
    let before = Timestamp::from_timestamp(/*seconds*/ -1, /*nanoseconds*/ 999_999_999)
        .expect("pre-epoch timestamp");
    assert_eq!(before.timestamp(), -1);
    assert_eq!(before.timestamp_millis(), -1);
    assert_eq!(before.timestamp_subsec_nanos(), 999_999_999);

    assert_eq!(before.timestamp_nanos_opt(), Some(-1));

    assert_eq!(
        Timestamp::from_timestamp_millis(/*milliseconds*/ -1)
            .expect("signed millisecond")
            .timestamp(),
        -1
    );
    assert_eq!(Timestamp::from_timestamp(i64::MAX, /*nanoseconds*/ 0), None);
    assert_eq!(
        Timestamp::from_timestamp(/*seconds*/ 0, /*nanoseconds*/ 1_000_000_000),
        None
    );
    let maximum = std::time::Duration::from_millis(i64::MAX as u64);
    assert!(super::duration_from_std(maximum).is_some());
    assert!(super::duration_from_std(maximum + std::time::Duration::from_nanos(1)).is_none());
    let upper: Timestamp = "+262142-12-31T23:59:59.999999999Z"
        .parse()
        .expect("upper boundary");
    assert!(upper.checked_add(time::Duration::nanoseconds(1)).is_none());
    let lower: Timestamp = "-262143-01-01T00:00:00Z".parse().expect("lower boundary");
    assert!(lower.checked_sub(time::Duration::nanoseconds(1)).is_none());
}

#[test]
fn preserves_native_pre_epoch_time_at_common_precision() {
    let epoch = std::time::SystemTime::UNIX_EPOCH;
    // Windows SystemTime uses 100ns intervals. Check a negative fractional
    // instant that its clock can represent, independently of Timestamp's 1ns range.
    let clock_before = epoch - std::time::Duration::from_nanos(/*nanos*/ 100);
    let clock_timestamp = Timestamp::from_system_time(clock_before).expect("pre-epoch clock");
    assert_eq!(
        clock_timestamp,
        Timestamp::from_timestamp(/*seconds*/ -1, /*nanoseconds*/ 999_999_900)
            .expect("pre-epoch clock timestamp")
    );
    assert_eq!(clock_timestamp.timestamp(), -1);
    assert_eq!(clock_timestamp.timestamp_millis(), -1);
    assert_eq!(clock_timestamp.timestamp_nanos_opt(), Some(-100));
    assert_eq!(clock_timestamp.to_system_time(), Some(clock_before));

    // Always exercise the 1ns SystemTime request too. Compare with the actual
    // clock interval, retaining exact 1ns coverage on clocks that represent it.
    let requested_before = epoch - std::time::Duration::from_nanos(/*nanos*/ 1);
    let actual_before = Timestamp::from_system_time(requested_before).expect("actual clock");
    let observed_elapsed = epoch
        .duration_since(requested_before)
        .expect("clock subtraction cannot advance the epoch");
    assert_eq!(
        Timestamp::UNIX_EPOCH - actual_before,
        time::Duration::try_from(observed_elapsed).expect("signed clock interval")
    );
    assert_eq!(actual_before.to_system_time(), Some(requested_before));
}

#[test]
fn network_and_filename_parsers_retain_distinct_contracts() {
    let timestamp =
        Timestamp::parse_from_rfc3339("1969-12-31 23:59:59.1234z").expect("network form");
    assert_eq!(timestamp.to_rfc3339(), "1969-12-31T23:59:59.123400+00:00");
    assert_eq!(format!("{timestamp:?}"), "1969-12-31T23:59:59.123400Z");
    assert_eq!(timestamp.to_string(), "1969-12-31 23:59:59.123400 UTC");
    for input in [
        " 2026-11-19T12:34:56Z",
        "2026-1-2T3:4:5Z",
        "2026-11-19T12:34:56UTC",
    ] {
        assert!(input.parse::<Timestamp>().is_ok(), "{input}");
        assert!(Timestamp::parse_from_rfc3339(input).is_err(), "{input}");
    }
    let leap = Timestamp::parse_filename_timestamp("2016-12-31T23-59-60").expect("legacy filename");
    assert_eq!(
        leap.format_utc(super::UtcFormat::Filename),
        "2016-12-31T23-59-60"
    );
    assert!(Timestamp::parse_filename_timestamp("2016-12-31T23-59-60Z").is_err());
    assert!(Timestamp::parse_filename_timestamp("2016-12-31T23-59-60.1").is_err());
}

#[test]
fn system_time_conversion_preserves_signed_fractional_instants() {
    let epoch = std::time::SystemTime::UNIX_EPOCH;
    for (input, expected) in [
        (
            "1969-12-31T23:59:58.750Z",
            epoch - std::time::Duration::from_millis(/*millis*/ 1_250),
        ),
        (
            "1969-12-31T23:59:59.999999900Z",
            epoch - std::time::Duration::from_nanos(/*nanos*/ 100),
        ),
        ("1970-01-01T00:00:00Z", epoch),
        (
            "1970-01-01T00:00:00.000000100Z",
            epoch + std::time::Duration::from_nanos(/*nanos*/ 100),
        ),
        (
            "1970-01-01T00:00:00.250Z",
            epoch + std::time::Duration::from_millis(/*millis*/ 250),
        ),
        (
            "1970-01-01T00:00:01.250Z",
            epoch + std::time::Duration::from_millis(/*millis*/ 1_250),
        ),
    ] {
        let timestamp = Timestamp::parse_from_rfc3339(input).expect(input);
        assert_eq!(timestamp.to_system_time(), Some(expected), "{input}");
        assert_eq!(
            Timestamp::from_system_time(expected),
            Some(timestamp),
            "{input}"
        );
    }
}

#[test]
fn system_time_conversion_normalizes_explicit_leap_seconds() {
    let epoch = std::time::SystemTime::UNIX_EPOCH;
    for (input, normalized, expected) in [
        (
            "1969-12-31T23:59:60.250Z",
            "1970-01-01T00:00:00.250Z",
            epoch + std::time::Duration::from_millis(/*millis*/ 250),
        ),
        (
            "2016-12-31T23:59:60.123456700Z",
            "2017-01-01T00:00:00.123456700Z",
            epoch
                + std::time::Duration::new(/*secs*/ 1_483_228_800, /*nanos*/ 123_456_700),
        ),
    ] {
        let timestamp = Timestamp::parse_from_rfc3339(input).expect(input);
        let normalized = Timestamp::parse_from_rfc3339(normalized).expect(normalized);
        assert_eq!(timestamp.to_system_time(), Some(expected), "{input}");
        assert_eq!(
            Timestamp::from_system_time(expected),
            Some(normalized),
            "{input}"
        );
    }
}

#[test]
fn system_time_conversion_respects_platform_checked_range() {
    let epoch = std::time::SystemTime::UNIX_EPOCH;
    let lower: Timestamp = "-262143-01-01T00:00:00Z".parse().expect("lower boundary");
    let upper: Timestamp = "+262142-12-31T23:59:59.999999900Z"
        .parse()
        .expect("upper boundary");
    let lower_expected = epoch.checked_sub(std::time::Duration::from_secs(
        lower.timestamp().unsigned_abs(),
    ));
    let upper_expected = epoch.checked_add(std::time::Duration::new(
        u64::try_from(upper.timestamp()).expect("positive upper boundary"),
        upper.timestamp_subsec_nanos(),
    ));
    // SystemTime has a platform-specific range. Do not assume either boundary
    // is representable: the conversion must return the checked std result.
    assert_eq!(lower.to_system_time(), lower_expected);
    assert_eq!(upper.to_system_time(), upper_expected);
    if let Some(converted) = lower_expected {
        assert_eq!(Timestamp::from_system_time(converted), Some(lower));
    }
    if let Some(converted) = upper_expected {
        assert_eq!(Timestamp::from_system_time(converted), Some(upper));
    }
}

#[test]
fn system_time_conversion_preserves_signed_fraction_and_normalizes_leap_seconds() {
    let epoch = std::time::SystemTime::UNIX_EPOCH;
    for (input, expected) in [
        (
            "1969-12-31T23:59:59.500Z",
            epoch - std::time::Duration::from_millis(/*millis*/ 500),
        ),
        ("1970-01-01T00:00:00Z", epoch),
        (
            "1970-01-01T00:00:00.000000100Z",
            epoch + std::time::Duration::from_nanos(/*nanos*/ 100),
        ),
        (
            "1969-12-31T23:59:60.500Z",
            epoch + std::time::Duration::from_millis(/*millis*/ 500),
        ),
        (
            "2016-12-31T23:59:60.250Z",
            epoch
                + std::time::Duration::new(/*secs*/ 1_483_228_800, /*nanos*/ 250_000_000),
        ),
    ] {
        let timestamp = Timestamp::parse_from_rfc3339(input).expect(input);
        assert_eq!(timestamp.to_system_time(), Some(expected), "{input}");
    }
}
