//! Ordinary FeatureV1 execution of the same immutable Q24 factor graph used by
//! generation and training. The original control owner handles claim/readback;
//! this worker owns no Cell state, version selection or publication authority.
//! The frozen meter reports live model object/vector capacity and the sum of
//! actual native vector allocations. It does not claim process RSS, allocator
//! overhead, CPU/energy or control-journal costs as measured model resources.

use std::sync::Arc;
use std::time::Instant;

use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_neuron::CellDefinitionV1;
use codex_hepta_neuron::CellEncodedInputV1;
use codex_hepta_neuron::CellEncodingRequestV1;
use codex_hepta_neuron::CellExecutionError;
use codex_hepta_neuron::CellGenerationErrorV2;
use codex_hepta_neuron::CellInputEncoderV1;
use codex_hepta_neuron::NeuronFeatureObservationV1;
use codex_hepta_neuron::NeuronFeatureRequestV1;
use codex_hepta_neuron::NeuronFeatureTerminalStatusV1;
use codex_hepta_neuron::NeuronFeatureWorkerV1;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronModelRuntimeTupleV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use super::LoadedCellQ24ModelV1;
use super::codec;

pub struct CellQ24FeatureWorkerV1 {
    model: Arc<LoadedCellQ24ModelV1>,
    runtime: NeuronModelRuntimeTupleV1,
    generation: Generation,
}

/// The only supported input is the exact bounded HQ24I001 vector. Each ordinary
/// task starts from Reset; an existing temporal checkpoint is not ignored.
#[derive(Clone)]
pub struct CellQ24FeatureEncoderV1 {
    model: Arc<LoadedCellQ24ModelV1>,
}

impl CellQ24FeatureWorkerV1 {
    /// Pins the arithmetic and measurement convention. Host admission remains
    /// responsible for executable provenance and the actual device identity.
    pub fn runtime_profile_digest() -> Digest32 {
        Digest32::of_bytes(b"hepta.cell.q24.feature-runtime.v1;shared-Q24-factor-graph;Instant-wall;owned-model-size-and-vector-capacity;sum-native-vector-capacities;reset-only")
    }

    pub fn new(
        model: Arc<LoadedCellQ24ModelV1>,
        bundle: &CellCompatibilityBundleV1,
        definition: &CellDefinitionV1,
    ) -> Result<Self, CellGenerationErrorV2> {
        definition
            .semantic_digest()
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        let digest = bundle
            .digest()
            .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
        let r = &definition.runtime;
        let c = model.components();
        if &bundle.components != c
            || definition.bundle_digest != digest
            || definition.state_schema_digest != c.state_schema
            || r.model_id != bundle.artifact_id
            || r.model_manifest_digest != digest
            || r.generation != bundle.generation
            || r.encoder_digest != c.encoder
            || r.head_digest != c.heads
            || r.weights_digest != model.effective_weights_digest()
            || r.tokenizer_digest != c.tokenizer
            || r.preprocessor_digest != c.normalizer
            || r.normalization_digest != c.normalizer
            || r.quantization_digest != c.numeric_profile
            || r.runtime_digest != Self::runtime_profile_digest()
            || r.input_feature_dimension != model.input_width()
            || r.state_width != model.output_width()
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let runtime = NeuronModelRuntimeTupleV1 {
            model_id: r.model_id.clone(),
            model_manifest_digest: r.model_manifest_digest,
            weights_digest: r.weights_digest,
            tokenizer_digest: r.tokenizer_digest,
            preprocessor_digest: r.preprocessor_digest,
            quantization_digest: r.quantization_digest,
            runtime_digest: r.runtime_digest,
            device_digest: r.device_digest,
        };
        Ok(Self {
            model,
            runtime,
            generation: r.generation,
        })
    }

    pub fn input_encoder(&self) -> CellQ24FeatureEncoderV1 {
        CellQ24FeatureEncoderV1 {
            model: Arc::clone(&self.model),
        }
    }
}

impl CellInputEncoderV1 for CellQ24FeatureEncoderV1 {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError> {
        if request.encoder_digest != self.model.components().encoder || request.checkpoint.is_some()
        {
            return Err(CellExecutionError::EncodingMismatch);
        }
        let feature_vector_q24 = codec::input(request.observation, self.model.input_width())
            .map_err(|_| CellExecutionError::EncodingMismatch)?;
        Ok(CellEncodedInputV1 {
            encoder_digest: self.model.components().encoder,
            feature_vector_q24,
            consumed_bytes: request.observation.len(),
            truncated_bytes: 0,
        })
    }
}

impl NeuronFeatureWorkerV1 for CellQ24FeatureWorkerV1 {
    fn runtime_tuple(&self) -> &NeuronModelRuntimeTupleV1 {
        &self.runtime
    }

    fn execute(
        &self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureObservationV1, NeuronModelError> {
        let queued = Instant::now();
        let c = self.model.components();
        if request.model_id != self.runtime.model_id
            || request.generation != self.generation
            || request.encoder_digest != c.encoder
            || request.head_digest != c.heads
            || request.weights_digest != self.model.effective_weights_digest()
            || request.input_digest.is_zero()
            || request.feature_vector_q24.len() != self.model.input_width()
            || request.expected_output_width != self.model.output_width()
            || request
                .feature_vector_q24
                .iter()
                .any(|value| !(-8 * codec::Q..=8 * codec::Q).contains(value))
        {
            return Err(NeuronModelError::Rejected);
        }
        let observed_memory_bytes = self.model.owned_allocation_bytes();
        let queue_age_micros = elapsed(queued)?;
        let started = Instant::now();
        let (hidden, hidden_allocation) = self
            .model
            .hidden_with_allocations(&request.feature_vector_q24);
        let output = self.model.heads.apply(&hidden);
        let width = self.model.output_width();
        let drive_q24 = output[..width].to_vec();
        let prediction_q24 = output[width..].to_vec();
        let allocated = hidden_allocation
            + output.capacity()
            + drive_q24.capacity()
            + prediction_q24.capacity();
        let latency_micros = elapsed(started)?;
        Ok(NeuronFeatureObservationV1 {
            encoder_digest: c.encoder,
            head_digest: c.heads,
            drive_q24,
            prediction_q24,
            observed_memory_bytes,
            transient_allocation_bytes: (allocated * size_of::<i64>()) as u64,
            queue_age_micros,
            latency_micros,
            status: NeuronFeatureTerminalStatusV1::Succeeded,
        })
    }
}

impl LoadedCellQ24ModelV1 {
    fn owned_allocation_bytes(&self) -> u64 {
        let mut count = self.base.values.capacity()
            + self.encoder.values.capacity()
            + self.heads.values.capacity();
        for adapter in [&self.organ, &self.cell].into_iter().flatten() {
            count += adapter.down.values.capacity() + adapter.up.values.capacity();
        }
        (size_of::<Self>() + count * size_of::<i64>()) as u64
    }
}

fn elapsed(started: Instant) -> Result<u64, NeuronModelError> {
    u64::try_from(started.elapsed().as_micros()).map_err(|_| NeuronModelError::Indeterminate)
}
