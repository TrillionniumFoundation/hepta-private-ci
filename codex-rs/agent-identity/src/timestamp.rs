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

    let now = now.to_offset(UtcOffset::UTC);
    // Date's Display preserves the signed, zero-padded Gregorian year.
    format!(
        "{}T{:02}:{:02}:{:02}Z",
        now.date(),
        now.hour(),
        now.minute(),
        now.second(),
    )
}

#[cfg(test)]
#[path = "timestamp_tests.rs"]
mod tests;
