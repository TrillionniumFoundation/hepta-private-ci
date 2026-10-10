//! Native numerical serving for the learned semantic-message MemoryCell circuit.
//! InferenceWorker retains grant, reservation, deadline and receipt ownership.
//! The pretrained text encoder executes upstream; this is not a Transformer VM.
use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverNeuronFeatureObservation;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::Error;
use crate::model_worker::ModelDriver;
use crate::model_worker::ModelManifest;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::WorkerRequest;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;
use std::time::Instant;
const MAX_PAYLOAD_BYTES: usize = 512 * 1024;
const Q24: f64 = (1_u64 << 24) as f64;

/// Source/representation binding supplied by an admitted host, not learned from
/// model output. Constructing this value alone does not authenticate it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryCellBindingV1 {
    pub encoder_digest: Digest32,
    pub dataset_digest: Digest32,
    pub scope_digest: Digest32,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Circuit {
    schema: String,
    encoder_digest: String,
    dataset_digest: String,
    scope_digest: String,
    output_profile: String,
    dimension: usize,
    hidden: usize,
    semantic_weight: Vec<f64>,
    semantic_bias: Vec<f64>,
    gate_weight: Vec<f64>,
    gate_bias: Vec<f64>,
    procedural_weight: Vec<f64>,
    procedural_bias: f64,
}
/// One pre-admitted immutable bundle. No filesystem, network, optimizer,
/// cache pooling or model installation is performed by this driver.
pub struct MemoryCellDriver {
    manifest: ModelManifest,
    circuit: Circuit,
    loaded: bool,
}
impl MemoryCellDriver {
    pub fn from_pinned_bytes(
        payload: &[u8],
        manifest: ModelManifest,
        binding: &MemoryCellBindingV1,
    ) -> Result<Self, Error> {
        if payload.is_empty() || payload.len() > MAX_PAYLOAD_BYTES {
            return Err(Error::FeatureLimit);
        }
        if Digest32::of_bytes(payload).to_string() != manifest.weights_digest
            || binding.encoder_digest.is_zero()
            || binding.dataset_digest.is_zero()
            || binding.scope_digest.is_zero()
            || manifest.runtime_digest != Self::runtime_digest().to_string()
            || manifest.quantization_digest != Self::quantization_digest().to_string()
        {
            return Err(Error::ModelMismatch);
        }
        let circuit: Circuit =
            serde_json::from_slice(payload).map_err(|_| Error::FeatureContract)?;
        if circuit.schema != "hepta.memory-circuit.v1"
            || circuit.output_profile != "relevance-state-five-v1"
            || !(1..=512).contains(&circuit.dimension)
            || !(1..=32).contains(&circuit.hidden)
            || circuit.encoder_digest != binding.encoder_digest.to_string()
            || circuit.dataset_digest != binding.dataset_digest.to_string()
            || circuit.scope_digest != binding.scope_digest.to_string()
            || circuit.semantic_weight.len() != circuit.hidden * circuit.dimension
            || circuit.gate_weight.len() != circuit.hidden * circuit.dimension
            || circuit.semantic_bias.len() != circuit.hidden
            || circuit.gate_bias.len() != circuit.hidden
            || circuit.procedural_weight.len() != circuit.dimension + circuit.hidden
        {
            return Err(Error::FeatureContract);
        }
        if circuit
            .semantic_weight
            .iter()
            .chain(&circuit.semantic_bias)
            .chain(&circuit.gate_weight)
            .chain(&circuit.gate_bias)
            .chain(&circuit.procedural_weight)
            .chain(std::iter::once(&circuit.procedural_bias))
            .any(|value| !value.is_finite() || value.abs() > 32.0)
        {
            return Err(Error::FeatureContract);
        }
        Ok(Self {
            manifest,
            circuit,
            loaded: false,
        })
    }
    pub fn head_digest() -> Digest32 {
        Digest32::of_bytes(b"hepta.memory-circuit.relevance-state-five-v1")
    }
    pub fn runtime_digest() -> Digest32 {
        Digest32::of_bytes(b"hepta.memory-circuit.rust-cpu.f64.v1")
    }
    pub fn quantization_digest() -> Digest32 {
        Digest32::of_bytes(
            b"hepta.memory-circuit.q24-input.f64-compute.q24-output.round-nearest.v1",
        )
    }
    fn tensor_bytes(&self) -> u64 {
        let c = &self.circuit;
        ((c.semantic_weight.capacity()
            + c.semantic_bias.capacity()
            + c.gate_weight.capacity()
            + c.gate_bias.capacity()
            + c.procedural_weight.capacity()
            + 1)
            * std::mem::size_of::<f64>()) as u64
    }
}
impl ModelDriver for MemoryCellDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        if self.loaded {
            return Err(Error::ModelAlreadyLoaded);
        }
        if manifest != &self.manifest {
            return Err(Error::ModelMismatch);
        }
        self.loaded = true;
        Ok(DriverModelHandle {
            opaque_id: self.manifest.weights_digest.clone(),
            observed_memory_bytes: self.tensor_bytes(),
        })
    }
    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        Err(Error::DriverFailure(
            "MemoryCell requires the typed feature port".into(),
        ))
    }
    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        if !self.loaded || handle.opaque_id != self.manifest.weights_digest {
            return Err(Error::ModelNotLoaded);
        }
        self.loaded = false;
        Ok(())
    }
}
impl NeuronFeatureDriver for MemoryCellDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        let start = Instant::now();
        if !self.loaded || handle.opaque_id != self.manifest.weights_digest {
            return Err(Error::ModelNotLoaded);
        }
        let c = &self.circuit;
        if request.encoder_digest != c.encoder_digest
            || request.head_digest != Self::head_digest().to_string()
            || request.weights_digest != self.manifest.weights_digest
            || request.expected_output_width != 5
            || request.feature_vector_q24.len() != c.dimension
            || request
                .feature_vector_q24
                .iter()
                .any(|v| !(-(8_i64 << 24)..=(8_i64 << 24)).contains(v))
        {
            return Err(Error::FeatureContract);
        }
        let x: Vec<_> = request
            .feature_vector_q24
            .iter()
            .map(|v| *v as f64 / Q24)
            .collect();
        let mut logit = c.procedural_bias;
        for (j, value) in x.iter().enumerate() {
            logit += c.procedural_weight[j] * value;
        }
        let mut semantic_magnitude = 0.0;
        let mut mean_gate = 0.0;
        for i in 0..c.hidden {
            let mut semantic = c.semantic_bias[i];
            let mut gate = c.gate_bias[i];
            for (j, value) in x.iter().enumerate() {
                semantic += c.semantic_weight[i * c.dimension + j] * value;
                gate += c.gate_weight[i * c.dimension + j] * value;
            }
            let semantic = semantic.tanh();
            let gate = 1.0 / (1.0 + (-gate).exp());
            semantic_magnitude += semantic.abs();
            mean_gate += gate;
            logit += c.procedural_weight[c.dimension + i] * semantic * gate;
        }
        if !logit.is_finite() {
            return Err(Error::FeatureContract);
        }
        let probability = (1.0 / (1.0 + (-logit).exp()) * Q24).round() as i64;
        // Five declared state features, NOT five class probabilities or a future predictor.
        let distribution = vec![
            (1_i64 << 24) - probability,
            probability,
            (semantic_magnitude / c.hidden as f64 * Q24).round() as i64,
            (mean_gate / c.hidden as f64 * Q24).round() as i64,
            (2 * probability - (1_i64 << 24)).abs(),
        ];
        Ok(DriverNeuronFeatureObservation {
            terminal_observed: true,
            succeeded: true,
            encoder_digest: c.encoder_digest.clone(),
            head_digest: request.head_digest.clone(),
            drive_q24: distribution.clone(),
            prediction_q24: distribution,
            observed_memory_bytes: self.tensor_bytes(),
            transient_allocation_bytes: (x.capacity() * std::mem::size_of::<f64>()
                + 10 * std::mem::size_of::<i64>()) as u64,
            queue_age_micros: 0,
            latency_micros: u64::try_from(start.elapsed().as_micros())
                .map_err(|_| Error::ArithmeticOverflow)?,
        })
    }
}
#[cfg(test)]
#[path = "memory_cell_driver_tests.rs"]
mod tests;
