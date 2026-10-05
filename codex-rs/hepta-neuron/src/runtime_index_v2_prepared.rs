// Exact fresh state from the original held runtime-index descriptor.
impl FileNeuronRuntimeIndexV2 {
    pub(crate) fn observe_fresh_prepared_v2(
        &self,
    ) -> Result<
        (
            NeuronRuntimeIndexContextV2,
            crate::NeuronPreparedFileObservationV2,
        ),
        NeuronRuntimeIndexError,
    > {
        self.ensure_healthy()?;
        if !self.records.is_empty()
            || !self.tick_index.is_empty()
            || self.pending.is_some()
            || self.dispatched
            || !self.failures.is_empty()
            || self.frontier.is_some()
            || !self.event_frontier.is_zero()
            || self.end_offset != HEADER_BYTES as u64
        {
            return Err(NeuronRuntimeIndexError::Conflict);
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
    context: &NeuronRuntimeIndexContextV2,
) -> Result<(), NeuronRuntimeIndexError> {
    if bytes != encode_header(context)? {
        return Err(NeuronRuntimeIndexError::ContextMismatch);
    }
    Ok(())
}
