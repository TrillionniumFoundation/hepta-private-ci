//! UTC timestamps at persisted and protocol boundaries.
//!
//! Calendar validation and arithmetic use `time`. This value preserves the
//! existing signed epoch range, leap-second representation, relaxed serde
//! input, and canonical 0/3/6/9 fractional digits used by signed cache files.
//! Local presentation retains the system time-zone policy over this full range.

use serde::Deserialize;
use serde::Deserializer;
use serde::Serialize;
use serde::Serializer;
use std::fmt;
use std::ops::Add;
use std::ops::Sub;
use std::str::FromStr;
use std::time::SystemTime;
use time::Duration;
use time::OffsetDateTime;

mod local;
mod parse;

pub use local::LocalFormat;
pub use local::LocalTimeError;
pub use local::LocalTimestamp;

const MIN_YEAR: i32 = -262_143;
const MAX_YEAR: i32 = 262_142;

/// A UTC instant with the historical persisted timestamp representation.
#[derive(Clone, Copy, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct Timestamp {
    seconds: i64,
    // Legacy leap seconds retain the preceding second and a fraction >= 1s.
    nanoseconds: u32,
}

/// Fractional precision for an explicitly formatted protocol timestamp.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum SecondsFormat {
    Secs,
    Millis,
    Micros,
    Nanos,
    AutoSi,
}

/// The UTC calendar layouts used by persisted paths and clock presentation.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum UtcFormat {
    Date,
    Time,
    DateTime,
    DateTimeUtc,
    DatePath,
    Compact,
    Filename,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ParseTimestampError;

impl fmt::Display for ParseTimestampError {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        output.write_str("invalid timestamp")
    }
}

impl std::error::Error for ParseTimestampError {}

impl Timestamp {
    pub const UNIX_EPOCH: Self = Self {
        seconds: 0,
        nanoseconds: 0,
    };

    pub fn now() -> Self {
        match Self::from_datetime(OffsetDateTime::now_utc()) {
            Some(timestamp) => timestamp,
            None => panic!("system clock is outside the supported timestamp range"),
        }
    }

    pub fn from_datetime(value: OffsetDateTime) -> Option<Self> {
        Self::from_timestamp(value.unix_timestamp(), value.nanosecond())
    }

    pub fn from_timestamp(seconds: i64, nanoseconds: u32) -> Option<Self> {
        let datetime = OffsetDateTime::from_unix_timestamp(seconds).ok()?;
        if !(MIN_YEAR..=MAX_YEAR).contains(&datetime.year())
            || nanoseconds >= 2_000_000_000
            || (nanoseconds >= 1_000_000_000 && seconds.rem_euclid(60) != 59)
        {
            return None;
        }
        Some(Self {
            seconds,
            nanoseconds,
        })
    }

    pub fn from_timestamp_millis(milliseconds: i64) -> Option<Self> {
        let seconds = milliseconds.div_euclid(1_000);
        let nanoseconds = u32::try_from(milliseconds.rem_euclid(1_000)).ok()? * 1_000_000;
        Self::from_timestamp(seconds, nanoseconds)
    }

    pub fn from_ymd_hms(
        year: i32,
        month: u32,
        day: u32,
        hour: u32,
        minute: u32,
        second: u32,
    ) -> Option<Self> {
        let (month, day, hour, minute, second) = (
            u8::try_from(month).ok()?,
            u8::try_from(day).ok()?,
            u8::try_from(hour).ok()?,
            u8::try_from(minute).ok()?,
            u8::try_from(second).ok()?,
        );
        let date =
            time::Date::from_calendar_date(year, time::Month::try_from(month).ok()?, day).ok()?;
        let datetime = date.with_hms(hour, minute, second).ok()?.assume_utc();
        Self::from_datetime(datetime)
    }

    pub fn from_system_time(value: SystemTime) -> Option<Self> {
        let nanos = match value.duration_since(SystemTime::UNIX_EPOCH) {
            Ok(duration) => i128::try_from(duration.as_nanos()).ok()?,
            Err(error) => -i128::try_from(error.duration().as_nanos()).ok()?,
        };
        let seconds = i64::try_from(nanos.div_euclid(1_000_000_000)).ok()?;
        let nanoseconds = u32::try_from(nanos.rem_euclid(1_000_000_000)).ok()?;
        Self::from_timestamp(seconds, nanoseconds)
    }

    /// Convert to the platform clock, normalizing an explicit leap second to
    /// the following second. Return `None` outside the platform clock's range.
    pub fn to_system_time(self) -> Option<SystemTime> {
        let nanos = i128::from(self.seconds) * 1_000_000_000 + i128::from(self.nanoseconds);
        let duration = std::time::Duration::new(
            u64::try_from(nanos.unsigned_abs() / 1_000_000_000).ok()?,
            u32::try_from(nanos.unsigned_abs() % 1_000_000_000).ok()?,
        );
        if nanos < 0 {
            SystemTime::UNIX_EPOCH.checked_sub(duration)
        } else {
            SystemTime::UNIX_EPOCH.checked_add(duration)
        }
    }

    pub fn timestamp(&self) -> i64 {
        self.seconds
    }

    pub fn timestamp_millis(&self) -> i64 {
        self.seconds * 1_000 + i64::from(self.nanoseconds / 1_000_000)
    }

    pub fn timestamp_nanos_opt(&self) -> Option<i64> {
        i64::try_from(i128::from(self.seconds) * 1_000_000_000 + i128::from(self.nanoseconds)).ok()
    }

    pub fn timestamp_subsec_nanos(&self) -> u32 {
        self.nanoseconds
    }

    pub fn with_nanosecond(self, nanoseconds: u32) -> Option<Self> {
        Self::from_timestamp(self.seconds, nanoseconds)
    }

    /// The calendar second containing this timestamp. Leap seconds retain
    /// their preceding second; use `to_rfc3339_opts` to display the `:60` field.
    pub fn calendar(&self) -> OffsetDateTime {
        match OffsetDateTime::from_unix_timestamp(self.seconds)
            .and_then(|calendar| calendar.replace_nanosecond(self.nanoseconds % 1_000_000_000))
        {
            Ok(calendar) => calendar,
            Err(_) => unreachable!("private timestamp fields were validated at construction"),
        }
    }

    pub fn checked_add(self, duration: Duration) -> Option<Self> {
        if self.nanoseconds < 1_000_000_000 {
            return Self::from_datetime(self.calendar().checked_add(duration)?);
        }
        // An explicitly represented leap second remains distinct while a
        // subsecond addition stays inside it. Leaving that boundary resumes
        // ordinary calendar arithmetic, with no implicit leap-second table.
        let seconds = duration.whole_seconds();
        let fraction = duration.subsec_nanoseconds();
        let combined = i64::from(self.nanoseconds) + i64::from(fraction);
        if seconds == 0 && combined < 2_000_000_000 {
            return Self::from_timestamp(self.seconds, u32::try_from(combined).ok()?);
        }
        let base = if seconds < 0 {
            self.calendar().checked_add(Duration::seconds(1))?
        } else {
            self.calendar()
        };
        Self::from_datetime(base.checked_add(duration)?)
    }

    pub fn checked_sub(self, duration: Duration) -> Option<Self> {
        self.checked_add(duration.checked_neg()?)
    }

    pub fn expires_after(self, duration: std::time::Duration) -> Option<Self> {
        self.checked_add(duration_from_std(duration)?)
    }

    pub fn signed_duration_since(self, earlier: Self) -> Duration {
        let mut seconds = self.seconds - earlier.seconds;
        // Preserve the arithmetic at an explicitly represented leap second,
        // including a timestamp pair on different calendar dates.
        let time_of_day = self.seconds.rem_euclid(86_400);
        let earlier_time_of_day = earlier.seconds.rem_euclid(86_400);
        if time_of_day > earlier_time_of_day && earlier.nanoseconds >= 1_000_000_000 {
            seconds += 1;
        } else if time_of_day < earlier_time_of_day && self.nanoseconds >= 1_000_000_000 {
            seconds -= 1;
        }
        Duration::seconds(seconds)
            + Duration::nanoseconds(i64::from(self.nanoseconds) - i64::from(earlier.nanoseconds))
    }

    /// Parse the strict network form; serde also accepts the historical
    /// relaxed spelling used in persisted authentication and cache files.
    pub fn parse_from_rfc3339(value: &str) -> Result<Self, ParseTimestampError> {
        parse::strict_timestamp(value).ok_or(ParseTimestampError)
    }

    pub fn parse_filename_timestamp(value: &str) -> Result<Self, ParseTimestampError> {
        parse::filename_timestamp(value).ok_or(ParseTimestampError)
    }

    /// Format a supported calendar layout without a fallible runtime format
    /// string. Canonical RFC3339 formatting has separate precision controls.
    pub fn format_utc(&self, layout: UtcFormat) -> String {
        let calendar = self.calendar();
        let year = calendar.year();
        let year = if (0..=9999).contains(&year) {
            format!("{year:04}")
        } else {
            format!("{year:+05}")
        };
        let month = u8::from(calendar.month());
        let day = calendar.day();
        let hour = calendar.hour();
        let minute = calendar.minute();
        let second = u32::from(calendar.second()) + self.nanoseconds / 1_000_000_000;
        match layout {
            UtcFormat::Date => format!("{year}-{month:02}-{day:02}"),
            UtcFormat::Time => format!("{hour:02}:{minute:02}:{second:02}"),
            UtcFormat::DateTime => {
                format!("{year}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02}")
            }
            UtcFormat::DateTimeUtc => {
                format!("{year}-{month:02}-{day:02} {hour:02}:{minute:02}:{second:02} UTC")
            }
            UtcFormat::DatePath => format!("{year}/{month:02}/{day:02}"),
            UtcFormat::Compact => {
                format!("{year}{month:02}{day:02}T{hour:02}{minute:02}{second:02}Z")
            }
            UtcFormat::Filename => {
                format!("{year}-{month:02}-{day:02}T{hour:02}-{minute:02}-{second:02}")
            }
        }
    }

    pub fn to_rfc3339(&self) -> String {
        self.to_rfc3339_opts(SecondsFormat::AutoSi, /*use_z*/ false)
    }

    pub fn to_rfc3339_opts(&self, precision: SecondsFormat, use_z: bool) -> String {
        Rfc3339 {
            timestamp: *self,
            precision,
            use_z,
        }
        .to_string()
    }
}

/// Preserve the existing refusal of durations outside the signed-millisecond
/// range at cache and remote-clock boundaries.
pub fn duration_from_std(duration: std::time::Duration) -> Option<Duration> {
    if duration.as_nanos() > i64::MAX as u128 * 1_000_000 {
        return None;
    }
    Duration::try_from(duration).ok()
}

/// Parse the date-only spelling used by persisted activity and announcement
/// records, retaining the existing calendar range and numeric padding rules.
pub fn parse_date(value: &str) -> Result<time::Date, ParseTimestampError> {
    Timestamp::parse_filename_timestamp(&format!("{value}T00-00-00"))
        .map(|timestamp| timestamp.calendar().date())
}

impl Add<Duration> for Timestamp {
    type Output = Self;
    fn add(self, duration: Duration) -> Self {
        match self.checked_add(duration) {
            Some(timestamp) => timestamp,
            None => panic!("timestamp addition is out of range"),
        }
    }
}

impl Sub<Duration> for Timestamp {
    type Output = Self;
    fn sub(self, duration: Duration) -> Self {
        match self.checked_sub(duration) {
            Some(timestamp) => timestamp,
            None => panic!("timestamp subtraction is out of range"),
        }
    }
}

impl Sub<Timestamp> for Timestamp {
    type Output = Duration;
    fn sub(self, earlier: Self) -> Duration {
        self.signed_duration_since(earlier)
    }
}

impl From<SystemTime> for Timestamp {
    fn from(value: SystemTime) -> Self {
        match Self::from_system_time(value) {
            Some(timestamp) => timestamp,
            None => panic!("system time is outside the supported timestamp range"),
        }
    }
}

impl FromStr for Timestamp {
    type Err = ParseTimestampError;
    fn from_str(value: &str) -> Result<Self, Self::Err> {
        parse::timestamp(value).ok_or(ParseTimestampError)
    }
}

impl fmt::Display for Timestamp {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        let canonical = self.to_rfc3339_opts(SecondsFormat::AutoSi, /*use_z*/ true);
        let (date, clock) = canonical.split_once('T').ok_or(fmt::Error)?;
        let clock = clock.strip_suffix('Z').ok_or(fmt::Error)?;
        write!(output, "{date} {clock} UTC")
    }
}

impl fmt::Debug for Timestamp {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(
            &Rfc3339 {
                timestamp: *self,
                precision: SecondsFormat::AutoSi,
                use_z: true,
            },
            output,
        )
    }
}

struct Rfc3339 {
    timestamp: Timestamp,
    precision: SecondsFormat,
    use_z: bool,
}

impl fmt::Display for Rfc3339 {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        let datetime = self.timestamp.calendar();
        let year = datetime.year();
        if (0..=9999).contains(&year) {
            write!(output, "{year:04}")?;
        } else {
            write!(output, "{year:+05}")?;
        }
        let month = u8::from(datetime.month());
        let day = datetime.day();
        let hour = datetime.hour();
        let minute = datetime.minute();
        let second = u32::from(datetime.second()) + self.timestamp.nanoseconds / 1_000_000_000;
        write!(
            output,
            "-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}"
        )?;
        let nanos = self.timestamp.nanoseconds % 1_000_000_000;
        let digits = match self.precision {
            SecondsFormat::Secs => 0,
            SecondsFormat::Millis => 3,
            SecondsFormat::Micros => 6,
            SecondsFormat::Nanos => 9,
            SecondsFormat::AutoSi if nanos == 0 => 0,
            SecondsFormat::AutoSi if nanos.is_multiple_of(1_000_000) => 3,
            SecondsFormat::AutoSi if nanos.is_multiple_of(1_000) => 6,
            SecondsFormat::AutoSi => 9,
        };
        match digits {
            3 => write!(output, ".{:03}", nanos / 1_000_000)?,
            6 => write!(output, ".{:06}", nanos / 1_000)?,
            9 => write!(output, ".{nanos:09}")?,
            _ => (),
        }
        output.write_str(if self.use_z { "Z" } else { "+00:00" })
    }
}

impl Serialize for Timestamp {
    fn serialize<S: Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
        serializer.collect_str(&Rfc3339 {
            timestamp: *self,
            precision: SecondsFormat::AutoSi,
            use_z: true,
        })
    }
}

impl<'de> Deserialize<'de> for Timestamp {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> Result<Self, D::Error> {
        struct TimestampVisitor;
        impl serde::de::Visitor<'_> for TimestampVisitor {
            type Value = Timestamp;
            fn expecting(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
                output.write_str("an RFC 3339 formatted date and time string")
            }
            fn visit_str<E: serde::de::Error>(self, value: &str) -> Result<Self::Value, E> {
                value.parse().map_err(E::custom)
            }
        }
        deserializer.deserialize_str(TimestampVisitor)
    }
}

#[cfg(test)]
#[path = "timestamp_tests.rs"]
mod tests;
