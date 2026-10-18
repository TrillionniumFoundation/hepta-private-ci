//! Canonical record encoding reused by immutable, non-executable history.
use super::*;

impl FileNeuronGenerationStoreV2 {
    pub(crate) fn archive_records(
        &self,
    ) -> Result<&[NeuronGenerationRecordV2], GenerationStoreError> {
        self.ensure_healthy()?;
        if self.pending_witness_count()? != 0 {
            return Err(GenerationStoreError::Backpressure);
        }
        Ok(&self.records)
    }
}

pub(crate) fn encode_archived_record(
    record: &NeuronGenerationRecordV2,
) -> Result<Vec<u8>, GenerationStoreError> {
    if !record.witness_acknowledged || operation_digest(record)? != record.operation_digest {
        return Err(GenerationStoreError::Corrupt);
    }
    let mut bytes = encode_operation(record)?;
    bytes.extend_from_slice(record.operation_digest.as_array());
    Ok(bytes)
}

pub(crate) fn decode_archived_record(
    bytes: &[u8],
) -> Result<NeuronGenerationRecordV2, GenerationStoreError> {
    let end = bytes
        .len()
        .checked_sub(32)
        .ok_or(GenerationStoreError::Corrupt)?;
    let mut record = decode_operation(&bytes[..end])?;
    record.operation_digest = operation_digest(&record)?;
    if record.operation_digest.as_array() != &bytes[end..] {
        return Err(GenerationStoreError::Corrupt);
    }
    // This encoding is admitted only by an export after all witness ACKs.
    // It is historical truth and never grants a new-work/result-use capability.
    record.witness_acknowledged = true;
    Ok(record)
}
