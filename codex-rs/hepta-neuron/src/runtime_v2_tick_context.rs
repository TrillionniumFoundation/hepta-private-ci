use super::AnchorWitnessStore;
use super::JournalAnchor;
use super::NeuronRuntimeV2;
use super::NeuronRuntimeV2Error;

impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    /// Read the fully acknowledged head through the existing owner. Pending
    /// operations remain recoverable truth, but cannot seed a new tick.
    pub fn current_tick_anchor(&self) -> Result<Option<JournalAnchor>, NeuronRuntimeV2Error> {
        self.validate_frontiers()?;
        if self.index.pending()?.is_some() || self.store.pending_witness_count()? != 0 {
            return Err(NeuronRuntimeV2Error::PendingOperation);
        }
        Ok(self.current_checkpoint_anchor())
    }
}
