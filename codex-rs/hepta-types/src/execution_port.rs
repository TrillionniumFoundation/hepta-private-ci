//! Borrowed, backend-neutral execution intent for owner-to-adapter checks.
//!
//! This is an in-process Rust view, not a registered wire schema, a durable
//! operation record, a Final-use token or a dispatch capability. It neither
//! authenticates the caller nor authorizes any side effect.

use std::error::Error;
use std::fmt;

use crate::Digest32;
use crate::Generation;
use crate::StableId;

/// Source-bound execution metadata without Codex session/transport coupling.
/// The existing execution owner remains responsible for durable admission,
/// final-use authorization, effect deduplication and recovery.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ExecutionPortIntentV1<'a> {
    pub operation_id: &'a StableId,
    pub source_admission_digest: Digest32,
    pub generation: Generation,
    pub payload_digest: Digest32,
    pub lease_payload_digest: Digest32,
    pub deadline_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ExecutionPortIntentErrorV1 {
    EmptyDigest(&'static str),
    PayloadBindingMismatch,
    DeadlineExpired,
}

impl ExecutionPortIntentV1<'_> {
    /// Structural validation only. A caller-supplied matching digest is NOT
    /// evidence of owner origin, a live lease, or current authorization.
    pub fn validate(&self, now_ms: u64) -> Result<(), ExecutionPortIntentErrorV1> {
        if self.source_admission_digest.is_zero() {
            return Err(ExecutionPortIntentErrorV1::EmptyDigest("source admission"));
        }
        if self.payload_digest.is_zero() || self.lease_payload_digest.is_zero() {
            return Err(ExecutionPortIntentErrorV1::EmptyDigest("payload"));
        }
        if self.payload_digest != self.lease_payload_digest {
            return Err(ExecutionPortIntentErrorV1::PayloadBindingMismatch);
        }
        if self.deadline_ms == 0 || now_ms >= self.deadline_ms {
            return Err(ExecutionPortIntentErrorV1::DeadlineExpired);
        }
        Ok(())
    }
}

impl fmt::Display for ExecutionPortIntentErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl Error for ExecutionPortIntentErrorV1 {}

#[cfg(test)]
#[path = "execution_port_tests.rs"]
mod tests;
