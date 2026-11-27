use super::LocalFormat;
use super::LocalTimeError;
use super::LocalTimestamp;
use crate::Timestamp;
use pretty_assertions::assert_eq;

#[test]
fn expanded_and_negative_years_keep_local_calendar_layouts() {
    let layouts = [
        LocalFormat::Date,
        LocalFormat::Time,
        LocalFormat::DayMonth,
        LocalFormat::TimeOnDate,
        LocalFormat::MonthDayTime,
        LocalFormat::TwelveHourTime,
        LocalFormat::OrdinalDateTime,
    ];
    for (input, offset, expected) in [
        (
            "+10000-06-01T12:00:00Z",
            0,
            [
                "+10000-06-01",
                "12:00",
                "1 Jun",
                "12:00 on 1 Jun +10000",
                "Jun  1 12:00",
                "12:00 PM",
                "Jun 1st, +10000 12:00 PM",
            ],
        ),
        (
            "0000-01-01T00:00:00Z",
            -3_600,
            [
                "-0001-12-31",
                "23:00",
                "31 Dec",
                "23:00 on 31 Dec -0001",
                "Dec 31 23:00",
                "11:00 PM",
                "Dec 31st, -0001 11:00 PM",
            ],
        ),
        (
            "2024-01-11T00:45:00Z",
            20_700,
            [
                "2024-01-11",
                "06:30",
                "11 Jan",
                "06:30 on 11 Jan 2024",
                "Jan 11 06:30",
                "6:30 AM",
                "Jan 11th, 2024 6:30 AM",
            ],
        ),
    ] {
        let utc: Timestamp = input.parse().expect(input);
        let local = LocalTimestamp::project(utc, offset).expect(input);
        let actual: Vec<_> = layouts
            .into_iter()
            .map(|layout| local.format(layout))
            .collect();
        assert_eq!(actual, expected, "{input}");
        assert_eq!(local.utc, utc);
    }
}

#[test]
fn local_projection_preserves_signed_leap_second_storage() {
    for input in ["2016-12-31T23:59:60.500Z", "1969-12-31T23:59:59.999999999Z"] {
        let utc: Timestamp = input.parse().expect(input);
        let original = serde_json::to_string(&utc).expect("serialize UTC");
        for offset in [-86_399, -18_000, 0, 19_845, 86_399] {
            let local = LocalTimestamp::project(utc, offset).expect("local projection");
            assert_eq!(
                serde_json::to_string(&local.utc).expect("serialize after projection"),
                original
            );
            assert_eq!(
                local.utc.timestamp_subsec_nanos(),
                utc.timestamp_subsec_nanos()
            );
        }
    }
}

#[test]
fn date_extraction_keeps_historical_calendar_boundary() {
    for (input, offset, date_text) in [
        ("-262143-01-01T00:00:00Z", -1, "-262144-12-31"),
        ("+262142-12-31T23:59:59Z", 1, "+262143-01-01"),
    ] {
        let local = LocalTimestamp::project(input.parse().expect(input), offset)
            .expect("buffer projection");
        assert_eq!(local.format(LocalFormat::Date), date_text);
        assert!(std::panic::catch_unwind(|| local.date()).is_err());
    }
    let utc: Timestamp = "+10000-06-01T12:00:00Z".parse().expect("expanded year");
    assert_eq!(
        LocalTimestamp::project(utc, /*offset*/ 0)
            .expect("projection")
            .date()
            .year(),
        10_000
    );
}

#[test]
fn local_offsets_outside_one_day_are_rejected() {
    let epoch = Timestamp::from_timestamp(/*seconds*/ 0, /*nanoseconds*/ 0).expect("epoch");
    for offset in [i32::MIN, -86_400, 86_400, i32::MAX] {
        assert_eq!(
            LocalTimestamp::project(epoch, offset),
            Err(LocalTimeError::InvalidOffset)
        );
    }
}

#[cfg(windows)]
#[test]
fn windows_local_projection_matches_native_year_rules() {
    use std::mem::MaybeUninit;
    use windows_sys::Win32::Foundation::SYSTEMTIME;
    use windows_sys::Win32::System::Time::GetTimeZoneInformationForYear;
    use windows_sys::Win32::System::Time::SystemTimeToTzSpecificLocalTime;
    use windows_sys::Win32::System::Time::TIME_ZONE_INFORMATION;

    for year in [
        1601, 1970, 1999, 2000, 2024, 2026, 2038, 9999, 10_000, 30_827,
    ] {
        let mut information = MaybeUninit::<TIME_ZONE_INFORMATION>::uninit();
        // SAFETY: writable output, system zone selected, initialization checked.
        assert_ne!(
            unsafe {
                GetTimeZoneInformationForYear(year, std::ptr::null(), information.as_mut_ptr())
            },
            0
        );
        // SAFETY: the preceding successful OS call initialized the structure.
        let information = unsafe { information.assume_init() };
        for month in 1..=12 {
            for day in [2, 15, 28] {
                for hour in [0, 6, 12, 18, 23] {
                    let source = SYSTEMTIME {
                        wYear: year,
                        wMonth: month,
                        wDayOfWeek: 0,
                        wDay: day,
                        wHour: hour,
                        wMinute: 30,
                        wSecond: 0,
                        wMilliseconds: 0,
                    };
                    let mut target = MaybeUninit::<SYSTEMTIME>::uninit();
                    // SAFETY: all inputs are initialized and output is writable.
                    assert_ne!(
                        unsafe {
                            SystemTimeToTzSpecificLocalTime(
                                &information,
                                &source,
                                target.as_mut_ptr(),
                            )
                        },
                        0
                    );
                    // SAFETY: the successful OS conversion initialized target.
                    let target = unsafe { target.assume_init() };
                    let instant = time::Date::from_calendar_date(
                        i32::from(year),
                        time::Month::try_from(month as u8).expect("month"),
                        day as u8,
                    )
                    .expect("date")
                    .with_hms(hour as u8, /*minute*/ 30, /*second*/ 0)
                    .expect("clock")
                    .assume_utc();
                    let local =
                        Timestamp::from_timestamp(instant.unix_timestamp(), /*nanoseconds*/ 0)
                            .expect("instant")
                            .try_local()
                            .expect("system zone")
                            .calendar()
                            .expect("calendar");
                    assert_eq!(
                        (
                            local.year(),
                            u8::from(local.month()),
                            local.day(),
                            local.hour(),
                            local.minute(),
                            local.second()
                        ),
                        (
                            i32::from(target.wYear),
                            target.wMonth as u8,
                            target.wDay as u8,
                            target.wHour as u8,
                            target.wMinute as u8,
                            target.wSecond as u8
                        )
                    );
                }
            }
        }
    }
}
