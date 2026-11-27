//! A Feature task uses the Cell owner, leaving the Generation journal at its
//! original genesis followed only by optional durable Drain events. This is
//! physical DATA, not an execution count, CURRENT grant, or task completion.

use super::*;

impl CellGenerationJournalObserverV1 {
    /// Reuse the full original parser and witness check. A revision of zero
    /// alone is insufficient: Admit, Resume, costs and every other event deny.
    /// Return the original genesis digest derived from the same pinned header
    /// and config, for comparison to a separately retained first-Publish fact.
    pub fn observe_original_feature_boundary(
        &self,
    ) -> Result<(CellGenerationJournalObservedV1, [u8; 32]), CellGenerationErrorV2> {
        let before = self.observe()?;
        if !before.feature_boundary_only || (!before.is_genesis() && !before.is_drained()) {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let genesis = CellGenerationObservationV1::capture(
            &self.config.generation,
            &GenerationState::new(&self.config.generation)?,
            continuity_checkpoint(&self.header, None, HEADER_BYTES as u64),
        )?;
        if self.observe()? != before {
            return Err(CellGenerationErrorV2::Pending);
        }
        Ok((before, genesis.digest()?))
    }
}
