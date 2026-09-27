//! Completion-space admission; this changes no HPTNGS02 encoding.
use super::*;

// Use the real encoder. Anchor/digest values are fixed-width; only the key's
// encoded ID length changes acknowledgement capacity. The marker is never
// persisted and supplies neither a checkpoint nor a witness acknowledgement.
fn acknowledgement_frame_bytes(key: &NeuronOperationKeyV2) -> Result<u64, GenerationStoreError> {
    let marker = Digest32::from_array([1; 32]);
    let payload = encode_witness_ack_event(
        Digest32::ZERO,
        key,
        JournalAnchor {
            sequence: 1,
            checkpoint_digest: marker,
        },
        marker,
    )?;
    framed_bytes(payload.len())
}

pub(super) fn recover_reserved_ack_bytes(
    records: &[NeuronGenerationRecordV2],
) -> Result<u64, GenerationStoreError> {
    records
        .iter()
        .filter(|record| !record.witness_acknowledged)
        .try_fold(0_u64, |total, record| {
            total
                .checked_add(acknowledgement_frame_bytes(&record.key)?)
                .ok_or(GenerationStoreError::Capacity)
        })
}

// HPTNGS02 starts at sequence one and only acknowledges the next prefix record.
// Both properties are validated on replay; no scan of retained payloads is needed.
pub(super) fn pending_count(
    records: usize,
    witness: Option<JournalAnchor>,
) -> Result<usize, GenerationStoreError> {
    let acknowledged = usize::try_from(witness.map_or(0, |anchor| anchor.sequence))
        .map_err(|_| GenerationStoreError::Corrupt)?;
    records
        .checked_sub(acknowledged)
        .ok_or(GenerationStoreError::Corrupt)
}

impl FileNeuronGenerationStoreV2 {
    pub(super) fn check_new_operation_capacity(
        &self,
        key: &NeuronOperationKeyV2,
        commit_frame_bytes: u64,
    ) -> Result<u64, GenerationStoreError> {
        if commit_frame_bytes > framed_bytes(MAX_FRAME_BYTES)? {
            return Err(GenerationStoreError::Capacity);
        }
        let reserved = self
            .pending_ack_bytes
            .checked_add(acknowledgement_frame_bytes(key)?)
            .ok_or(GenerationStoreError::Capacity)?;
        let required = commit_frame_bytes
            .checked_add(reserved)
            .ok_or(GenerationStoreError::Capacity)?;
        self.check_file_capacity(required)?;
        Ok(reserved)
    }
}
