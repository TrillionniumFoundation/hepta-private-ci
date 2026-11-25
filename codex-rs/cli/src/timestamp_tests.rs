use pretty_assertions::assert_eq;

use super::ParseError;
use super::parse_rfc3339;

#[test]
fn rfc3339_keeps_original_syntax_offsets_and_fraction_truncation() {
    for (input, expected) in [
        ("1970-01-01T00:00:00Z", (0, 0)),
        ("1970-01-01t01:30:00+01:30", (0, 0)),
        ("1969-12-31 23:59:59.123456789999z", (-1, 123_456_789)),
        ("1970-01-01T00:00:00\u{2212}00:01", (60, 0)),
        ("1970-01-01T00:00:60.125+00:01", (-1, 1_125_000_000)),
        ("1970-01-01T00:00:00-00:00", (0, 0)),
    ] {
        assert_eq!(parse_rfc3339(input), Ok(expected), "{input}");
    }
}

#[test]
fn rfc3339_keeps_original_rejection_categories_and_messages() {
    for (input, error, message) in [
        ("", ParseError::TooShort, "premature end of input"),
        (
            "1970-01-01T00:00:00.",
            ParseError::TooShort,
            "premature end of input",
        ),
        (
            "1970-01-01T00:00:00+00:",
            ParseError::TooShort,
            "premature end of input",
        ),
        (
            "1970-01-01_00:00:00Z",
            ParseError::Invalid,
            "input contains invalid characters",
        ),
        (
            "1970-01-01T00:00:00.Z",
            ParseError::Invalid,
            "input contains invalid characters",
        ),
        (
            "1970-01-01T00:00:00\u{ff0b}00:00",
            ParseError::Invalid,
            "input contains invalid characters",
        ),
        (
            "2025-02-29T00:00:00Z",
            ParseError::OutOfRange,
            "input is out of range",
        ),
        (
            "1970-01-01T25:00:00Z",
            ParseError::OutOfRange,
            "input is out of range",
        ),
        (
            "1970-01-01T00:00:61Z",
            ParseError::OutOfRange,
            "input is out of range",
        ),
        (
            "1970-01-01T00:00:00+24:00",
            ParseError::OutOfRange,
            "input is out of range",
        ),
        (
            "1970-01-01T00:00:00+00:60",
            ParseError::OutOfRange,
            "input is out of range",
        ),
        (
            "1970-01-01T00:00:00Z ",
            ParseError::TooLong,
            "trailing input",
        ),
        (
            "1970-01-01T00:00:00+24:00x",
            ParseError::TooLong,
            "trailing input",
        ),
    ] {
        assert_eq!(parse_rfc3339(input), Err(error), "{input}");
        assert_eq!(error.to_string(), message);
    }
}

#[test]
fn rfc3339_order_keeps_leap_seconds_nanos_and_offset_ties() {
    let before = parse_rfc3339("1970-01-01T00:00:59.999999999Z").unwrap();
    let leap = parse_rfc3339("1970-01-01T00:00:60.100000000Z").unwrap();
    let later_leap = parse_rfc3339("1970-01-01T00:00:60.100000001Z").unwrap();
    let after = parse_rfc3339("1970-01-01T00:01:00Z").unwrap();
    assert!(before < leap && leap < later_leap && later_leap < after);
    assert_eq!(leap, (59, 1_100_000_000));
    assert_eq!(
        leap,
        parse_rfc3339("1970-01-01T01:00:60.100000000999+01:00").unwrap()
    );
}

#[test]
fn rfc3339_four_digit_calendar_keeps_utc_boundary_crossings() {
    assert_eq!(
        parse_rfc3339("0000-01-01T00:00:00+23:59"),
        Ok((-62_167_305_540, 0))
    );
    assert_eq!(
        parse_rfc3339("9999-12-31T23:59:59-23:59"),
        Ok((253_402_387_139, 0))
    );
    for input in ["+10000-01-01T00:00:00Z", "-0001-01-01T00:00:00Z"] {
        assert_eq!(parse_rfc3339(input), Err(ParseError::Invalid));
    }
}
