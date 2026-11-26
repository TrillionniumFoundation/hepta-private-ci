//! Windows keeps the original OS query and extrapolation year limits.

use super::LocalTimeError;
use super::windows_rules::DateFields;
use super::windows_rules::YearInformation;
use crate::Timestamp;
use std::mem::MaybeUninit;
use windows_sys::Win32::Foundation::SYSTEMTIME;
use windows_sys::Win32::System::Time::GetTimeZoneInformationForYear;
use windows_sys::Win32::System::Time::TIME_ZONE_INFORMATION;

impl From<SYSTEMTIME> for DateFields {
    fn from(value: SYSTEMTIME) -> Self {
        Self {
            year: value.wYear,
            month: value.wMonth,
            weekday: value.wDayOfWeek,
            day: value.wDay,
            hour: value.wHour,
            minute: value.wMinute,
            second: value.wSecond,
            millisecond: value.wMilliseconds,
        }
    }
}

pub(super) fn offset(value: Timestamp) -> Result<i32, LocalTimeError> {
    let year = value.calendar().year();
    let mut information = MaybeUninit::<TIME_ZONE_INFORMATION>::uninit();
    // SAFETY: the output is writable, the null zone selects this process's
    // system zone, and the OS output is read only after a successful call.
    let success = unsafe {
        GetTimeZoneInformationForYear(
            super::windows_rules::query_year(year),
            std::ptr::null(),
            information.as_mut_ptr(),
        )
    };
    if success == 0 {
        return Err(LocalTimeError::Unavailable);
    }
    // SAFETY: the successful OS call initialized TIME_ZONE_INFORMATION.
    let information = unsafe { information.assume_init() };
    YearInformation {
        bias: information.Bias,
        standard_bias: information.StandardBias,
        daylight_bias: information.DaylightBias,
        standard_date: information.StandardDate.into(),
        daylight_date: information.DaylightDate.into(),
    }
    .offset(value)
}
