//! Calendar interpretation of Windows TIME_ZONE_INFORMATION.
//! OS lookup is separate so calendar boundaries can be checked on every host.

use super::LocalTimeError;
use crate::MAX_YEAR;
use crate::MIN_YEAR;
use crate::Timestamp;

#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub(super) struct DateFields {
    pub year: u16,
    pub month: u16,
    pub weekday: u16,
    pub day: u16,
    pub hour: u16,
    pub minute: u16,
    pub second: u16,
    pub millisecond: u16,
}

pub(super) struct YearInformation {
    pub bias: i32,
    pub standard_bias: i32,
    pub daylight_bias: i32,
    pub standard_date: DateFields,
    pub daylight_date: DateFields,
}

pub(super) fn query_year(year: i32) -> u16 {
    year.clamp(1601, 30827) as u16
}

impl YearInformation {
    pub(super) fn offset(&self, value: Timestamp) -> Result<i32, LocalTimeError> {
        let bias_offset = |adjustment| {
            self.bias
                .checked_add(adjustment)
                .and_then(|minutes| minutes.checked_mul(60))
                .and_then(i32::checked_neg)
                .filter(|seconds| (-86_399..=86_399).contains(seconds))
                .ok_or(LocalTimeError::InvalidOffset)
        };
        let standard = bias_offset(self.standard_bias)?;
        let daylight = bias_offset(self.daylight_bias)?;
        // Querying the OS clamps the lookup year, but recurring transition
        // dates are resolved in the original timestamp year, as before.
        let year = value.calendar().year();
        let standard_date = self.standard_date.resolve(year)?;
        let daylight_date = self.daylight_date.resolve(year)?;
        let standard_utc =
            standard_date.map(|(seconds, nanos)| (seconds - i64::from(daylight), nanos));
        let daylight_utc =
            daylight_date.map(|(seconds, nanos)| (seconds - i64::from(standard), nanos));
        let instant = (value.seconds, value.nanoseconds);
        let offset = match (standard_utc, daylight_utc) {
            (Some(end), Some(start)) if start < end => {
                if start <= instant && instant < end {
                    daylight
                } else {
                    standard
                }
            }
            (Some(end), Some(start)) => {
                if end <= instant && instant < start {
                    standard
                } else {
                    daylight
                }
            }
            (Some(end), None) => {
                if instant < end {
                    daylight
                } else {
                    standard
                }
            }
            (None, Some(start)) => {
                if instant < start {
                    standard
                } else {
                    daylight
                }
            }
            (None, None) => standard,
        };
        Ok(offset)
    }
}

impl DateFields {
    fn resolve(&self, year: i32) -> Result<Option<(i64, u32)>, LocalTimeError> {
        if self.year == 0 && self.month == 0 {
            return Ok(None);
        }
        let invalid = LocalTimeError::Unavailable;
        if self.hour >= 24
            || self.minute >= 60
            || self.second >= 60
            || self.millisecond >= if self.second == 59 { 2_000 } else { 1_000 }
        {
            return Err(invalid);
        }
        let month = time::Month::try_from(u8::try_from(self.month).map_err(|_| invalid)?)
            .map_err(|_| invalid)?;
        let date = if self.year != 0 {
            time::Date::from_calendar_date(
                i32::from(self.year),
                month,
                u8::try_from(self.day).map_err(|_| invalid)?,
            )
            .map_err(|_| invalid)?
        } else {
            if !(MIN_YEAR..=MAX_YEAR).contains(&year)
                || self.weekday > 6
                || !(1..=5).contains(&self.day)
            {
                return Err(invalid);
            }
            let first =
                time::Date::from_calendar_date(year, month, /*day*/ 1).map_err(|_| invalid)?;
            let weekday = u16::from(first.weekday().number_days_from_sunday());
            let day = 1 + (self.weekday + 7 - weekday) % 7 + 7 * (self.day - 1);
            time::Date::from_calendar_date(year, month, day as u8)
                .or_else(|error| {
                    if self.day == 5 {
                        time::Date::from_calendar_date(year, month, (day - 7) as u8)
                    } else {
                        Err(error)
                    }
                })
                .map_err(|_| invalid)?
        };
        let second = date
            .with_hms(self.hour as u8, self.minute as u8, self.second as u8)
            .map_err(|_| invalid)?
            .assume_utc()
            .unix_timestamp();
        Ok(Some((second, u32::from(self.millisecond) * 1_000_000)))
    }
}

#[cfg(test)]
#[path = "local_windows_rules_tests.rs"]
mod tests;
