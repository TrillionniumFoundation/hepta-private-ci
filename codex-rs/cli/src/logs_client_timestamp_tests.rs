use super::Args;
use super::build_filter;
use super::formatter;
use super::parse_timestamp;
use clap::Parser;
use pretty_assertions::assert_eq;

#[test]
fn log_filters_keep_whole_i64_seconds_and_negative_fraction_floor() {
    for (input, expected) in [
        ("-9223372036854775808", i64::MIN),
        ("9223372036854775807", i64::MAX),
        ("+42", 42),
        ("1969-12-31T23:59:59.999999999Z", -1),
        ("1970-01-01T00:00:60.125+00:01", -1),
    ] {
        assert_eq!(parse_timestamp(input).unwrap(), expected);
    }
}

#[test]
fn log_filter_errors_keep_flag_context_and_original_parse_cause() {
    for flag in ["--from", "--to"] {
        let args = Args::try_parse_from(["codex-state-logs", flag, "invalid"]).unwrap();
        let error = build_filter(&args).unwrap_err();
        assert_eq!(
            format!("{error:#}"),
            format!(
                "failed to parse {flag}: expected RFC3339 or unix seconds, got invalid: premature end of input"
            )
        );
    }
}

#[test]
fn log_display_keeps_utc_millis_compact_time_and_leap_second() {
    assert_eq!(
        formatter::ts(
            /*ts*/ -1,
            /*ts_nanos*/ 999_999_999,
            /*compact*/ false
        ),
        "1969-12-31T23:59:59.999Z"
    );
    assert_eq!(
        formatter::ts(
            /*ts*/ 59,
            /*ts_nanos*/ 1_234_567_890,
            /*compact*/ false
        ),
        "1970-01-01T00:00:60.234Z"
    );
    assert_eq!(
        formatter::ts(
            /*ts*/ 59,
            /*ts_nanos*/ 1_234_567_890,
            /*compact*/ true
        ),
        "00:00:60"
    );
    assert_eq!(
        formatter::ts(/*ts*/ -1, /*ts_nanos*/ 0, /*compact*/ true),
        "23:59:59"
    );
}

#[test]
fn log_display_keeps_nanosecond_conversion_and_raw_fallback() {
    for nanos in [-1, 4_294_967_296] {
        assert_eq!(
            formatter::ts(/*ts*/ 0, nanos, /*compact*/ false),
            "1970-01-01T00:00:00.000Z"
        );
    }
    for (seconds, nanos, expected) in [
        (0, 1_000_000_000, "0.1000000000Z"),
        (59, 2_000_000_000, "59.2000000000Z"),
        (0, 4_294_967_295, "0.4294967295Z"),
        (i64::MAX, 0, "9223372036854775807.000000000Z"),
        (i64::MIN, 1, "-9223372036854775808.000000001Z"),
    ] {
        assert_eq!(formatter::ts(seconds, nanos, /*compact*/ false), expected);
        assert_eq!(formatter::ts(seconds, nanos, /*compact*/ true), expected);
    }
}

#[test]
fn log_display_keeps_signed_years_and_original_calendar_limits() {
    // Independent original calendar literals also exercise the cycle endpoints,
    // year zero, and the Gregorian century exception.
    for (seconds, expected) in [
        (-8_334_601_228_800, "-262143-01-01T00:00:00.000Z"),
        (-62_198_755_200, "-0001-01-01T00:00:00.000Z"),
        (-62_167_219_200, "0000-01-01T00:00:00.000Z"),
        (253_402_300_800, "+10000-01-01T00:00:00.000Z"),
        (8_210_235_340_800, "+262142-01-01T00:00:00.000Z"),
        (-62_162_121_600, "0000-02-29T00:00:00.000Z"),
        (-12_622_780_801, "1569-12-31T23:59:59.000Z"),
        (-12_622_780_800, "1570-01-01T00:00:00.000Z"),
        (-11_670_998_400, "1600-02-29T00:00:00.000Z"),
        (-2_203_891_201, "1900-02-28T23:59:59.000Z"),
        (-2_203_891_200, "1900-03-01T00:00:00.000Z"),
        (951_782_400, "2000-02-29T00:00:00.000Z"),
        (12_622_780_799, "2369-12-31T23:59:59.000Z"),
        (12_622_780_800, "2370-01-01T00:00:00.000Z"),
    ] {
        assert_eq!(
            formatter::ts(seconds, /*ts_nanos*/ 0, /*compact*/ false),
            expected
        );
    }
    for seconds in [-8_334_632_851_200, 8_210_266_876_800] {
        assert_eq!(
            formatter::ts(seconds, /*ts_nanos*/ 0, /*compact*/ false),
            format!("{seconds}.000000000Z")
        );
    }
}
