use std::fmt;

use time::Date;
use time::Month;
use time::OffsetDateTime;
use time::Time;

/// The four failures reachable through the CLI's existing RFC3339 parser.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) enum ParseError {
    OutOfRange,
    Invalid,
    TooShort,
    TooLong,
}

impl fmt::Display for ParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::OutOfRange => "input is out of range",
            Self::Invalid => "input contains invalid characters",
            Self::TooShort => "premature end of input",
            Self::TooLong => "trailing input",
        })
    }
}

impl std::error::Error for ParseError {}

/// Returns whole Unix seconds and the original nanosecond component.
///
/// A leap second retains the preceding `:59` second and at least one billion
/// nanoseconds. Comparing these pairs preserves UTC ordering, including leap
/// seconds and subsecond ties. This owner keeps the previous RFC3339 grammar
/// and error categories; it does not accept the wider separators of ISO8601.
pub(super) fn parse_rfc3339(value: &str) -> Result<(i64, u32), ParseError> {
    let bytes = value.as_bytes();
    if bytes.len() < 19 {
        return Err(ParseError::TooShort);
    }
    let year = i32::from(two_digits(&bytes[..2])?) * 100 + i32::from(two_digits(&bytes[2..4])?);
    if bytes[4] != b'-' {
        return Err(ParseError::Invalid);
    }
    let month = two_digits(&bytes[5..7])?;
    if bytes[7] != b'-' {
        return Err(ParseError::Invalid);
    }
    let day = two_digits(&bytes[8..10])?;
    let date = Date::from_calendar_date(
        year,
        Month::try_from(month).map_err(|_| ParseError::OutOfRange)?,
        day,
    )
    .map_err(|_| ParseError::OutOfRange)?;
    if !matches!(bytes[10], b'T' | b't' | b' ') {
        return Err(ParseError::Invalid);
    }
    let hour = two_digits(&bytes[11..13])?;
    if bytes[13] != b':' {
        return Err(ParseError::Invalid);
    }
    let minute = two_digits(&bytes[14..16])?;
    if bytes[16] != b':' {
        return Err(ParseError::Invalid);
    }
    let mut second = two_digits(&bytes[17..19])?;
    let mut nanos = if second == 60 {
        second = 59;
        1_000_000_000
    } else {
        0
    };
    let mut rest = &bytes[19..];
    if let Some(fraction) = rest.strip_prefix(b".") {
        match fraction.first() {
            None => return Err(ParseError::TooShort),
            Some(digit) if !digit.is_ascii_digit() => return Err(ParseError::Invalid),
            Some(_) => {}
        }
        let digits = fraction
            .iter()
            .take_while(|byte| byte.is_ascii_digit())
            .count();
        let mut scale = 100_000_000;
        for digit in fraction.iter().take(digits).take(9) {
            nanos += u32::from(*digit - b'0') * scale;
            scale /= 10;
        }
        rest = &fraction[digits..];
    }
    let clock = Time::from_hms(hour, minute, second).map_err(|_| ParseError::OutOfRange)?;
    let offset = if matches!(rest.first(), Some(b'Z' | b'z')) {
        if rest.len() != 1 {
            return Err(ParseError::TooLong);
        }
        0
    } else {
        let negative = if let Some(suffix) = rest.strip_prefix(b"+") {
            rest = suffix;
            false
        } else if let Some(suffix) = rest.strip_prefix(b"-") {
            rest = suffix;
            true
        } else if let Some(suffix) = rest.strip_prefix("\u{2212}".as_bytes()) {
            rest = suffix;
            true
        } else {
            return Err(if rest.is_empty() {
                ParseError::TooShort
            } else {
                ParseError::Invalid
            });
        };
        let hours = two_digits(rest.get(..2).ok_or(ParseError::TooShort)?)?;
        match rest.get(2) {
            None => return Err(ParseError::TooShort),
            Some(b':') => {}
            Some(_) => return Err(ParseError::Invalid),
        }
        let minutes = two_digits(rest.get(3..5).ok_or(ParseError::TooShort)?)?;
        if minutes > 59 {
            return Err(ParseError::OutOfRange);
        }
        if rest.len() != 5 {
            return Err(ParseError::TooLong);
        }
        if hours > 23 {
            return Err(ParseError::OutOfRange);
        }
        let seconds = i64::from(hours) * 3_600 + i64::from(minutes) * 60;
        if negative { -seconds } else { seconds }
    };
    Ok((
        date.with_time(clock).assume_utc().unix_timestamp() - offset,
        nanos,
    ))
}

fn two_digits(bytes: &[u8]) -> Result<u8, ParseError> {
    let [first, second] = bytes else {
        return Err(ParseError::TooShort);
    };
    if !first.is_ascii_digit() || !second.is_ascii_digit() {
        return Err(ParseError::Invalid);
    }
    Ok((*first - b'0') * 10 + *second - b'0')
}

/// A private calendar view; `within_cycle` is never the original Unix instant.
pub(super) struct UtcCalendar {
    pub(super) year: i32,
    pub(super) within_cycle: OffsetDateTime,
}

pub(super) fn checked_utc(seconds: i64) -> Option<UtcCalendar> {
    // 146097 Gregorian days repeat every 400 years. The maintained calendar
    // implementation only receives 1970..=2369, without global `large-dates`.
    const CYCLE_SECONDS: i64 = 12_622_780_800;
    let within_cycle =
        OffsetDateTime::from_unix_timestamp(seconds.rem_euclid(CYCLE_SECONDS)).ok()?;
    let year = seconds
        .div_euclid(CYCLE_SECONDS)
        .checked_mul(400)?
        .checked_add(i64::from(within_cycle.year()))?;
    if !(-262_143..=262_142).contains(&year) {
        return None;
    }
    Some(UtcCalendar {
        year: i32::try_from(year).ok()?,
        within_cycle,
    })
}

pub(super) fn format_year(year: i32) -> String {
    if (0..=9_999).contains(&year) {
        format!("{year:04}")
    } else {
        format!("{year:+05}")
    }
}

#[cfg(test)]
#[path = "timestamp_tests.rs"]
mod tests;
