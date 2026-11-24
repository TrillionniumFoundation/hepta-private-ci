//! UTC instants at Codex's persisted and wire boundaries.
//!
//! Calendar validation and arithmetic use `time`; system/IANA zone lookup uses
//! Jiff. This boundary keeps the established 3/6/9-digit UTC serialization,
//! floor-based epoch conversion, and represented leap seconds. In particular,
//! cache signatures must not change merely because a date library changes.

mod calendar;
mod codec;
mod offset;

pub use codec::Precision;
pub use offset::OffsetTimestamp;
pub use time::Date as CivilDate;
pub use time::Duration as SignedDuration;
pub use time::PrimitiveDateTime as CivilDateTime;

use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::Serializer;
use std::fmt;
use std::ops::Add;
use std::ops::AddAssign;
use std::ops::Sub;
use std::str::FromStr;
use std::time::SystemTime;
use time::UtcOffset;

/// An instant whose wire representation and epoch rounding are stable.
///
/// A nanosecond field at least 1e9 represents the leap second immediately
/// following a `:59` second. It remains distinguishable from the next minute.
#[derive(Clone, Copy, Default, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct Timestamp {
    seconds: i64,
    nanoseconds: u32,
}

#[derive(Debug)]
pub struct ParseError(String);

impl fmt::Display for ParseError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.0)
    }
}

impl std::error::Error for ParseError {}

impl Timestamp {
    pub const UNIX_EPOCH: Self = Self {
        seconds: 0,
        nanoseconds: 0,
    };

    pub fn now() -> Self {
        SystemTime::now().into()
    }

    /// Constructs an instant with a floor-based second and a positive fraction.
    pub fn from_parts(secs: i64, nanos: u32) -> Option<Self> {
        if nanos >= 2_000_000_000 || (nanos >= 1_000_000_000 && secs.rem_euclid(60) != 59) {
            return None;
        }
        let datetime = time::OffsetDateTime::from_unix_timestamp(secs).ok()?;
        (-262_143..=262_142)
            .contains(&datetime.year())
            .then_some(Self {
                seconds: secs,
                nanoseconds: nanos,
            })
    }

    pub fn from_milliseconds(millis: i64) -> Option<Self> {
        Self::from_parts(
            millis.div_euclid(1_000),
            (millis.rem_euclid(1_000) as u32) * 1_000_000,
        )
    }

    pub fn from_civil(datetime: CivilDateTime) -> Self {
        let utc = datetime.assume_utc();
        Self::from_parts(utc.unix_timestamp(), utc.nanosecond()).expect("validated civil time")
    }

    pub fn from_ymd_hms(
        year: i32,
        month: u32,
        day: u32,
        hour: u32,
        min: u32,
        sec: u32,
    ) -> Option<Self> {
        let date = civil_date(year, month, day)?;
        let datetime = date
            .with_hms(
                hour.try_into().ok()?,
                min.try_into().ok()?,
                sec.try_into().ok()?,
            )
            .ok()?;
        Some(Self::from_civil(datetime))
    }

    pub fn epoch_seconds(&self) -> i64 {
        self.seconds
    }

    pub fn epoch_milliseconds(&self) -> i64 {
        self.seconds * 1_000 + i64::from(self.nanoseconds / 1_000_000)
    }

    pub fn with_nanoseconds(self, nanos: u32) -> Option<Self> {
        Self::from_parts(self.seconds, nanos)
    }

    pub fn civil(self) -> CivilDateTime {
        let utc = self.calendar();
        CivilDateTime::new(utc.date(), utc.time())
    }

    pub fn date(self) -> CivilDate {
        self.calendar().date()
    }
    pub fn year(self) -> i32 {
        self.calendar().year()
    }
    pub fn month(self) -> u32 {
        self.calendar().month() as u32
    }
    pub fn day(self) -> u32 {
        u32::from(self.calendar().day())
    }
    pub fn hour(self) -> u32 {
        u32::from(self.calendar().hour())
    }
    pub fn minute(self) -> u32 {
        u32::from(self.calendar().minute())
    }
    pub fn second(self) -> u32 {
        u32::from(self.calendar().second())
    }

    pub fn to_local(self) -> OffsetTimestamp {
        OffsetTimestamp::system_local(self)
    }

    pub fn format(self, pattern: &str) -> String {
        codec::format(self, UtcOffset::UTC, pattern, "UTC")
    }

    pub fn rfc3339(self) -> String {
        codec::rfc3339(
            self,
            UtcOffset::UTC,
            Precision::Auto,
            codec::UtcStyle::Numeric,
        )
    }

    pub fn rfc3339_utc(self, precision: Precision) -> String {
        codec::rfc3339(self, UtcOffset::UTC, precision, codec::UtcStyle::Zulu)
    }

    pub fn checked_add(self, duration: SignedDuration) -> Option<Self> {
        if self.nanoseconds < 1_000_000_000 {
            let value = self.calendar().checked_add(duration)?;
            return Self::from_parts(value.unix_timestamp(), value.nanosecond());
        }
        let fraction = i64::from(self.nanoseconds) + i64::from(duration.subsec_nanoseconds());
        let seconds = duration.whole_seconds();
        if seconds == 0 && fraction < 2_000_000_000 {
            return Self::from_parts(self.seconds, fraction.try_into().ok()?);
        }
        let correction = if seconds < 0 { 1 } else { 0 };
        let base = Self::from_parts(
            self.seconds.checked_add(correction)?,
            self.nanoseconds - 1_000_000_000,
        )?;
        base.checked_add(duration)
    }

    pub fn checked_sub(self, duration: SignedDuration) -> Option<Self> {
        self.checked_add(duration.checked_neg()?)
    }

    pub fn duration_since(self, earlier: Self) -> SignedDuration {
        let mut seconds = self.seconds - earlier.seconds;
        let left = self.seconds.rem_euclid(86_400);
        let right = earlier.seconds.rem_euclid(86_400);
        if left > right && earlier.nanoseconds >= 1_000_000_000 {
            seconds += 1;
        } else if left < right && self.nanoseconds >= 1_000_000_000 {
            seconds -= 1;
        }
        SignedDuration::new(
            seconds,
            self.nanoseconds as i32 - earlier.nanoseconds as i32,
        )
    }

    fn calendar(self) -> time::OffsetDateTime {
        time::OffsetDateTime::from_unix_timestamp(self.seconds)
            .expect("validated timestamp")
            .replace_nanosecond(self.nanoseconds % 1_000_000_000)
            .expect("normalized nanosecond")
    }
}

impl FromStr for Timestamp {
    type Err = ParseError;
    fn from_str(value: &str) -> Result<Self, Self::Err> {
        codec::parse(value, codec::ParseMode::Persisted).map(OffsetTimestamp::to_utc)
    }
}

impl Serialize for Timestamp {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.serialize_str(&self.rfc3339_utc(Precision::Auto))
    }
}

impl<'de> Deserialize<'de> for Timestamp {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        String::deserialize(deserializer)?
            .parse()
            .map_err(serde::de::Error::custom)
    }
}

impl fmt::Debug for Timestamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.rfc3339_utc(Precision::Auto))
    }
}

impl fmt::Display for Timestamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{} UTC",
            self.rfc3339_utc(Precision::Auto)
                .trim_end_matches('Z')
                .replace('T', " ")
        )
    }
}

impl From<SystemTime> for Timestamp {
    fn from(value: SystemTime) -> Self {
        let value = time::OffsetDateTime::from(value);
        Self::from_parts(value.unix_timestamp(), value.nanosecond())
            .expect("system time in supported range")
    }
}

impl From<Timestamp> for SystemTime {
    fn from(value: Timestamp) -> Self {
        let epoch_nanos = i128::from(value.seconds) * 1_000_000_000 + i128::from(value.nanoseconds);
        time::OffsetDateTime::from_unix_timestamp_nanos(epoch_nanos)
            .expect("validated instant")
            .into()
    }
}

impl Add<SignedDuration> for Timestamp {
    type Output = Self;
    fn add(self, rhs: SignedDuration) -> Self {
        self.checked_add(rhs).expect("timestamp addition in range")
    }
}
impl AddAssign<SignedDuration> for Timestamp {
    fn add_assign(&mut self, rhs: SignedDuration) {
        *self = *self + rhs;
    }
}
impl Sub<SignedDuration> for Timestamp {
    type Output = Self;
    fn sub(self, rhs: SignedDuration) -> Self {
        self.checked_sub(rhs)
            .expect("timestamp subtraction in range")
    }
}
impl Sub<Timestamp> for Timestamp {
    type Output = SignedDuration;
    fn sub(self, rhs: Self) -> SignedDuration {
        self.duration_since(rhs)
    }
}

pub fn civil_date(year: i32, month: u32, day: u32) -> Option<CivilDate> {
    if !(-262_143..=262_142).contains(&year) {
        return None;
    }
    CivilDate::from_calendar_date(
        year,
        time::Month::try_from(u8::try_from(month).ok()?).ok()?,
        day.try_into().ok()?,
    )
    .ok()
}

pub fn parse_utc(input: &str, pattern: &str) -> Result<Timestamp, ParseError> {
    calendar::parse_utc(input, pattern)
}

pub fn parse_date(input: &str, pattern: &str) -> Result<CivilDate, ParseError> {
    calendar::parse_date(input, pattern)
}

pub fn format_date(date: CivilDate, pattern: &str) -> String {
    Timestamp::from_civil(date.midnight()).format(pattern)
}

#[cfg(test)]
#[path = "time_tests.rs"]
mod tests;
