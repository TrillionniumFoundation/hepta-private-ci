use super::ProductEvaluationRunnerV1;

impl ProductEvaluationRunnerV1<crate::LockedFileFinalHoldoutCasStoreV1> {
    /// Observe the existing holdout file owner under an exclusive runner borrow.
    pub fn qualification_holdout_bytes(
        &mut self,
        max_bytes: usize,
    ) -> Result<Vec<u8>, crate::LockedFileCasErrorV1> {
        self.holdout.qualification_file_bytes(max_bytes)
    }
}
