//! Clock and duration text at the existing MCP boundary.
//!
//! The shared maintained time boundary preserves the existing numeric UTC
//! offset, 0/3/6/9 fractional digits, civil range, and represented leap seconds.

pub(crate) fn now_rfc3339() -> String {
    codex_utils_time::Timestamp::now().rfc3339()
}

#[cfg(feature = "request-state")]
pub(crate) fn now_unix_millis() -> i64 {
    codex_utils_time::Timestamp::now().epoch_milliseconds()
}

/// Preserve the timeout diagnostic's ISO 8601 form and overflow fallback.
/// Adapted from upstream rust-sdk PR #1474, commit 9043cdfa8694d83bf506c2f3eb0313ec173edd7e.
#[cfg(any(feature = "client", feature = "server"))]
pub(crate) struct Iso8601Duration(pub(crate) std::time::Duration);

#[cfg(any(feature = "client", feature = "server"))]
impl std::fmt::Display for Iso8601Duration {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        const MAX_SECS: u64 = (i64::MAX / 1_000) as u64;
        const MAX_SUBSEC_NANOS: u32 = (i64::MAX % 1_000) as u32 * 1_000_000;
        let secs = self.0.as_secs();
        let nanos = self.0.subsec_nanos();
        if self.0.is_zero() || secs > MAX_SECS || (secs == MAX_SECS && nanos > MAX_SUBSEC_NANOS) {
            return f.write_str("P0D");
        }
        write!(f, "PT{secs}")?;
        if nanos > 0 {
            let mut fraction = nanos;
            let mut digits = 9;
            while fraction.is_multiple_of(10) {
                fraction /= 10;
                digits -= 1;
            }
            write!(f, ".{fraction:0digits$}")?;
        }
        f.write_str("S")
    }
}

#[cfg(test)]
#[path = "time_tests.rs"]
mod tests;
