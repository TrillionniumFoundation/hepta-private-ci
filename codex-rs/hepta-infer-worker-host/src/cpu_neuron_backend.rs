//! A bounded, opt-in CPU Q24 kernel for *physical* neuron feature batching.
//!
//! This driver performs one weight-major matrix pass across every input in a
//! batch, rather than invoking a single-request driver N times. The selected
//! host must independently authenticate the frozen manifest, weights and
//! authority before constructing it. This is a CPU backend, NOT a GPU/NPU,
//! attested deployment, trained-model quality or external resource receipt.
//! Production model invocation still goes through the signed microbatch owner.

use std::str::FromStr;
use std::time::Instant;

use codex_hepta_types::Digest32;

use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverNeuronFeatureBatchObservationV1;
use crate::model_worker::DriverNeuronFeatureObservation;
use crate::model_worker::DriverRunObservation;
use crate::model_worker::Error;
use crate::model_worker::ModelDriver;
use crate::model_worker::ModelManifest;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::WorkerRequest;

const Q24: i128 = 1_i128 << 24;
const MAX_Q24: i64 = 8_i64 << 24;
const MAX_WIDTH: usize = 512;
const MAX_BATCH: usize = 256;

/// Immutable, row-major drive and prediction projection matrices.
/// All weights are supplied as actual Q24 bytes, not caller-produced digests.
#[derive(Clone, Debug)]
pub struct CpuNeuronWeightBundleV1 {
    input_width: usize,
    output_width: usize,
    drive_weights: Box<[i64]>,
    prediction_weights: Box<[i64]>,
    encoder_digest: Digest32,
    head_digest: Digest32,
    weight_digest: Digest32,
}

impl CpuNeuronWeightBundleV1 {
    pub fn new(
        input_width: usize,
        output_width: usize,
        drive_weights: Vec<i64>,
        prediction_weights: Vec<i64>,
        encoder_digest: Digest32,
        head_digest: Digest32,
    ) -> Result<Self, Error> {
        let elements = input_width
            .checked_mul(output_width)
            .ok_or(Error::FeatureLimit)?;
        if input_width == 0
            || input_width > MAX_WIDTH
            || output_width == 0
            || output_width > MAX_WIDTH
            || elements != drive_weights.len()
            || elements != prediction_weights.len()
            || encoder_digest.is_zero()
            || head_digest.is_zero()
            || drive_weights
                .iter()
                .chain(&prediction_weights)
                .any(|&x| !(-MAX_Q24..=MAX_Q24).contains(&x))
        {
            return Err(Error::FeatureContract);
        }
        let mut content = Vec::with_capacity(64 + 2 * elements * 8);
        content.extend_from_slice(b"hepta.cpu-neuron.q24-weights.v1\0");
        content.extend_from_slice(&(input_width as u32).to_be_bytes());
        content.extend_from_slice(&(output_width as u32).to_be_bytes());
        content.extend_from_slice(encoder_digest.as_array());
        content.extend_from_slice(head_digest.as_array());
        for value in drive_weights.iter().chain(&prediction_weights) {
            content.extend_from_slice(&value.to_be_bytes());
        }
        let weight_digest = Digest32::of_bytes(&content);
        Ok(Self {
            input_width,
            output_width,
            drive_weights: drive_weights.into_boxed_slice(),
            prediction_weights: prediction_weights.into_boxed_slice(),
            encoder_digest,
            head_digest,
            weight_digest,
        })
    }

    pub const fn weight_digest(&self) -> Digest32 {
        self.weight_digest
    }

    fn resident_bytes(&self) -> Result<u64, Error> {
        let elements = self
            .drive_weights
            .len()
            .checked_add(self.prediction_weights.len())
            .and_then(|elements| elements.checked_mul(std::mem::size_of::<i64>()))
            .ok_or(Error::ArithmeticOverflow)?;
        u64::try_from(elements).map_err(|_| Error::ArithmeticOverflow)
    }
}

/// Exact backend identity is configured by a trusted host, not selected from
/// an untrusted request or mutated after a generation has been admitted.
#[derive(Debug)]
pub struct CpuNeuronFeatureDriverV1 {
    weights: CpuNeuronWeightBundleV1,
    model_digest: Digest32,
    runtime_digest: Digest32,
    quantization_digest: Digest32,
    device_digest: Digest32,
    loaded: Option<String>,
    native_batch_calls: u64,
    native_batched_requests: u64,
}

impl CpuNeuronFeatureDriverV1 {
    pub fn new(
        weights: CpuNeuronWeightBundleV1,
        model_digest: Digest32,
        runtime_digest: Digest32,
        quantization_digest: Digest32,
        device_digest: Digest32,
    ) -> Result<Self, Error> {
        if model_digest.is_zero()
            || runtime_digest.is_zero()
            || quantization_digest.is_zero()
            || device_digest.is_zero()
        {
            return Err(Error::InvalidManifest);
        }
        Ok(Self {
            weights,
            model_digest,
            runtime_digest,
            quantization_digest,
            device_digest,
            loaded: None,
            native_batch_calls: 0,
            native_batched_requests: 0,
        })
    }

    /// Diagnostic physical-invocation counters; they are not signed receipts.
    pub const fn native_batch_counters(&self) -> (u64, u64) {
        (self.native_batch_calls, self.native_batched_requests)
    }

    fn check_loaded(&self, handle: &DriverModelHandle) -> Result<(), Error> {
        if self.loaded.as_deref() != Some(handle.opaque_id.as_str()) {
            return Err(Error::ModelNotLoaded);
        }
        Ok(())
    }

    fn run_kernel(
        &mut self,
        handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<Vec<DriverNeuronFeatureBatchObservationV1>, Error> {
        self.check_loaded(handle)?;
        if requests.is_empty() || requests.len() > MAX_BATCH {
            return Err(Error::RequestCapacity);
        }
        // Validate the *whole* group before mutating counters or invoking the
        // kernel. No incompatible member can trigger a partially run batch.
        for request in requests {
            if request.feature_vector_q24.len() != self.weights.input_width
                || request.expected_output_width != self.weights.output_width
                || Digest32::from_str(&request.encoder_digest).ok()
                    != Some(self.weights.encoder_digest)
                || Digest32::from_str(&request.head_digest).ok() != Some(self.weights.head_digest)
                || Digest32::from_str(&request.weights_digest).ok()
                    != Some(self.weights.weight_digest)
                || request
                    .feature_vector_q24
                    .iter()
                    .any(|&x| !(-MAX_Q24..=MAX_Q24).contains(&x))
            {
                return Err(Error::FeatureContract);
            }
        }
        let started = Instant::now();
        let count = requests.len();
        let width = self.weights.output_width;
        // Output-major contiguous accumulators make each inner batch lane
        // adjacent in memory and avoid two heap allocations per request.
        let accumulator_elements = count.checked_mul(width).ok_or(Error::ArithmeticOverflow)?;
        let mut drive = vec![0_i128; accumulator_elements];
        let mut prediction = vec![0_i128; accumulator_elements];
        // The weights are the outer loop and are reused across the batch.
        // This is a single native CPU matrix pass, not a loop over model calls.
        for out in 0..width {
            for input in 0..self.weights.input_width {
                let index = out * self.weights.input_width + input;
                let drive_weight = i128::from(self.weights.drive_weights[index]);
                let prediction_weight = i128::from(self.weights.prediction_weights[index]);
                for (position, request) in requests.iter().enumerate() {
                    let value = i128::from(request.feature_vector_q24[input]);
                    let slot = out * count + position;
                    drive[slot] += drive_weight * value;
                    prediction[slot] += prediction_weight * value;
                }
            }
        }
        // Conversion is completed before output publication. Out-of-bounds
        // outputs are an error, never silently clamped to fit a signed receipt.
        let mut computed = Vec::with_capacity(count);
        for (position, request) in requests.iter().enumerate() {
            let drives = (0..width)
                .map(|out| round_q48_to_q24(drive[out * count + position]))
                .collect::<Result<Vec<_>, _>>()?;
            let predictions = (0..width)
                .map(|out| round_q48_to_q24(prediction[out * count + position]))
                .collect::<Result<Vec<_>, _>>()?;
            computed.push((request, drives, predictions));
        }
        let latency_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        let resident_bytes = self.weights.resident_bytes()?;
        let temporary_elements = accumulator_elements
            .checked_mul(2)
            .ok_or(Error::ArithmeticOverflow)?;
        // This counts the explicit accumulator buffers. It is an engineering
        // lower bound, NOT independently attested peak RSS or GPU memory.
        let explicit_allocation_bytes = u64::try_from(temporary_elements)
            .map_err(|_| Error::ArithmeticOverflow)?
            .saturating_mul(std::mem::size_of::<i128>() as u64);
        let mut results = Vec::with_capacity(count);
        for (request, drives, predictions) in computed {
            results.push(DriverNeuronFeatureBatchObservationV1 {
                request_id: request.authorization.request_id.clone(),
                input_digest: request.input_digest.clone(),
                observation: DriverNeuronFeatureObservation {
                    terminal_observed: true,
                    succeeded: true,
                    encoder_digest: request.encoder_digest.clone(),
                    head_digest: request.head_digest.clone(),
                    drive_q24: drives,
                    prediction_q24: predictions,
                    observed_memory_bytes: resident_bytes,
                    transient_allocation_bytes: explicit_allocation_bytes,
                    queue_age_micros: 0,
                    latency_micros,
                },
            });
        }
        if count > 1 {
            self.native_batch_calls = self.native_batch_calls.saturating_add(1);
            self.native_batched_requests =
                self.native_batched_requests.saturating_add(count as u64);
        }
        Ok(results)
    }
}

impl ModelDriver for CpuNeuronFeatureDriverV1 {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        if self.loaded.is_some() {
            return Err(Error::ModelAlreadyLoaded);
        }
        if manifest.model_digest != self.model_digest.to_string()
            || manifest.weights_digest != self.weights.weight_digest.to_string()
            || manifest.runtime_digest != self.runtime_digest.to_string()
            || manifest.quantization_digest != self.quantization_digest.to_string()
            || manifest.device_digest != self.device_digest.to_string()
        {
            return Err(Error::ModelMismatch);
        }
        self.loaded = Some(manifest.model_id.clone());
        Ok(DriverModelHandle {
            opaque_id: manifest.model_id.clone(),
            observed_memory_bytes: self.weights.resident_bytes()?,
        })
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        Err(Error::DriverFailure(
            "CPU neuron backend has no generic turn executor".into(),
        ))
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        self.check_loaded(&handle)?;
        self.loaded = None;
        Ok(())
    }
}

impl NeuronFeatureDriver for CpuNeuronFeatureDriverV1 {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        let mut values = self.run_kernel(handle, std::slice::from_ref(request))?;
        values
            .pop()
            .map(|entry| entry.observation)
            .ok_or(Error::FeatureContract)
    }

    fn run_neuron_features_batch(
        &mut self,
        handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<Vec<DriverNeuronFeatureBatchObservationV1>, Error> {
        if requests.len() < 2 {
            return Err(Error::RequestCapacity);
        }
        self.run_kernel(handle, requests)
    }
}

/// Correct nearest/ties-to-even Q48 -> Q24 rounding, including negative ties.
/// Integer outputs outside the versioned feature range fail closed.
fn round_q48_to_q24(value: i128) -> Result<i64, Error> {
    let base = value.div_euclid(Q24);
    let remainder = value.rem_euclid(Q24);
    let rounded = if remainder > Q24 / 2 || (remainder == Q24 / 2 && base % 2 != 0) {
        base.checked_add(1).ok_or(Error::ArithmeticOverflow)?
    } else {
        base
    };
    if rounded < i128::from(-MAX_Q24) || rounded > i128::from(MAX_Q24) {
        return Err(Error::FeatureOutputMismatch);
    }
    i64::try_from(rounded).map_err(|_| Error::ArithmeticOverflow)
}

#[cfg(test)]
#[path = "cpu_neuron_backend_tests.rs"]
mod tests;
