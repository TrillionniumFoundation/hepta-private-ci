//! Qualification-only forwarding to the retained final-holdout file owner.

use super::ProductEvaluationRunnerV1;
use crate::LockedFileCasErrorV1;
use crate::LockedFileFinalHoldoutCasStoreV1;

impl ProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1> {
    /// Read the complete bounded holdout file through its original locked
    /// handle. This does not release holdout data or mint evaluation evidence.
    pub fn qualification_holdout_file_bytes(
        &mut self,
        maximum_bytes: u64,
    ) -> Result<Vec<u8>, LockedFileCasErrorV1> {
        self.holdout.qualification_file_bytes(maximum_bytes)
    }
}
