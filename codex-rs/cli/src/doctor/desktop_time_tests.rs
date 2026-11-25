use pretty_assertions::assert_eq;
use time::Date;
use time::Month;
use time::OffsetDateTime;
use time::UtcOffset;

use super::CheckStatus;
use super::inspect_desktop_session;
use super::utc_log_day;

fn inspect_handshakes(contents: &str) -> CheckStatus {
    let directory = tempfile::tempdir().unwrap();
    std::fs::write(
        directory
            .path()
            .join("codex-desktop-time-fixture-12345-t0-i0-0.log"),
        contents,
    )
    .unwrap();
    let (running, check) = inspect_desktop_session(directory.path(), |pid| pid == 12345);
    assert!(running);
    check.status
}

#[test]
fn desktop_handshake_order_keeps_nanos_and_absolute_offset_time() {
    let status = inspect_handshakes(concat!(
        "2026-08-07T12:00:00.999999998Z error [AppServerConnection] initialize_handshake_result outcome=failure transportKind=stdio\n",
        "2026-08-07T14:00:00.999999999+02:00 info [AppServerConnection] initialize_handshake_result outcome=success transportKind=stdio\n",
        "2026-08-07T11:59:59.999999999Z error [AppServerConnection] initialize_handshake_result outcome=failure transportKind=stdio\n",
    ));
    assert_eq!(status, CheckStatus::Ok);
}

#[test]
fn desktop_handshake_ties_and_leap_seconds_keep_existing_selection() {
    assert_eq!(
        inspect_handshakes(concat!(
            "2026-08-07T12:00:00Z info [AppServerConnection] initialize_handshake_result outcome=success transportKind=stdio\n",
            "2026-08-07T13:00:00+01:00 error [AppServerConnection] initialize_handshake_result outcome=failure transportKind=stdio\n",
            "invalid info [AppServerConnection] initialize_handshake_result outcome=success transportKind=stdio\n",
        )),
        CheckStatus::Fail
    );
    let leap = concat!(
        "2026-08-07T12:00:59.999999999Z error [AppServerConnection] initialize_handshake_result outcome=failure transportKind=stdio\n",
        "2026-08-07T12:00:60.100Z info [AppServerConnection] initialize_handshake_result outcome=success transportKind=stdio\n",
        "2026-08-07T12:00:60.099999999Z error [AppServerConnection] initialize_handshake_result outcome=failure transportKind=stdio\n",
    );
    assert_eq!(inspect_handshakes(leap), CheckStatus::Ok);
    assert_eq!(
        inspect_handshakes(&format!(
            "{leap}2026-08-07T12:01:00Z error [AppServerConnection] initialize_handshake_result outcome=failure transportKind=stdio\n"
        )),
        CheckStatus::Fail
    );
}

#[test]
fn desktop_log_directory_uses_utc_date_and_existing_year_format() {
    let local = Date::from_calendar_date(/*year*/ 2000, Month::January, /*day*/ 1)
        .unwrap()
        .with_hms(/*hour*/ 0, /*minute*/ 30, /*second*/ 0)
        .unwrap()
        .assume_offset(UtcOffset::from_hms(/*hours*/ 1, /*minutes*/ 0, /*seconds*/ 0).unwrap());
    assert_eq!(utc_log_day(local.unix_timestamp()), "1999/12/31");
    assert_eq!(
        utc_log_day(OffsetDateTime::UNIX_EPOCH.unix_timestamp()),
        "1970/01/01"
    );
    assert_eq!(utc_log_day(253_402_300_800), "+10000/01/01");
    #[cfg(not(all(
        target_arch = "wasm32",
        not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
    )))]
    {
        let now = std::time::UNIX_EPOCH + std::time::Duration::from_secs(253_402_300_800);
        assert_eq!(
            utc_log_day(super::native_clock_seconds(now)),
            "+10000/01/01"
        );
    }
}

#[cfg(not(all(
    target_arch = "wasm32",
    not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
)))]
#[test]
#[should_panic(expected = "system time before Unix epoch")]
fn desktop_native_log_clock_keeps_pre_epoch_refusal() {
    let now = std::time::UNIX_EPOCH - std::time::Duration::from_secs(1);
    assert!(std::panic::catch_unwind(|| super::native_clock_seconds(now)).is_err());
    utc_log_day((OffsetDateTime::UNIX_EPOCH - time::Duration::nanoseconds(1)).unix_timestamp());
}
