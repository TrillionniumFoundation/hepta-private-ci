use super::*;

impl<W: AnchorWitnessStore> NeuronRuntimeV2<W> {
    /// Clone the current sparse checkpoint only after the original store,
    /// discovery index and witness agree on a fully acknowledged head. This
    /// read never reconciles pending work or creates an operation.
    pub fn current_acknowledged_sparse_checkpoint_v2(
        &self,
        required_anchor: JournalAnchor,
    ) -> Result<Option<SparseCheckpoint>, NeuronRuntimeV2Error> {
        let anchor = self.current_tick_anchor()?;
        let checkpoint = self.checkpoint.clone();
        if checkpoint.is_some() && !self.store.contains_acknowledged_anchor(required_anchor)? {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        if checkpoint.as_ref().map(|value| JournalAnchor {
            sequence: value.sequence(),
            checkpoint_digest: value.digest(),
        }) != anchor
        {
            return Err(NeuronRuntimeV2Error::RecoveryMismatch);
        }
        Ok(checkpoint)
    }
}
