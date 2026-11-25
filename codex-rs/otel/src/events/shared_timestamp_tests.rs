use super::timestamp;
use pretty_assertions::assert_eq;
use time::OffsetDateTime;

#[test]
fn event_timestamp_preserves_fixed_millisecond_utc_bytes() {
    let cases = [
        (OffsetDateTime::UNIX_EPOCH, "1970-01-01T00:00:00.000Z"),
        (
            time::macros::datetime!(2024-02-29 23:59:59.999999999 UTC),
            "2024-02-29T23:59:59.999Z",
        ),
        (
            time::macros::datetime!(2024-03-01 00:30:00.123999999 +01:00),
            "2024-02-29T23:30:00.123Z",
        ),
    ];
    for (now, expected) in cases {
        assert_eq!(timestamp(now), expected);
    }
}

#[cfg(not(all(
    target_arch = "wasm32",
    not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
)))]
#[test]
#[should_panic(expected = "system time before Unix epoch")]
fn event_timestamp_preserves_native_pre_epoch_refusal() {
    let nanos = -1;
    let now = OffsetDateTime::from_unix_timestamp_nanos(nanos).expect("valid pre-epoch time");
    timestamp(now);
}
