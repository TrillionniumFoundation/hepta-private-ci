//! UTC timestamps with stable persisted and signed wire representations.
//!
//! The wire codec preserves the previous timestamp serializer's spelling and precision.
//! Leap-second strings have a separate carrier: converting them to an ordinary instant
//! returns an error instead of silently changing a signed value or its second.

use std::cmp::Ordering;
use std::fmt;

use time::OffsetDateTime;
use time::UtcOffset;

mod format;
mod parse;
pub mod serde;

#[cfg(test)]
#[path = "codec_tests.rs"]
mod tests;

// Preserve the range of the previous UTC timestamp constructors and serializer.
const MIN_UNIX_SECONDS: i64 = -8_334_601_228_800;
const MAX_UNIX_SECONDS: i64 = 8_210_266_876_799;

/// Fractional-second precision. Fixed precisions truncate rather than round.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Precision {
    Seconds,
    Millis,
    Micros,
    Nanos,
    /// Use no fraction, or exactly three, six, or nine digits, without losing precision.
    AutoSi,
}

/// The spelling of a zero UTC offset in the serialized timestamp.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UtcSuffix {
    Z,
    Offset,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TimestampError {
    InvalidSyntax,
    OutOfRange,
    InvalidNanosecond,
    /// A leap second cannot be represented faithfully by `OffsetDateTime`.
    UnrepresentableLeapSecond,
}

impl fmt::Display for TimestampError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(match self {
            Self::InvalidSyntax => "invalid timestamp syntax",
            Self::OutOfRange => "timestamp component or instant is outside the supported range",
            Self::InvalidNanosecond => "invalid timestamp nanosecond component",
            Self::UnrepresentableLeapSecond => {
                "leap-second timestamp cannot be represented as an ordinary instant"
            }
        })
    }
}

impl std::error::Error for TimestampError {}

/// A timestamp's legacy canonical UTC wire value, including an explicit leap second.
///
/// This type is for data that must be reserialized byte-for-byte after canonicalization,
/// such as authenticated cache fields. It deliberately has no general ordering or arithmetic
/// implementation. Use `compare_to_instant` for existing expiry comparisons, or require an
/// ordinary instant explicitly with `try_into_instant` before scheduling.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct CanonicalUtcTimestamp {
    // For a leap second, this is the preceding :59 with the original fractional part.
    value: OffsetDateTime,
    leap_second: bool,
}

impl CanonicalUtcTimestamp {
    /// Parse the previous serde timestamp grammar, then normalize its wire value to UTC.
    ///
    /// This includes signed extended years, surrounding whitespace, short numeric date
    /// components, `UTC`, and offsets without a colon. Extra fractional digits are truncated
    /// after the ninth digit, matching the previous parser.
    pub fn parse_legacy(value: &str) -> Result<Self, TimestampError> {
        parse::parse(value, parse::Grammar::LegacySerde)
    }

    pub fn from_instant(value: OffsetDateTime) -> Result<Self, TimestampError> {
        check_seconds(value.unix_timestamp())?;
        Ok(Self {
            value: value.to_offset(UtcOffset::UTC),
            leap_second: false,
        })
    }

    /// Preserve a persisted timestamp's original epoch parts, including a leap second.
    ///
    /// The leap representation is valid only on a `:59` second with nanoseconds in
    /// 1,000,000,000..2,000,000,000. Ordinary instant construction still rejects it.
    pub fn from_unix_parts(seconds: i64, nanos: u32) -> Result<Self, TimestampError> {
        check_seconds(seconds)?;
        let leap_second = nanos >= 1_000_000_000;
        if nanos >= 2_000_000_000 || (leap_second && seconds.rem_euclid(60) != 59) {
            return Err(TimestampError::InvalidNanosecond);
        }
        Ok(Self {
            value: from_unix_parts(seconds, nanos % 1_000_000_000)?,
            leap_second,
        })
    }

    /// Format the preserved wire timestamp at the requested precision, including `:60`.
    pub fn format(self, precision: Precision, suffix: UtcSuffix) -> String {
        format::format(self, precision, suffix)
    }

    /// Format the canonical UTC string with zero, three, six, or nine fractional digits.
    pub fn canonical_wire(self) -> String {
        self.format(Precision::AutoSi, UtcSuffix::Z)
    }

    /// Preserve the previous UTC timestamp ordering against an ordinary instant.
    ///
    /// A leap second sorts after every ordinary fraction of its preceding `:59` second
    /// and before the following second. Adding its extra nanoseconds to an epoch count
    /// would change that ordering, so the seconds and subsecond fields stay separate.
    pub fn compare_to_instant(self, other: OffsetDateTime) -> Ordering {
        let nanos = self.value.nanosecond() + u32::from(self.leap_second) * 1_000_000_000;
        (self.value.unix_timestamp(), nanos).cmp(&(other.unix_timestamp(), other.nanosecond()))
    }

    /// Refuse to normalize or truncate a leap second into a different ordinary instant.
    pub fn try_into_instant(self) -> Result<OffsetDateTime, TimestampError> {
        if self.leap_second {
            return Err(TimestampError::UnrepresentableLeapSecond);
        }
        Ok(self.value)
    }
}

/// Parse the strict RFC 3339 input grammar and normalize the instant to UTC.
///
/// As in the previous RFC 3339 parser, lowercase `t`/`z`, one space in place of `T`,
/// a Unicode minus sign in the offset, and extra fractional digits are accepted.
/// Signed extended years and the relaxed serde grammar require `parse_legacy` instead.
/// An explicit `:60` returns `UnrepresentableLeapSecond` and is never normalized.
pub fn parse_rfc3339_utc(value: &str) -> Result<OffsetDateTime, TimestampError> {
    parse::parse(value, parse::Grammar::Rfc3339)?.try_into_instant()
}

/// Construct an ordinary UTC instant from floor-based epoch seconds and nanoseconds.
///
/// The previous constructor encoded leap seconds as 1,000,000,000..2,000,000,000
/// nanoseconds on a `:59` second. Those inputs now return `UnrepresentableLeapSecond`.
/// Other nanosecond values at or above 1,000,000,000 remain invalid.
pub fn from_unix_parts(seconds: i64, nanos: u32) -> Result<OffsetDateTime, TimestampError> {
    check_seconds(seconds)?;
    if nanos >= 1_000_000_000 {
        return Err(if nanos < 2_000_000_000 && seconds.rem_euclid(60) == 59 {
            TimestampError::UnrepresentableLeapSecond
        } else {
            TimestampError::InvalidNanosecond
        });
    }
    OffsetDateTime::from_unix_timestamp(seconds)
        .map_err(|_| TimestampError::OutOfRange)?
        .replace_nanosecond(nanos)
        .map_err(|_| TimestampError::InvalidNanosecond)
}

/// Construct a UTC instant from signed epoch milliseconds, including negative fractions.
pub fn from_unix_millis(millis: i64) -> Result<OffsetDateTime, TimestampError> {
    // The Euclidean remainder is always in 0..1000, including before the epoch.
    let nanos = millis.rem_euclid(1_000) as u32 * 1_000_000;
    from_unix_parts(millis.div_euclid(1_000), nanos)
}

/// Return epoch milliseconds rounded down, including for instants before the epoch.
pub fn unix_millis_floor(value: OffsetDateTime) -> i64 {
    value.unix_timestamp() * 1_000 + i64::from(value.nanosecond() / 1_000_000)
}

pub fn format_rfc3339_utc(
    value: OffsetDateTime,
    precision: Precision,
    suffix: UtcSuffix,
) -> Result<String, TimestampError> {
    Ok(format::format(
        CanonicalUtcTimestamp::from_instant(value)?,
        precision,
        suffix,
    ))
}

fn check_seconds(seconds: i64) -> Result<(), TimestampError> {
    if !(MIN_UNIX_SECONDS..=MAX_UNIX_SECONDS).contains(&seconds) {
        return Err(TimestampError::OutOfRange);
    }
    Ok(())
}
