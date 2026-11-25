use time::OffsetDateTime;
use time::UtcOffset;

pub(super) fn current_utc(now: OffsetDateTime) -> OffsetDateTime {
    // Keep the native clock's existing pre-epoch refusal. The original
    // wasm-bindgen clock also represented dates before the Unix epoch.
    #[cfg(not(all(
        target_arch = "wasm32",
        not(any(target_os = "emscripten", target_os = "wasi", target_os = "linux"))
    )))]
    assert!(now.unix_timestamp() >= 0, "system time before Unix epoch");
    now.to_offset(UtcOffset::UTC)
}

#[cfg(test)]
pub(super) use tests::seconds_now;

#[cfg(test)]
#[path = "timestamp_tests.rs"]
mod tests;
