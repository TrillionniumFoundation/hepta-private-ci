//! Production-only shared limits for authenticated record streams.
//!
//! Raw-envelope stream types live behind `protocol-tooling`. The final typed
//! production stream imports only this value object.

use crate::MAX_AUTHENTICATED_RECORD_BYTES;

/// Independent per-call work limits and a per-record admission ceiling.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RecordStreamLimits {
    pub max_record_bytes: usize,
    pub max_feed_bytes: usize,
    pub max_records_per_feed: usize,
}

impl Default for RecordStreamLimits {
    fn default() -> Self {
        Self {
            max_record_bytes: MAX_AUTHENTICATED_RECORD_BYTES,
            max_feed_bytes: 64 * 1024,
            max_records_per_feed: 16,
        }
    }
}
