//! The original root-signed activation window remains a current-use boundary.

use super::ActivatedLearningTrustV1;
use crate::SignedEvidenceError;

impl ActivatedLearningTrustV1 {
    pub(crate) fn current_valid_until(&self, now: u64) -> Result<u64, SignedEvidenceError> {
        if now < self.effective_at || now > self.expires_at {
            return Err(SignedEvidenceError::ValidityWindow);
        }
        if self.root_revoked_at.is_some_and(|at| now >= at) {
            return Err(SignedEvidenceError::Revoked);
        }
        Ok(self.root_revoked_at.map_or(self.expires_at, |at| {
            self.expires_at.min(at.saturating_sub(1))
        }))
    }
}
