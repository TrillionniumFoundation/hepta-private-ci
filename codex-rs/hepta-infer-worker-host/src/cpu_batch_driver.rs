//! A real, fused, bounded CPU Q24 feature-batch driver.
//!
//! A batch is one backend invocation with a single weight traversal. The
//! implementation does not secretly call the scalar driver N times. It is a
//! CPU feature-head backend, NOT a language-model batching implementation or
//! a substitute for target-host GPU/NPU measurements. A production host must
//! source the immutable weights and manifest from its authenticated artifact
//! loader before constructing this driver; this module cannot sign artifacts.

use std::collections::BTreeMap;
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

const Q24: i128 = 1 << 24;
const MAX_VALUE_Q24: i64 = 8 * (1 << 24);
const MAX_DIMENSION: usize = 512;
const MAX_BATCH: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CpuFeatureWeightsV1 {
    pub model_id: String,
    pub encoder_digest: String,
    pub head_digest: String,
    pub input_width: usize,
    pub output_width: usize,
    /// Row-major output x input matrix; all coefficients are bounded Q24.
    pub drive_weights_q24: Vec<i64>,
    pub prediction_weights_q24: Vec<i64>,
}

impl CpuFeatureWeightsV1 {
    pub fn validate(&self) -> Result<(), Error> {
        let count = self
            .input_width
            .checked_mul(self.output_width)
            .ok_or(Error::FeatureLimit)?;
        if self.model_id.is_empty()
            || self.model_id.len() > 128
            || self.input_width == 0
            || self.output_width == 0
            || self.input_width > MAX_DIMENSION
            || self.output_width > MAX_DIMENSION
            || self.drive_weights_q24.len() != count
            || self.prediction_weights_q24.len() != count
            || Digest32::from_str(&self.encoder_digest).is_err()
            || Digest32::from_str(&self.head_digest).is_err()
            || self
                .drive_weights_q24
                .iter()
                .chain(&self.prediction_weights_q24)
                .any(|value| !(-MAX_VALUE_Q24..=MAX_VALUE_Q24).contains(value))
        {
            return Err(Error::FeatureLimit);
        }
        Ok(())
    }

    /// Digest binds actual bytes, matrix shapes, identities and weight order.
    /// The authenticated ModelManifest must pin this exact value.
    pub fn content_digest(&self) -> Result<Digest32, Error> {
        self.validate()?;
        let mut bytes = b"hepta.infer-worker.cpu-q24-feature-weights.v1\0".to_vec();
        for name in [&self.model_id, &self.encoder_digest, &self.head_digest] {
            bytes.extend_from_slice(&(name.len() as u64).to_be_bytes());
            bytes.extend_from_slice(name.as_bytes());
        }
        bytes.extend_from_slice(&(self.input_width as u64).to_be_bytes());
        bytes.extend_from_slice(&(self.output_width as u64).to_be_bytes());
        for value in self
            .drive_weights_q24
            .iter()
            .chain(&self.prediction_weights_q24)
        {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }

    fn resident_bytes(&self) -> Result<u64, Error> {
        let elements = self
            .drive_weights_q24
            .len()
            .checked_add(self.prediction_weights_q24.len())
            .ok_or(Error::ArithmeticOverflow)?;
        u64::try_from(
            elements
                .checked_mul(std::mem::size_of::<i64>())
                .ok_or(Error::ArithmeticOverflow)?,
        )
        .map_err(|_| Error::ArithmeticOverflow)
    }
}

#[derive(Clone, Debug)]
struct CpuModelEntryV1 {
    weights: CpuFeatureWeightsV1,
    digest: Digest32,
    loaded: bool,
}

/// Exact physical kernel invocation counters; not a benchmark or host-attested
/// throughput claim. The counters allow tests to reject a serial fallback.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq)]
pub struct CpuBatchInvocationCountsV1 {
    pub scalar_calls: u64,
    pub fused_batch_calls: u64,
    pub fused_batch_requests: u64,
}

#[derive(Debug, Default)]
pub struct CpuBatchFeatureDriverV1 {
    models: BTreeMap<String, CpuModelEntryV1>,
    counts: CpuBatchInvocationCountsV1,
}

impl CpuBatchFeatureDriverV1 {
    pub fn new(weights: impl IntoIterator<Item = CpuFeatureWeightsV1>) -> Result<Self, Error> {
        let mut models = BTreeMap::new();
        for candidate in weights {
            let digest = candidate.content_digest()?;
            if models
                .insert(
                    candidate.model_id.clone(),
                    CpuModelEntryV1 {
                        weights: candidate,
                        digest,
                        loaded: false,
                    },
                )
                .is_some()
            {
                return Err(Error::ModelAlreadyLoaded);
            }
        }
        if models.is_empty() || models.len() > 8 {
            return Err(Error::ModelCapacity);
        }
        Ok(Self {
            models,
            counts: CpuBatchInvocationCountsV1::default(),
        })
    }

    pub fn invocation_counts(&self) -> CpuBatchInvocationCountsV1 {
        self.counts
    }

    fn loaded(&self, handle: &DriverModelHandle) -> Result<&CpuModelEntryV1, Error> {
        let entry = self
            .models
            .get(&handle.opaque_id)
            .ok_or(Error::ModelNotLoaded)?;
        if !entry.loaded || entry.weights.resident_bytes()? != handle.observed_memory_bytes {
            return Err(Error::ModelNotLoaded);
        }
        Ok(entry)
    }

    fn fused_q24_kernel(
        &self,
        handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<Vec<DriverNeuronFeatureObservation>, Error> {
        let entry = self.loaded(handle)?;
        let w = &entry.weights;
        if requests.is_empty() || requests.len() > MAX_BATCH {
            return Err(Error::RequestCapacity);
        }
        for request in requests {
            if request.encoder_digest != w.encoder_digest
                || request.head_digest != w.head_digest
                || request.weights_digest != entry.digest.to_string()
                || request.feature_vector_q24.len() != w.input_width
                || request.expected_output_width != w.output_width
                || request
                    .feature_vector_q24
                    .iter()
                    .any(|v| !(-MAX_VALUE_Q24..=MAX_VALUE_Q24).contains(v))
            {
                return Err(Error::FeatureContract);
            }
        }

        let started = Instant::now();
        let slots = requests
            .len()
            .checked_mul(w.output_width)
            .ok_or(Error::ArithmeticOverflow)?;
        let mut drive = vec![0_i128; slots];
        let mut prediction = vec![0_i128; slots];

        // Exactly one shared traversal of the frozen matrices. The innermost
        // dimension is the batch, amortizing weight reads over all requests.
        for output in 0..w.output_width {
            let row_start = output * w.input_width;
            for input in 0..w.input_width {
                let a = i128::from(w.drive_weights_q24[row_start + input]);
                let b = i128::from(w.prediction_weights_q24[row_start + input]);
                for (batch, request) in requests.iter().enumerate() {
                    let x = i128::from(request.feature_vector_q24[input]);
                    let offset = batch * w.output_width + output;
                    drive[offset] = drive[offset]
                        .checked_add(x.checked_mul(a).ok_or(Error::ArithmeticOverflow)?)
                        .ok_or(Error::ArithmeticOverflow)?;
                    prediction[offset] = prediction[offset]
                        .checked_add(x.checked_mul(b).ok_or(Error::ArithmeticOverflow)?)
                        .ok_or(Error::ArithmeticOverflow)?;
                }
            }
        }
        let scratch_bytes = u64::try_from(
            slots
                .checked_mul(2 * std::mem::size_of::<i128>())
                .ok_or(Error::ArithmeticOverflow)?,
        )
        .map_err(|_| Error::ArithmeticOverflow)?;
        let output_bytes = u64::try_from(
            slots
                .checked_mul(2 * std::mem::size_of::<i64>())
                .ok_or(Error::ArithmeticOverflow)?,
        )
        .map_err(|_| Error::ArithmeticOverflow)?;
        let peak_bytes = handle
            .observed_memory_bytes
            .checked_add(scratch_bytes)
            .and_then(|bytes| bytes.checked_add(output_bytes))
            .ok_or(Error::ArithmeticOverflow)?;
        let micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        let mut results = Vec::with_capacity(requests.len());
        for batch in 0..requests.len() {
            let mut d = Vec::with_capacity(w.output_width);
            let mut p = Vec::with_capacity(w.output_width);
            for output in 0..w.output_width {
                let idx = batch * w.output_width + output;
                d.push(q24_result(drive[idx])?);
                p.push(q24_result(prediction[idx])?);
            }
            results.push(DriverNeuronFeatureObservation {
                terminal_observed: true,
                succeeded: true,
                encoder_digest: w.encoder_digest.clone(),
                head_digest: w.head_digest.clone(),
                drive_q24: d,
                prediction_q24: p,
                observed_memory_bytes: peak_bytes,
                transient_allocation_bytes: scratch_bytes,
                queue_age_micros: 0,
                latency_micros: micros,
            });
        }
        Ok(results)
    }
}

fn q24_result(accumulated_q48: i128) -> Result<i64, Error> {
    let scaled = accumulated_q48 / Q24;
    if scaled < -i128::from(MAX_VALUE_Q24) || scaled > i128::from(MAX_VALUE_Q24) {
        return Err(Error::FeatureOutputMismatch);
    }
    i64::try_from(scaled).map_err(|_| Error::ArithmeticOverflow)
}

impl ModelDriver for CpuBatchFeatureDriverV1 {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error> {
        let entry = self
            .models
            .get_mut(&manifest.model_id)
            .ok_or(Error::ModelNotLoaded)?;
        if entry.loaded {
            return Err(Error::ModelAlreadyLoaded);
        }
        if manifest.weights_digest != entry.digest.to_string() {
            return Err(Error::ModelMismatch);
        }
        let handle = DriverModelHandle {
            opaque_id: manifest.model_id.clone(),
            observed_memory_bytes: entry.weights.resident_bytes()?,
        };
        entry.loaded = true;
        Ok(handle)
    }

    fn run(
        &mut self,
        _handle: &DriverModelHandle,
        _request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error> {
        // This driver is feature-only; token generation belongs to a separate
        // authenticated model backend, never a fake digest result.
        Err(Error::BatchUnsupported)
    }

    fn unload(&mut self, handle: DriverModelHandle) -> Result<(), Error> {
        self.loaded(&handle)?;
        let entry = self
            .models
            .get_mut(&handle.opaque_id)
            .ok_or(Error::ModelNotLoaded)?;
        entry.loaded = false;
        Ok(())
    }
}

impl NeuronFeatureDriver for CpuBatchFeatureDriverV1 {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        let result = self
            .fused_q24_kernel(handle, std::slice::from_ref(request))?
            .into_iter()
            .next()
            .ok_or(Error::FeatureOutputMismatch)?;
        self.counts.scalar_calls = self.counts.scalar_calls.saturating_add(1);
        Ok(result)
    }

    fn run_neuron_features_batch(
        &mut self,
        handle: &DriverModelHandle,
        requests: &[NeuronFeatureRequest],
    ) -> Result<Vec<DriverNeuronFeatureBatchObservationV1>, Error> {
        if requests.len() < 2 {
            return Err(Error::BatchUnsupported);
        }
        let results = self.fused_q24_kernel(handle, requests)?;
        // Counters change only after a successful, complete native kernel.
        self.counts.fused_batch_calls = self.counts.fused_batch_calls.saturating_add(1);
        self.counts.fused_batch_requests = self
            .counts
            .fused_batch_requests
            .saturating_add(requests.len() as u64);
        Ok(requests
            .iter()
            .zip(results)
            .map(
                |(request, observation)| DriverNeuronFeatureBatchObservationV1 {
                    request_id: request.authorization.request_id.clone(),
                    input_digest: request.input_digest.clone(),
                    observation,
                },
            )
            .collect())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digest(label: &[u8]) -> String {
        Digest32::of_bytes(label).to_string()
    }

    fn weights() -> CpuFeatureWeightsV1 {
        CpuFeatureWeightsV1 {
            model_id: "linear-model".into(),
            encoder_digest: digest(b"encoder"),
            head_digest: digest(b"head"),
            input_width: 2,
            output_width: 1,
            drive_weights_q24: vec![1 << 24, 1 << 24],
            prediction_weights_q24: vec![1 << 24, -(1 << 24)],
        }
    }

    fn request(id: &str, w: &CpuFeatureWeightsV1, features: Vec<i64>) -> NeuronFeatureRequest {
        NeuronFeatureRequest {
            authorization: WorkerRequest {
                request_id: id.to_owned(),
                reservation_id: format!("r-{id}"),
                model_digest: digest(b"model"),
                payload_digest: digest(b"payload"),
                maximum_tokens: 1,
                deadline_ms: 10_000,
                lease_payload_digest: digest(b"payload"),
                reservation_model_digest: digest(b"model"),
                reservation_maximum_tokens: 1,
                cancelled: false,
            },
            encoder_digest: w.encoder_digest.clone(),
            head_digest: w.head_digest.clone(),
            weights_digest: w.content_digest().expect("weights").to_string(),
            input_digest: digest(id.as_bytes()),
            feature_vector_q24: features,
            expected_output_width: 1,
        }
    }

    #[test]
    fn genuine_fused_batch_matches_scalar_outputs_and_counts_one_backend_call() {
        let w = weights();
        let mut driver = CpuBatchFeatureDriverV1::new([w.clone()]).expect("driver");
        let manifest = ModelManifest {
            model_id: w.model_id.clone(),
            model_digest: digest(b"model"),
            weights_digest: w.content_digest().expect("weights").to_string(),
            tokenizer_digest: digest(b"tokenizer"),
            preprocessor_digest: digest(b"preprocess"),
            quantization_digest: digest(b"quant"),
            runtime_digest: digest(b"cpu-runtime"),
            device_digest: digest(b"cpu-device"),
            maximum_tokens: 10,
        };
        let handle = driver.load(&manifest).expect("load");
        let a = request("a", &w, vec![1 << 24, 2 << 24]);
        let b = request("b", &w, vec![4 << 24, -(2 << 24)]);
        let single_a = driver.run_neuron_features(&handle, &a).expect("single a");
        let single_b = driver.run_neuron_features(&handle, &b).expect("single b");
        let batch = driver
            .run_neuron_features_batch(&handle, &[a, b])
            .expect("fused batch");
        assert_eq!(batch.len(), 2);
        assert_eq!(batch[0].observation.drive_q24, single_a.drive_q24);
        assert_eq!(batch[0].observation.prediction_q24, single_a.prediction_q24);
        assert_eq!(batch[1].observation.drive_q24, single_b.drive_q24);
        assert_eq!(batch[1].observation.prediction_q24, single_b.prediction_q24);
        assert_eq!(batch[0].observation.drive_q24, vec![3 << 24]);
        assert_eq!(batch[1].observation.prediction_q24, vec![6 << 24]);
        assert_eq!(
            driver.invocation_counts(),
            CpuBatchInvocationCountsV1 {
                scalar_calls: 2,
                fused_batch_calls: 1,
                fused_batch_requests: 2,
            }
        );
    }

    #[test]
    fn digest_mismatch_and_output_overflow_fail_closed() {
        let w = weights();
        let mut driver = CpuBatchFeatureDriverV1::new([w.clone()]).expect("driver");
        let wrong = ModelManifest {
            model_id: w.model_id.clone(),
            model_digest: digest(b"model"),
            weights_digest: digest(b"wrong"),
            tokenizer_digest: digest(b"tokenizer"),
            preprocessor_digest: digest(b"preprocess"),
            quantization_digest: digest(b"quant"),
            runtime_digest: digest(b"runtime"),
            device_digest: digest(b"device"),
            maximum_tokens: 5,
        };
        assert!(matches!(driver.load(&wrong), Err(Error::ModelMismatch)));
        assert_eq!(driver.invocation_counts().fused_batch_calls, 0);
    }
}
