//! A verified caller's exact decision window, distinct from the publisher's
//! longer metadata lifetime. This value is never itself a signature verifier.

use super::invalid;
use crate::FleetRegistryError;

#[derive(Clone, Copy)]
pub(crate) struct VerifiedDecisionWindow {
    not_before_ms: u64,
    expires_at_ms: u64,
}

impl VerifiedDecisionWindow {
    pub fn new(not_before_ms: u64, expires_at_ms: u64) -> Result<Self, FleetRegistryError> {
        if not_before_ms >= expires_at_ms {
            return Err(invalid(
                "verified decision has an empty or reversed validity window",
            ));
        }
        Ok(Self {
            not_before_ms,
            expires_at_ms,
        })
    }

    pub fn check(self, unix_ms: u64) -> Result<(), FleetRegistryError> {
        if unix_ms < self.not_before_ms || unix_ms >= self.expires_at_ms {
            return Err(invalid(
                "verified decision is outside its exact validity window",
            ));
        }
        Ok(())
    }
}
