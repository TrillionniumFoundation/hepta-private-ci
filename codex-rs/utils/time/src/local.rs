//! Local presentation over the complete persisted calendar range.

use crate::MAX_YEAR;
use crate::MIN_YEAR;
use crate::Timestamp;
use std::fmt;
use time::OffsetDateTime;

#[cfg(unix)]
#[path = "local_unix.rs"]
mod system;

#[cfg(windows)]
#[path = "local_windows.rs"]
mod system;
#[cfg(any(windows, test))]
#[path = "local_windows_rules.rs"]
mod windows_rules;

#[cfg(all(
    target_arch = "wasm32",
    not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
))]
#[path = "local_wasm.rs"]
mod system;

/// The local calendar layouts used by the current protocol and UI callers.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalFormat {
    Date,
    Time,
    DayMonth,
    TimeOnDate,
    MonthDayTime,
    TwelveHourTime,
    OrdinalDateTime,
}

/// A time-zone query failed after configuration discovery completed.
/// These errors must not select a different zone or silently format UTC.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalTimeError {
    Unavailable,
    InvalidOffset,
    ProjectionOutOfRange,
    UnsupportedConfiguration,
}

impl fmt::Display for LocalTimeError {
    fn fmt(&self, output: &mut fmt::Formatter<'_>) -> fmt::Result {
        output.write_str(match self {
            Self::Unavailable => "unable to select local time type",
            Self::InvalidOffset => "local offset is outside the supported range",
            Self::ProjectionOutOfRange => "local calendar projection is out of range",
            Self::UnsupportedConfiguration => {
                "local time-zone configuration requires compatibility handling"
            }
        })
    }
}

impl std::error::Error for LocalTimeError {}

/// A presentation value retaining the UTC instant and its raw leap residue.
/// It does not implement serde and is never used for persisted timestamp bytes.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LocalTimestamp {
    utc: Timestamp,
    offset: i32,
}

impl LocalTimestamp {
    fn project(utc: Timestamp, offset: i32) -> Result<Self, LocalTimeError> {
        if !(-86_399..=86_399).contains(&offset) {
            return Err(LocalTimeError::InvalidOffset);
        }
        let local = Self { utc, offset };
        local.calendar()?;
        Ok(local)
    }

    fn calendar(&self) -> Result<OffsetDateTime, LocalTimeError> {
        let seconds = self
            .utc
            .seconds
            .checked_add(i64::from(self.offset))
            .ok_or(LocalTimeError::ProjectionOutOfRange)?;
        OffsetDateTime::from_unix_timestamp(seconds)
            .and_then(|calendar| calendar.replace_nanosecond(self.utc.nanoseconds % 1_000_000_000))
            .map_err(|_| LocalTimeError::ProjectionOutOfRange)
    }

    fn validated_calendar(&self) -> OffsetDateTime {
        match self.calendar() {
            Ok(calendar) => calendar,
            Err(_) => {
                unreachable!("private local projection fields were validated at construction")
            }
        }
    }

    /// The actual local date. As before, a local offset that crosses the
    /// historical minimum or maximum date makes date extraction out of range.
    pub fn date(&self) -> time::Date {
        let calendar = self.validated_calendar();
        assert!(
            (MIN_YEAR..=MAX_YEAR).contains(&calendar.year()),
            "Local time out of range for the supported calendar"
        );
        calendar.date()
    }

    /// Format one of the closed presentation layouts without reparsing a
    /// dynamic format string or losing the sign on expanded calendar years.
    pub fn format(&self, layout: LocalFormat) -> String {
        let calendar = self.validated_calendar();
        let year = calendar.year();
        let year = if (0..=9_999).contains(&year) {
            format!("{year:04}")
        } else {
            format!("{year:+05}")
        };
        let month = u8::from(calendar.month());
        let day = calendar.day();
        let hour = calendar.hour();
        let minute = calendar.minute();
        let months = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        ];
        let month_name = months[usize::from(month - 1)];
        let hour12 = match hour % 12 {
            0 => 12,
            value => value,
        };
        let meridiem = if hour < 12 { "AM" } else { "PM" };
        match layout {
            LocalFormat::Date => format!("{year}-{month:02}-{day:02}"),
            LocalFormat::Time => format!("{hour:02}:{minute:02}"),
            LocalFormat::DayMonth => format!("{day} {month_name}"),
            LocalFormat::TimeOnDate => {
                format!("{hour:02}:{minute:02} on {day} {month_name} {year}")
            }
            LocalFormat::MonthDayTime => {
                format!("{month_name} {day:2} {hour:02}:{minute:02}")
            }
            LocalFormat::TwelveHourTime => format!("{hour12}:{minute:02} {meridiem}"),
            LocalFormat::OrdinalDateTime => {
                let suffix = match day {
                    11..=13 => "th",
                    _ => match day % 10 {
                        1 => "st",
                        2 => "nd", // codespell:ignore
                        3 => "rd",
                        _ => "th",
                    },
                };
                format!("{month_name} {day}{suffix}, {year} {hour12}:{minute:02} {meridiem}")
            }
        }
    }
}

impl Timestamp {
    /// Query the system zone without concealing a query or projection failure.
    pub fn try_local(&self) -> Result<LocalTimestamp, LocalTimeError> {
        #[cfg(any(
            unix,
            windows,
            all(
                target_arch = "wasm32",
                not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
            )
        ))]
        let offset = system::offset(*self)?;
        #[cfg(not(any(
            unix,
            windows,
            all(
                target_arch = "wasm32",
                not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
            )
        )))]
        let offset = 0;
        LocalTimestamp::project(*self, offset)
    }

    /// Project the instant into the local zone, with the historical infallible
    /// call shape. Only a failure that previously prevented selecting an
    /// offset can panic; configuration discovery retains its fallback policy.
    pub fn local(&self) -> LocalTimestamp {
        match self.try_local() {
            Ok(local) => local,
            // Preserve the original infallible Local conversion contract.
            Err(error) => panic!("unable to select local time type: {error}"),
        }
    }

    pub fn format_local(&self, layout: LocalFormat) -> String {
        self.local().format(layout)
    }

    pub fn local_date(&self) -> time::Date {
        self.local().date()
    }
}

#[cfg(test)]
#[path = "local_tests.rs"]
mod tests;
