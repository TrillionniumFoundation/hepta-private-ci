// Exact fresh state from the original held generation-store descriptor.
impl FileNeuronGenerationStoreV2 {
    pub(crate) fn observe_fresh_prepared_v2(
        &self,
    ) -> Result<
        (
            NeuronGenerationStoreContextV2,
            crate::NeuronPreparedFileObservationV2,
        ),
        GenerationStoreError,
    > {
        self.ensure_healthy()?;
        if !self.records.is_empty()
            || !self.tick_index.is_empty()
            || self.local_frontier.is_some()
            || self.witness_frontier.is_some()
            || !self.event_frontier.is_zero()
            || self.pending_ack_bytes != 0
            || self.end_offset != HEADER_BYTES as u64
        {
            return Err(GenerationStoreError::Conflict);
        }
        let expected = encode_header(&self.context)?;
        Ok((
            self.context.clone(),
            self.file.observe_prepared_header_v2(&expected)?,
        ))
    }
}
pub(crate) fn validate_fresh_prepared_header_v2(
    bytes: &[u8],
    context: &NeuronGenerationStoreContextV2,
) -> Result<(), GenerationStoreError> {
    if bytes != encode_header(context)? {
        return Err(GenerationStoreError::ContextMismatch);
    }
    Ok(())
}
