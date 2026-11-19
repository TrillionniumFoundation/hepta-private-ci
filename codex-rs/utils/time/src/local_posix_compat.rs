//! The old parser accepted rules whose DST ordering changes between years.
//! The maintained parser now rejects those rules. This adapter is used only
//! for that specific rejection, retaining the former neighboring-year lookup.

use super::LocalTimeError;
use tz::UtcDateTime;
use tz::timezone::LocalTimeType;
use tz::timezone::TimeZoneSettings;

#[derive(Clone, Copy)]
pub(super) enum RuleSyntax {
    Posix,
    TzifV3,
}

pub(super) struct LegacyRule {
    pub standard: LocalTimeType,
    pub daylight: LocalTimeType,
    start: RuleDay,
    end: RuleDay,
}

struct RuleDay {
    day: Day,
    seconds: i32,
}

enum Day {
    Julian(u16),
    Ordinal(u16),
    MonthWeekday { month: u8, week: u8, weekday: u8 },
}

// The former grammar limited explicitly written offset hours to 23. This
// applies only to the standard/DST offsets before the first comma, never to
// transition clocks, binary TZif offsets, or the implicit one-hour DST shift.
pub(super) fn valid_offset_ranges(value: &str) -> bool {
    let head = value.split(',').next().unwrap_or(value);
    let Some((_, tail)) = designation(head) else {
        return true;
    };
    let length = tail
        .bytes()
        .take_while(|byte| byte.is_ascii_digit() || matches!(byte, b'+' | b'-' | b':'))
        .count();
    let standard = &tail[..length];
    let daylight = designation(&tail[length..])
        .map(|(_, offset)| offset)
        .unwrap_or("");
    [standard, daylight].into_iter().all(|offset| {
        if offset.is_empty() {
            return true;
        }
        let offset = offset.strip_prefix(['+', '-']).unwrap_or(offset);
        let hour = offset.split(':').next().unwrap_or(offset);
        hour.parse::<u32>().is_ok_and(|hour| hour <= 23)
    })
}

impl LegacyRule {
    pub(super) fn parse(input: &str, syntax: RuleSyntax) -> Option<Self> {
        let mut fields = input.split(',');
        let head = fields.next()?;
        let start = RuleDay::parse(fields.next()?, syntax)?;
        let end = RuleDay::parse(fields.next()?, syntax)?;
        if fields.next().is_some() {
            return None;
        }
        let (standard_name, tail) = designation(head)?;
        let length = tail
            .bytes()
            .take_while(|byte| byte.is_ascii_digit() || matches!(byte, b'+' | b'-' | b':'))
            .count();
        let standard_text = format!("{standard_name}{}", &tail[..length]);
        let standard = fixed_type(&standard_text)?;
        let (daylight_name, offset) = designation(&tail[length..])?;
        let daylight = if offset.is_empty() {
            let name = daylight_name
                .strip_prefix('<')
                .and_then(|name| name.strip_suffix('>'))
                .unwrap_or(daylight_name);
            LocalTimeType::new(
                standard.ut_offset().checked_add(3_600)?,
                /*is_dst*/ true,
                Some(name.as_bytes()),
            )
            .ok()?
        } else {
            let value = fixed_type(&format!("{daylight_name}{offset}"))?;
            LocalTimeType::new(
                value.ut_offset(),
                /*is_dst*/ true,
                Some(value.time_zone_designation().as_bytes()),
            )
            .ok()?
        };
        Some(Self {
            standard,
            daylight,
            start,
            end,
        })
    }

    pub(super) fn local_type(&self, seconds: i64) -> Result<&LocalTimeType, LocalTimeError> {
        let year = UtcDateTime::from_timespec(seconds, /*nanoseconds*/ 0)
            .map_err(|_| LocalTimeError::Unavailable)?
            .year();
        if !(i32::MIN + 2..=i32::MAX - 2).contains(&year) {
            return Err(LocalTimeError::Unavailable);
        }
        let start = |year| self.start.instant(year, self.standard.ut_offset());
        let end = |year| self.end.instant(year, self.daylight.ut_offset());
        let this_start = start(year)?;
        let this_end = end(year)?;
        let daylight = if this_start <= this_end {
            if seconds < this_start {
                if seconds < end(year - 1)? {
                    start(year - 1)? <= seconds
                } else {
                    false
                }
            } else if seconds < this_end {
                true
            } else if start(year + 1)? <= seconds {
                seconds < end(year + 1)?
            } else {
                false
            }
        } else if seconds < this_end {
            if seconds < start(year - 1)? {
                seconds < end(year - 1)?
            } else {
                true
            }
        } else if seconds < this_start {
            false
        } else if end(year + 1)? <= seconds {
            start(year + 1)? <= seconds
        } else {
            true
        };
        Ok(if daylight {
            &self.daylight
        } else {
            &self.standard
        })
    }
}

fn fixed_type(value: &str) -> Option<LocalTimeType> {
    // This is a grammar fragment, never a new system file lookup.
    let settings = TimeZoneSettings::new(&[], |_| {
        Err(std::io::Error::from(std::io::ErrorKind::NotFound).into())
    });
    let zone = settings.parse_posix_tz(value).ok()?;
    zone.as_ref().local_time_types().first().copied()
}

fn designation(value: &str) -> Option<(&str, &str)> {
    let length = if value.starts_with('<') {
        value.find('>')? + 1
    } else {
        value.bytes().take_while(u8::is_ascii_alphabetic).count()
    };
    if length == 0 {
        return None;
    }
    Some(value.split_at(length))
}

impl RuleDay {
    fn parse(value: &str, syntax: RuleSyntax) -> Option<Self> {
        let (date, clock) = match value.split_once('/') {
            Some((date, clock)) => (date, Some(clock)),
            None => (value, None),
        };
        let decimal = |value: &str| {
            if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
                return None;
            }
            value.parse::<u16>().ok()
        };
        let day = if let Some(date) = date.strip_prefix('J') {
            let day = decimal(date)?;
            if !(1..=365).contains(&day) {
                return None;
            }
            Day::Julian(day)
        } else if let Some(date) = date.strip_prefix('M') {
            let mut parts = date.split('.');
            let month = decimal(parts.next()?)?;
            let week = decimal(parts.next()?)?;
            let weekday = decimal(parts.next()?)?;
            if parts.next().is_some()
                || !(1..=12).contains(&month)
                || !(1..=5).contains(&week)
                || weekday > 6
            {
                return None;
            }
            Day::MonthWeekday {
                month: month as u8,
                week: week as u8,
                weekday: weekday as u8,
            }
        } else {
            let day = decimal(date)?;
            if day > 365 {
                return None;
            }
            Day::Ordinal(day)
        };
        let seconds = match clock {
            None => 7_200,
            Some(clock) => {
                let (sign, clock) = match syntax {
                    RuleSyntax::Posix => (1, clock),
                    RuleSyntax::TzifV3 => {
                        if let Some(clock) = clock.strip_prefix('-') {
                            (-1, clock)
                        } else {
                            (1, clock.strip_prefix('+').unwrap_or(clock))
                        }
                    }
                };
                let mut parts = clock.split(':');
                let hour = decimal(parts.next()?)?;
                let minute = match parts.next() {
                    Some(value) => decimal(value)?,
                    None => 0,
                };
                let second = match parts.next() {
                    Some(value) => decimal(value)?,
                    None => 0,
                };
                let max_hour = match syntax {
                    RuleSyntax::Posix => 24,
                    RuleSyntax::TzifV3 => 167,
                };
                if parts.next().is_some() || hour > max_hour || minute > 59 || second > 59 {
                    return None;
                }
                sign * (i32::from(hour) * 3_600 + i32::from(minute) * 60 + i32::from(second))
            }
        };
        Some(Self { day, seconds })
    }

    fn instant(&self, year: i32, offset: i32) -> Result<i64, LocalTimeError> {
        let midnight = |month| {
            UtcDateTime::new(
                year, month, /*month_day*/ 1, /*hour*/ 0, /*minute*/ 0,
                /*second*/ 0, /*nanoseconds*/ 0,
            )
            .map(|date| date.unix_time())
            .map_err(|_| LocalTimeError::Unavailable)
        };
        let leap = year % 4 == 0 && (year % 100 != 0 || year % 400 == 0);
        let seconds = match self.day {
            Day::Julian(day) => {
                midnight(/*month*/ 1)?
                    + (i64::from(day - 1) + i64::from(leap && day >= 60)) * 86_400
            }
            Day::Ordinal(day) => midnight(/*month*/ 1)? + i64::from(day) * 86_400,
            Day::MonthWeekday {
                month,
                week,
                weekday,
            } => {
                let first = midnight(month)?;
                let first_weekday = (first.div_euclid(86_400) + 4).rem_euclid(7);
                let mut day =
                    (i64::from(weekday) + 7 - first_weekday) % 7 + 7 * i64::from(week - 1);
                let days = match month {
                    2 => {
                        if leap {
                            29
                        } else {
                            28
                        }
                    }
                    4 | 6 | 9 | 11 => 30,
                    _ => 31,
                };
                if day >= days {
                    day -= 7;
                }
                first + day * 86_400
            }
        };
        Ok(seconds + i64::from(self.seconds) - i64::from(offset))
    }
}
