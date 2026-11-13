//! A fixed, lossless [drive, prediction] projection for a successor Cell. The
//! normal prepare path still checks its runtime's declared feature dimension.

use codex_hepta_neuron::CellEncodedInputV1;
use codex_hepta_neuron::CellEncodingRequestV1;
use codex_hepta_neuron::CellExecutionError;
use codex_hepta_neuron::CellInputEncoderV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::circuit_cell_binding::push_text;
use crate::decode_circuit_cell_ports_v2;

/// Pins the producer, bundle, state schema, width and channel order. This
/// encoder accepts only a producer in the consumer's agent/run/principal scope
/// and at its current source frontier. It neither grants actions nor gradients.
pub struct CircuitCellRepresentationEncoderV1 {
    producer_cell_id: StableId,
    producer_bundle_digest: Digest32,
    producer_state_schema_digest: Digest32,
    width: usize,
    digest: Digest32,
}

impl CircuitCellRepresentationEncoderV1 {
    pub fn new(
        producer_cell_id: StableId,
        producer_bundle_digest: Digest32,
        producer_state_schema_digest: Digest32,
        width: usize,
    ) -> Result<Self, CellExecutionError> {
        if producer_bundle_digest.is_zero()
            || producer_state_schema_digest.is_zero()
            || !(1..=256).contains(&width)
        {
            return Err(CellExecutionError::InvalidDefinition);
        }
        let mut bytes =
            b"hepta.circuit.cell-representation-encoder.q24.v1\0drive,prediction\0".to_vec();
        push_text(&mut bytes, producer_cell_id.as_str());
        bytes.extend_from_slice(producer_bundle_digest.as_array());
        bytes.extend_from_slice(producer_state_schema_digest.as_array());
        bytes.extend_from_slice(&(width as u32).to_be_bytes());
        Ok(Self {
            producer_cell_id,
            producer_bundle_digest,
            producer_state_schema_digest,
            width,
            digest: Digest32::of_bytes(&bytes),
        })
    }

    pub fn digest(&self) -> Digest32 {
        self.digest
    }
}

impl CellInputEncoderV1 for CircuitCellRepresentationEncoderV1 {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError> {
        let ports = decode_circuit_cell_ports_v2(request.observation)
            .map_err(|_| CellExecutionError::EncodingMismatch)?;
        let mut producer_scope = request.scope.clone();
        producer_scope.cell_id = self.producer_cell_id.clone();
        if request.encoder_digest != self.digest
            || ports.scope_digest != producer_scope.digest()
            || ports.bundle_digest != self.producer_bundle_digest
            || ports.source_frontier != request.source_frontier
            || ports.state_schema_digest != self.producer_state_schema_digest
            || ports.representation.drive_q24.len() != self.width
        {
            return Err(CellExecutionError::EncodingMismatch);
        }
        let mut features = ports.representation.drive_q24;
        features.extend(ports.representation.prediction_q24);
        Ok(CellEncodedInputV1 {
            encoder_digest: self.digest,
            feature_vector_q24: features,
            consumed_bytes: request.observation.len(),
            truncated_bytes: 0,
        })
    }
}
