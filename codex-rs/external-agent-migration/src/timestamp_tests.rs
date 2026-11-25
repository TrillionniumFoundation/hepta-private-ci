use super::current_utc;
use pretty_assertions::assert_eq;
use time::OffsetDateTime;
use time::UtcOffset;
use time::macros::datetime;
use time::macros::format_description;

pub(crate) fn seconds_now() -> String {
    seconds_at(OffsetDateTime::now_utc())
}

fn seconds_at(now: OffsetDateTime) -> String {
    current_utc(now)
        .format(format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second]Z"
        ))
        .expect("UTC timestamp contains every component required by the static format")
}

#[test]
fn current_timestamp_preserves_unix_seconds_and_utc_offset() {
    for (input, expected, seconds) in [
        (
            datetime!(1970-01-01 0:00:00 UTC),
            datetime!(1970-01-01 0:00:00 UTC),
            0,
        ),
        (
            datetime!(1970-01-01 0:00:00.999999999 UTC),
            datetime!(1970-01-01 0:00:00.999999999 UTC),
            0,
        ),
        (
            datetime!(1970-01-01 1:00:01.999999999 +01:00),
            datetime!(1970-01-01 0:00:01.999999999 UTC),
            1,
        ),
    ] {
        let actual = current_utc(input);
        assert_eq!(
            (actual, actual.offset(), actual.unix_timestamp()),
            (expected, UtcOffset::UTC, seconds),
        );
    }
}

#[test]
fn fixture_timestamp_preserves_seconds_utc_bytes() {
    for (input, expected) in [
        (datetime!(1970-01-01 0:00:00 UTC), "1970-01-01T00:00:00Z"),
        (
            datetime!(2024-02-29 23:59:59.999999999 UTC),
            "2024-02-29T23:59:59Z",
        ),
        (
            datetime!(2024-03-01 0:59:59.999999999 +01:00),
            "2024-02-29T23:59:59Z",
        ),
    ] {
        assert_eq!(seconds_at(input), expected);
    }
}

#[cfg(not(all(
    target_arch = "wasm32",
    not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
)))]
#[test]
#[should_panic(expected = "system time before Unix epoch")]
fn current_timestamp_preserves_native_pre_epoch_refusal() {
    current_utc(datetime!(1969-12-31 23:59:59.999999999 UTC));
}
