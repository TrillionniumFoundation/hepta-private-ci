//! Reserve index completion before dispatch; no new durable record format.
use super::*;

impl FileNeuronRuntimeIndexV2 {
    pub(super) fn check_prepare_capacity(
        &self,
        key: &NeuronOperationKeyV2,
        expected: Option<JournalAnchor>,
        prepared_bytes: u64,
    ) -> Result<(), NeuronRuntimeIndexError> {
        let sequence = match expected {
            Some(anchor) => anchor
                .sequence
                .checked_add(1)
                .ok_or(NeuronRuntimeIndexError::InvalidRecord)?,
            None => 1,
        };
        // Only the key and sequence affect encoded length. Digests are fixed
        // width. These sizing markers never become a stored completion.
        let marker = Digest32::from_array([1; 32]);
        let completion = IndexEventV2::Completed {
            key: OperationKeyDto::from_key(key),
            next_anchor: AnchorDto::from_anchor(JournalAnchor {
                sequence,
                checkpoint_digest: marker,
            }),
            generation_operation_digest: marker.to_string(),
        };
        let payload = encode_event(self.event_frontier, &completion)?;
        if payload.len() > MAX_FRAME_BYTES {
            return Err(NeuronRuntimeIndexError::Capacity);
        }
        let required = prepared_bytes
            .checked_add(framed_bytes(payload.len())?)
            .ok_or(NeuronRuntimeIndexError::Capacity)?;
        self.check_capacity(required)
    }
}
