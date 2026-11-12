//! Test-only decoding of the actual completed Material prefix. This helper
//! does not issue signatures, claim a journal, or create a production client.
use super::*;

impl OriginalCellQ24MaterialCommandReceiptV1 {
    pub(crate) fn fixture_original_model_dataset(
        config: &OriginalCellQ24MaterialReceiptConfigV1,
        snapshot: LearningIterationSnapshotV1,
        evidence: Vec<SignedLearningEvidenceV1>,
    ) -> Result<Self, Error> {
        let at = now()?;
        wire::authenticate_cut(config, Role::Dataset, Self {
            snapshot, evidence, original_context: wire::context_binding(config, at)?,
        }, at)
    }
}
