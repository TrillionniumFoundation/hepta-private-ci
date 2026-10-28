//! Existing NeuronModelPort binding for the exported associative model.
//!
//! Direct typed prediction uses exact SHAKE features. The generic neuron port
//! receives Q24 features, explicitly quantized by its caller; that conversion is
//! not claimed bit-equivalent to the direct float64 feature path. Runtime byte
//! charging covers serialized model and decoded numeric payload, not process RSS
//! or a complete allocator accounting of map nodes and string capacities.

use std::mem::size_of;
use std::time::Instant;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::ASSOCIATIVE_MEMORY_ADDRESS_PROFILE_V1;
use crate::ASSOCIATIVE_MEMORY_NUMERIC_PROFILE_V1;
use crate::AssociativeMemoryCellV1;
use crate::AssociativeMemoryError;
use crate::LocalModelRuntimeReceiptV1;
use crate::NeuronModelError;
use crate::NeuronModelOutputV1;
use crate::NeuronModelPort;
use crate::NeuronModelRequestV1;
use crate::NeuronRuntimeConfigV1;
use crate::canonical_feature_vector_digest_v1;
use crate::canonical_model_output_digest_v1;

const Q24: f64 = 16_777_216.0;

/// Executes a pinned learned model through the same selected-runtime contract
/// as other neuron backends. Source admission remains with the cognitive owner.
pub struct AssociativeMemoryModelPortV1 {
    cell: AssociativeMemoryCellV1,
    selected: NeuronRuntimeConfigV1,
}

impl AssociativeMemoryModelPortV1 {
    pub fn new(
        cell: AssociativeMemoryCellV1,
        selected: &NeuronRuntimeConfigV1,
    ) -> Result<Self, AssociativeMemoryError> {
        let address_digest = Digest32::of_bytes(ASSOCIATIVE_MEMORY_ADDRESS_PROFILE_V1.as_bytes());
        if selected.model_manifest_digest != cell.digest()
            || selected.weights_digest != cell.parameters_digest()
            || selected.head_digest != cell.head_digest()
            || selected.encoder_digest != address_digest
            || selected.preprocessor_digest != address_digest
            || selected.quantization_digest
                != Digest32::of_bytes(ASSOCIATIVE_MEMORY_NUMERIC_PROFILE_V1.as_bytes())
            || selected.input_feature_dimension != cell.input_dimension()
            || cell.input_dimension() > 512
            || selected.state_width != cell.output_width()
            || selected.tokenizer_digest.is_zero()
            || selected.runtime_digest.is_zero()
            || selected.device_digest.is_zero()
        {
            return Err(AssociativeMemoryError::InvalidConfiguration);
        }
        Ok(Self {
            cell,
            selected: selected.clone(),
        })
    }
}

impl NeuronModelPort for AssociativeMemoryModelPortV1 {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        if request.config_id != self.selected.config_id
            || request.generation != self.selected.generation
            || request.model_id != self.selected.model_id
            || request.encoder_digest != self.selected.encoder_digest
            || request.head_digest != self.cell.head_digest()
            || request.weights_digest != self.cell.parameters_digest()
            || request.expected_output_width != self.cell.output_width()
            || request.input_digest
                != canonical_feature_vector_digest_v1(&request.feature_vector_q24)
            || request.feature_vector_q24.len() != self.cell.input_dimension()
            || request
                .feature_vector_q24
                .iter()
                .any(|value| !(-16_777_216..=16_777_216).contains(value))
        {
            return Err(NeuronModelError::Rejected);
        }
        let started = Instant::now();
        let features = request
            .feature_vector_q24
            .iter()
            .map(|value| *value as f64 / Q24)
            .collect::<Vec<_>>();
        let logits = self
            .cell
            .logits(&features)
            .map_err(|_| NeuronModelError::Rejected)?;
        let mut drive_q24 = logits
            .iter()
            .map(|value| (value.clamp(-8.0, 8.0) * Q24).round() as i64)
            .collect::<Vec<_>>();
        drive_q24.resize(self.cell.output_width(), 0);
        let prediction_q24 = vec![0; self.cell.output_width()];
        let model = &self.cell.model;
        let parameter_count = model.dimension * model.hidden
            + model.hidden
            + model.hidden * model.catalog.len()
            + model.catalog.len();
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id: self.selected.model_id.clone(),
            model_manifest_digest: self.cell.digest(),
            weights_digest: self.cell.parameters_digest(),
            tokenizer_digest: self.selected.tokenizer_digest,
            preprocessor_digest: self.selected.preprocessor_digest,
            quantization_id: StableId::new("memory.f32.f64.q24.v1")
                .map_err(|_| NeuronModelError::Rejected)?,
            quantization_digest: self.selected.quantization_digest,
            backend_id: StableId::new("memory.associative.cpu.v1")
                .map_err(|_| NeuronModelError::Rejected)?,
            runtime_digest: self.selected.runtime_digest,
            device_identity_digest: self.selected.device_digest,
            latency_micros: u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX),
            resident_bytes: (size_of::<Self>()
                + self.cell.serialized_bytes()
                + parameter_count * size_of::<f32>()) as u64,
        };
        let output_digest =
            canonical_model_output_digest_v1(&drive_q24, &prediction_q24, &runtime_receipt)
                .map_err(|_| NeuronModelError::Rejected)?;
        let transient_allocation_bytes = ((features.capacity() + model.hidden + logits.capacity())
            * size_of::<f64>()
            + (drive_q24.capacity() + prediction_q24.capacity()) * size_of::<i64>())
            as u64;
        Ok(NeuronModelOutputV1 {
            encoder_digest: self.selected.encoder_digest,
            head_digest: self.cell.head_digest(),
            output_digest,
            drive_q24,
            prediction_q24,
            queue_age_micros: 0,
            transient_allocation_bytes,
            runtime_receipt,
        })
    }
}
