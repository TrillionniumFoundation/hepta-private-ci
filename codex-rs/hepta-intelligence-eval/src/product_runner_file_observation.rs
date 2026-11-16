use super::ProductEvaluationRunnerV1;

impl ProductEvaluationRunnerV1<crate::LockedFileFinalHoldoutCasStoreV1> {
    #[cfg(feature = "qualification-owned-file-read")]
    /// Observe the existing holdout file owner under an exclusive runner borrow.
    pub fn qualification_holdout_bytes(
        &mut self,
        max_bytes: usize,
    ) -> Result<Vec<u8>, crate::LockedFileCasErrorV1> {
        self.holdout.qualification_file_bytes(max_bytes)
    }
}

#[cfg(any(test, feature = "qualification-file-observation"))]
use crate::LockedFileCasErrorV1;
use crate::LockedFileFinalHoldoutCasStoreV1;

impl ProductEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1> {
    #[cfg(any(test, feature = "qualification-file-observation"))]
    /// Read the complete bounded holdout file through its original locked
    /// handle. This does not release holdout data or mint evaluation evidence.
    pub fn qualification_holdout_file_bytes(
        &mut self,
        maximum_bytes: u64,
    ) -> Result<Vec<u8>, LockedFileCasErrorV1> {
        self.holdout
            .qualification_unpoisoned_file_bytes(maximum_bytes)
    }
}
