//! Retain the first actual failure of this one task's protected clock.
//! A callback adapter cannot report Result, so its consumers must explicitly
//! reject MAX before computing outcomes or writing state. The ordinary remote
//! and original feature-control refusal increments are required dependencies.

use std::sync::Arc;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::time::Instant;

use codex_hepta_contracts::AuthorityTrustError;

use super::invalid;
use crate::AgentdError;

/// Crate-private failure observation only: no owner, time setter, reset,
/// success token, deadline extension or mutable access to the actual clock.
#[derive(Clone)]
pub(crate) struct OriginalTaskClockStatus {
    first_failure: Arc<AtomicU8>,
    end: Instant,
}

impl OriginalTaskClockStatus {
    pub(super) fn new(end: Instant) -> Self {
        Self { first_failure: Arc::new(AtomicU8::new(0)), end }
    }

    pub(super) fn record_original_error(&self, error: AuthorityTrustError) {
        let code = match error {
            AuthorityTrustError::Invalid => 1,
            AuthorityTrustError::Conflict => 2,
            AuthorityTrustError::Unavailable => 3,
        };
        self.record(code);
    }

    pub(super) fn record_overflow(&self) { self.record(4); }

    fn record(&self, code: u8) {
        // Preserve the first actual cause even if later clock reads recover,
        // another failure happens, or the absolute end subsequently expires.
        let _ = self.first_failure.compare_exchange(0, code, Ordering::AcqRel, Ordering::Acquire);
    }

    pub(crate) fn require_healthy(&self) -> Result<(), AgentdError> {
        if Instant::now() >= self.end { self.record(5); }
        let message = match self.first_failure.load(Ordering::Acquire) {
            0 => return Ok(()),
            1 => "original protected task clock: Invalid",
            2 => "original protected task clock: Conflict",
            3 => "original protected task clock: Unavailable",
            4 => "original protected task clock: microsecond projection overflow",
            5 => "original protected task clock: absolute task end expired",
            _ => "original protected task clock: invalid retained failure state",
        };
        Err(invalid(message))
    }
}
