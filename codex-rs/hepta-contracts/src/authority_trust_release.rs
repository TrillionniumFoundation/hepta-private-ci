//! External commitment for one Fleet release owner, separate from FinalUse
//! nonces and learning activation. This value carries no publication authority.

use crate::AuthorityTrustError;
use serde::Deserialize;
use serde::Serialize;

/// One independently retained commitment to the complete release-owner journal.
///
/// `initial_root_sha256` is the immutable, out-of-band M15 bootstrap root pin.
/// The checkpoint covers M15 publication history; `state_sha256` additionally
/// covers the owner's exact journal, including local allowance and revocation.
/// Local deny events may advance generation without changing the M15 checkpoint.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ReleaseFrontierV1 {
    pub generation: u64,
    pub initial_root_sha256: [u8; 32],
    pub checkpoint_sha256: [u8; 32],
    pub state_sha256: [u8; 32],
}

impl ReleaseFrontierV1 {
    /// Validate a retained value without manufacturing a trust or freshness claim.
    pub fn validate(&self) -> Result<(), AuthorityTrustError> {
        if self.generation == 0
            || self.initial_root_sha256 == [0; 32]
            || self.checkpoint_sha256 == [0; 32]
            || self.state_sha256 == [0; 32]
        {
            return Err(AuthorityTrustError::Invalid);
        }
        Ok(())
    }
}
