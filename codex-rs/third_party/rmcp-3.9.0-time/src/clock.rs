#[cfg(any(feature = "client", feature = "server"))]
use std::time::Duration;

use time::OffsetDateTime;
use time::UtcOffset;

// Retain the established UTC spelling, including +00:00 and groups of three
// fractional digits. The general time RFC 3339 formatter trims more zeroes.
pub(crate) fn format_utc_rfc3339(timestamp: OffsetDateTime) -> String {
    let timestamp = timestamp.to_offset(UtcOffset::UTC);
    let year = timestamp.year();
    let year = if year < 0 {
        format!("{year:05}")
    } else if year > 9999 {
        format!("+{year}")
    } else {
        format!("{year:04}")
    };
    let nanos = timestamp.nanosecond();
    let fraction = if nanos == 0 {
        String::new()
    } else if nanos.is_multiple_of(1_000_000) {
        format!(".{:03}", nanos / 1_000_000)
    } else if nanos.is_multiple_of(1_000) {
        format!(".{:06}", nanos / 1_000)
    } else {
        format!(".{nanos:09}")
    };
    format!(
        "{year}-{:02}-{:02}T{:02}:{:02}:{:02}{fraction}+00:00",
        u8::from(timestamp.month()),
        timestamp.day(),
        timestamp.hour(),
        timestamp.minute(),
        timestamp.second(),
    )
}

#[cfg(feature = "request-state")]
pub(crate) fn unix_millis(timestamp: OffsetDateTime) -> i64 {
    // Every year supported by time/large-dates fits in i64 milliseconds.
    timestamp.unix_timestamp_nanos().div_euclid(1_000_000) as i64
}

#[cfg(any(feature = "client", feature = "server"))]
pub(crate) fn format_timeout(timeout: Duration) -> String {
    // The previous duration conversion returned zero for unrepresentable values.
    // Keep that diagnostic behavior without affecting the actual timeout.
    if timeout.is_zero() || timeout.as_nanos() > i64::MAX as u128 * 1_000_000 {
        return "P0D".to_string();
    }
    let seconds = timeout.as_secs();
    let nanos = timeout.subsec_nanos();
    if nanos == 0 {
        format!("PT{seconds}S")
    } else {
        let fraction = format!("{nanos:09}");
        format!("PT{seconds}.{}S", fraction.trim_end_matches('0'))
    }
}

#[cfg(test)]
#[path = "clock_tests.rs"]
mod tests;
