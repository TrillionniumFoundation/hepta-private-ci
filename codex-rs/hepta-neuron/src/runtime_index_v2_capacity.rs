//! Reserve every remaining durable transition before dispatch.
use super::*;

impl FileNeuronRuntimeIndexV2 {
    pub(super) fn remaining_reservation(
        &self,
        key: &NeuronOperationKeyV2,
        expected: Option<JournalAnchor>,
        include_dispatch: bool,
    ) -> Result<u64, NeuronRuntimeIndexError> {
        let sequence = match expected {
            Some(anchor) => anchor
                .sequence
                .checked_add(1)
                .ok_or(NeuronRuntimeIndexError::InvalidRecord)?,
            None => 1,
        };
        let marker = Digest32::from_array([1; 32]);
        let completion = IndexEventV2::Completed {
            key: OperationKeyDto::from_key(key),
            next_anchor: AnchorDto::from_anchor(JournalAnchor {
                sequence,
                checkpoint_digest: marker,
            }),
            generation_operation_digest: marker.to_string(),
        };
        let completed_bytes = encode_event(self.event_frontier, &completion)?;
        let failure = IndexEventV2::Failed {
            key: OperationKeyDto::from_key(key),
            failure: NeuronOperationFailureV2::InvalidModelOutput,
        };
        let failed_bytes = encode_event(self.event_frontier, &failure)?;
        if completed_bytes.len().max(failed_bytes.len()) > MAX_FRAME_BYTES {
            return Err(NeuronRuntimeIndexError::Capacity);
        }
        let terminal = framed_bytes(completed_bytes.len().max(failed_bytes.len()))?;
        if !include_dispatch {
            return Ok(terminal);
        }
        let dispatch = IndexEventV2::DispatchStarted {
            key: OperationKeyDto::from_key(key),
        };
        let dispatch_bytes = encode_event(self.event_frontier, &dispatch)?;
        terminal
            .checked_add(framed_bytes(dispatch_bytes.len())?)
            .ok_or(NeuronRuntimeIndexError::Capacity)
    }

    pub(super) fn check_prepare_capacity(
        &self,
        key: &NeuronOperationKeyV2,
        expected: Option<JournalAnchor>,
        prepared_bytes: u64,
    ) -> Result<(), NeuronRuntimeIndexError> {
        let remaining =
            self.remaining_reservation(key, expected, /*include_dispatch*/ true)?;
        let required = prepared_bytes
            .checked_add(remaining)
            .ok_or(NeuronRuntimeIndexError::Capacity)?;
        self.check_capacity(required)
    }
}
