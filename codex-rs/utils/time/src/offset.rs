use crate::ParseError;
use crate::SignedDuration;
use crate::Timestamp;
use crate::codec;
use std::cmp::Ordering;
use std::fmt;
use std::hash::Hash;
use std::hash::Hasher;
use std::ops::Add;
use std::ops::Sub;
use time::UtcOffset;

/// An instant plus its display offset. Fixed-offset arithmetic retains that
/// offset; system-local arithmetic resolves the result through the zone rules.
#[derive(Clone, Copy)]
pub struct OffsetTimestamp {
    pub(crate) instant: Timestamp,
    pub(crate) offset: UtcOffset,
    pub(crate) system_local: bool,
}

impl OffsetTimestamp {
    pub(crate) fn system_local(instant: Timestamp) -> Self {
        let mut result = match Self::in_time_zone(instant, &jiff::tz::TimeZone::system()) {
            Ok(result) => result,
            Err(error) => panic!("validated timestamp and system time zone: {error:?}"),
        };
        result.system_local = true;
        result
    }

    pub fn now_local() -> Self {
        Timestamp::now().to_local()
    }

    pub fn parse_rfc3339(input: &str) -> Result<Self, ParseError> {
        codec::parse(input, codec::ParseMode::Rfc3339)
    }

    pub fn in_time_zone(instant: Timestamp, zone: &jiff::tz::TimeZone) -> Result<Self, ParseError> {
        let jiff = match jiff::Timestamp::new(
            instant.seconds,
            (instant.nanoseconds % 1_000_000_000) as i32,
        ) {
            Ok(timestamp) => timestamp,
            Err(_) => {
                // IANA data uses its first offset before recorded history and
                // recurring POSIX rules after the last transition. Gregorian
                // weekdays/leap years repeat after 400 years. Sample that far
                // future cycle (or the fixed prehistoric offset) within Jiff's
                // civil range without narrowing the persisted timestamp range.
                let year = if instant.year() < -9_999 {
                    -9_600
                } else {
                    9_200 + instant.year().rem_euclid(400)
                };
                let sample = instant
                    .calendar()
                    .replace_year(year)
                    .map_err(|error| ParseError(error.to_string()))?;
                jiff::Timestamp::new(sample.unix_timestamp(), /*nanosecond*/ 0)
                    .map_err(|error| ParseError(error.to_string()))?
            }
        };
        let offset = UtcOffset::from_whole_seconds(zone.to_offset(jiff).seconds())
            .map_err(|error| ParseError(error.to_string()))?;
        Ok(Self {
            instant,
            offset,
            system_local: false,
        })
    }

    /// Local civil times in a gap or fold remain invalid, matching `single`.
    pub fn from_local_ymd_hms(
        year: i32,
        month: u32,
        day: u32,
        hour: u32,
        min: u32,
        sec: u32,
    ) -> Option<Self> {
        let original = Timestamp::from_ymd_hms(year, month, day, hour, min, sec)?.civil();
        let sample_year = if year <= -9_999 {
            -9_600
        } else if year >= 9_999 {
            9_200 + year.rem_euclid(400)
        } else {
            year
        };
        let civil = jiff::civil::DateTime::new(
            sample_year.try_into().ok()?,
            month.try_into().ok()?,
            day.try_into().ok()?,
            hour.try_into().ok()?,
            min.try_into().ok()?,
            sec.try_into().ok()?,
            /*subsec_nanosecond*/ 0,
        )
        .ok()?;
        let zone = jiff::tz::TimeZone::system();
        let sampled = zone.to_ambiguous_timestamp(civil).unambiguous().ok()?;
        let offset = UtcOffset::from_whole_seconds(zone.to_offset(sampled).seconds()).ok()?;
        let actual = original.assume_offset(offset);
        let instant = Timestamp::from_parts(actual.unix_timestamp(), actual.nanosecond())?;
        Some(Self {
            instant,
            offset,
            system_local: true,
        })
    }

    pub fn to_utc(self) -> Timestamp {
        self.instant
    }
    pub fn to_local(self) -> Self {
        self.instant.to_local()
    }
    pub fn epoch_seconds(&self) -> i64 {
        self.instant.epoch_seconds()
    }
    pub fn epoch_milliseconds(&self) -> i64 {
        self.instant.epoch_milliseconds()
    }
    pub fn date(self) -> crate::CivilDate {
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

    pub fn format(self, pattern: &str) -> String {
        let offset_name = codec::format_offset(self.offset);
        codec::format(self.instant, self.offset, pattern, &offset_name)
    }
    pub fn rfc3339(self) -> String {
        codec::rfc3339(
            self.instant,
            self.offset,
            codec::Precision::Auto,
            codec::UtcStyle::Numeric,
        )
    }
    pub fn duration_since(self, earlier: Self) -> SignedDuration {
        self.instant.duration_since(earlier.instant)
    }
    fn calendar(self) -> time::OffsetDateTime {
        self.instant.calendar().to_offset(self.offset)
    }
}

impl fmt::Debug for OffsetTimestamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.rfc3339())
    }
}
impl fmt::Display for OffsetTimestamp {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.format("%Y-%m-%d %H:%M:%S%.f %:z"))
    }
}
impl PartialEq for OffsetTimestamp {
    fn eq(&self, other: &Self) -> bool {
        self.instant == other.instant
    }
}
impl Eq for OffsetTimestamp {}
impl PartialOrd for OffsetTimestamp {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}
impl Ord for OffsetTimestamp {
    fn cmp(&self, other: &Self) -> Ordering {
        self.instant.cmp(&other.instant)
    }
}
impl Hash for OffsetTimestamp {
    fn hash<H: Hasher>(&self, state: &mut H) {
        self.instant.hash(state);
    }
}
impl Add<SignedDuration> for OffsetTimestamp {
    type Output = Self;
    fn add(self, rhs: SignedDuration) -> Self {
        let instant = self.instant + rhs;
        if self.system_local {
            Self::system_local(instant)
        } else {
            Self { instant, ..self }
        }
    }
}
impl Sub<SignedDuration> for OffsetTimestamp {
    type Output = Self;
    fn sub(self, rhs: SignedDuration) -> Self {
        let instant = self.instant - rhs;
        if self.system_local {
            Self::system_local(instant)
        } else {
            Self { instant, ..self }
        }
    }
}
impl Sub<OffsetTimestamp> for OffsetTimestamp {
    type Output = SignedDuration;
    fn sub(self, rhs: Self) -> SignedDuration {
        self.duration_since(rhs)
    }
}
impl From<OffsetTimestamp> for std::time::SystemTime {
    fn from(value: OffsetTimestamp) -> Self {
        value.instant.into()
    }
}
