// Exact unseeded, unused original witness descriptor.
impl FileNeuronWitnessStoreV2 {
    pub(crate) fn observe_fresh_prepared_file_v2(
        &self,
    ) -> Result<
        (
            NeuronWitnessContextV2,
            crate::NeuronPreparedFileObservationV2,
        ),
        WitnessStoreError,
    > {
        self.ensure_healthy()?;
        if self.seed.is_some() || self.current.is_some() || self.records != 0 {
            return Err(WitnessStoreError::Conflict);
        }
        let expected = encode_header(&self.context, None);
        Ok((
            self.context.clone(),
            self.file.observe_prepared_header_v2(&expected)?,
        ))
    }
}
pub(crate) fn validate_fresh_prepared_header_v2(
    bytes: &[u8],
    context: &NeuronWitnessContextV2,
) -> Result<(), WitnessStoreError> {
    context.validate()?;
    if bytes != encode_header(context, None) {
        return Err(WitnessStoreError::ContextMismatch);
    }
    Ok(())
}
