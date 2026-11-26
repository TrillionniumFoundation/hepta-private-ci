use time::OffsetDateTime;
use time::UtcOffset;

pub(super) fn seconds_now() -> String {
    seconds_at(OffsetDateTime::now_utc())
}

fn seconds_at(now: OffsetDateTime) -> String {
    // Preserve the original native clock's rejection before the Unix epoch.
    #[cfg(not(all(
        target_arch = "wasm32",
        not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
    )))]
    assert!(now.unix_timestamp() >= 0, "system time before Unix epoch");

    match now
        .to_offset(UtcOffset::UTC)
        .format(time::macros::format_description!(
            "[year]-[month]-[day]T[hour]:[minute]:[second]Z"
        )) {
        Ok(timestamp) => timestamp,
        Err(error) => panic!(
            "UTC timestamp contains every component required by the static format: {error:?}"
        ),
    }
}

#[cfg(test)]
#[path = "timestamp_tests.rs"]
mod tests;
