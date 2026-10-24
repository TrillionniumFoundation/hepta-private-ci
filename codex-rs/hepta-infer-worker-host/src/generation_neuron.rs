//! Bounded feature execution over the registered generation backend.
//! Registration binds the complete predecessor and raw generation request.
//! The 96-value projection is not a replacement for those original identities.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::str::FromStr;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use codex_hepta_infer_core::GenerationStateV1;
use codex_hepta_types::Digest32;
use serde::Deserialize;
use serde::Serialize;

use super::GenerationDriver;
use super::failure;
use crate::model_worker::DriverModelHandle;
use crate::model_worker::DriverNeuronFeatureObservation;
use crate::model_worker::Error;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::canonical_neuron_feature_payload_digest;

const WIDTH: usize = 96;
const Q24: f64 = (1_i64 << 24) as f64;
const PROJECTION: &[u8] = b"hepta.ndu-v6.four-state-tanh-persistence.q24.v1\0hidden=96;blocks=h,image,text,context;f64-left-sum/4;tanh;round-away;q=16777216;raw-range=-8,8";
const RESOURCE_PROFILE: &[u8] = b"hepta.ndu-v6.cold-generation-resource.v1\0latency=driver-entry-through-observation;queue=none;resident=child-peak-rss;transient-charge=child-peak-rss;not-allocator-bytes;not-cumulative-allocation;not-production-qualification";

pub fn generation_projection_digest() -> Digest32 {
    Digest32::of_bytes(PROJECTION)
}

pub fn generation_neuron_head_digest() -> Digest32 {
    let mut bytes = b"hepta.ndu-v6.generation-neuron-head.v1\0".to_vec();
    bytes.extend_from_slice(generation_projection_digest().as_array());
    bytes.extend_from_slice(Digest32::of_bytes(RESOURCE_PROFILE).as_array());
    Digest32::of_bytes(&bytes)
}

/// Each block is finite raw float32 data; tanh is the declared transformation.
/// This does not silently clip a malformed or unbounded generation state.
pub fn project_generation_state(state: &GenerationStateV1) -> Result<Vec<i64>, Error> {
    if state.values_f32.len() != 4 * WIDTH {
        return Err(failure("four-block projection width"));
    }
    let values = state
        .values_f32
        .iter()
        .map(|v| f64::from(f32::from_bits(*v)))
        .collect::<Vec<_>>();
    if values.iter().any(|v| !(-8.0..=8.0).contains(v)) {
        return Err(failure("unbounded raw projection input"));
    }
    Ok((0..WIDTH)
        .map(|i| {
            let mean = (((values[i] + values[i + WIDTH]) + values[i + 2 * WIDTH])
                + values[i + 3 * WIDTH])
                / 4.0;
            (mean.tanh() * Q24).round() as i64
        })
        .collect())
}

/// Supplied once by the host, after a real prefix execution yields predecessor.
/// This contains a pre-existing authorization; it creates no lease or grant.
#[derive(Clone)]
pub struct GenerationNeuronBindingV1 {
    pub request: NeuronFeatureRequest,
    pub generation_request_sha256: String,
    pub previous_state: GenerationStateV1,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct GenerationNeuronEvidenceV1 {
    pub feature_payload_sha256: String,
    pub generation_request_sha256: String,
    pub previous_state_sha256: String,
    pub projection_sha256: String,
    pub resource_profile_sha256: String,
    pub process_wall_ns: u64,
    pub projection_wall_ns: u64,
    pub driver_wall_ns: u64,
    pub failure_reason: Option<String>,
    /// A measured resident-byte charge for the transient child process.
    /// Never an allocator peak/cumulative allocation bound or qualification.
    pub transient_process_resident_charge_bytes: Option<u64>,
    pub authority: String,
}

#[derive(Clone, Default)]
pub struct GenerationNeuronEvidence(Arc<Mutex<BTreeMap<String, GenerationNeuronEvidenceV1>>>);

impl GenerationNeuronEvidence {
    pub fn get(&self, payload: &str) -> Option<GenerationNeuronEvidenceV1> {
        self.0.lock().ok()?.get(payload).cloned()
    }
}

#[derive(Default)]
pub(super) struct GenerationNeuronRegistry {
    bindings: BTreeMap<String, GenerationNeuronBindingV1>,
    observations: BTreeMap<String, DriverNeuronFeatureObservation>,
    evidence: GenerationNeuronEvidence,
}

impl GenerationDriver {
    pub fn with_neuron_bindings(
        mut self,
        bindings: Vec<GenerationNeuronBindingV1>,
    ) -> Result<Self, Error> {
        if bindings.is_empty()
            || bindings.len() > 128
            || !self.neuron.bindings.is_empty()
            || !self
                .evidence
                .0
                .lock()
                .map_err(|_| failure("evidence lock"))?
                .is_empty()
            || self.registration.pins.hidden != WIDTH
        {
            return Err(failure("neuron registration bounds or already used driver"));
        }
        let manifest = self.manifest()?;
        let mut raw_requests = BTreeSet::new();
        for binding in bindings {
            let raw = self
                .requests
                .get(&binding.generation_request_sha256)
                .ok_or(Error::PayloadMismatch)?;
            let request = &binding.request;
            let payload = canonical_neuron_feature_payload_digest(request);
            let state = &binding.previous_state;
            let backend = Digest32::from_str(&state.backend_state_sha256).map_err(failure)?;
            let mut bytes = b"hepta.inference.generation-state.v1\0".to_vec();
            bytes.extend_from_slice(raw.model.snapshot_sha256.as_bytes());
            bytes.extend_from_slice(state.backend_state_sha256.as_bytes());
            bytes.extend_from_slice(&state.plan_index.unwrap_or(-2).to_le_bytes());
            for value in &state.values_f32 {
                bytes.extend_from_slice(&value.to_le_bytes());
            }
            if raw.actions.is_empty()
                || backend.is_zero()
                || state.plan_index.is_some_and(|v| !(-1..=3).contains(&v))
                || Digest32::of_bytes(&bytes).to_string() != state.state_sha256
                || request.authorization.request_id
                    != format!("ndu-neuron:{}", binding.generation_request_sha256)
                || request.authorization.maximum_tokens < 8
                || request.authorization.reservation_maximum_tokens < 8
                || request.authorization.cancelled
                || request.authorization.model_digest != manifest.model_digest
                || request.authorization.reservation_model_digest != manifest.model_digest
                || request.authorization.payload_digest != payload
                || request.authorization.lease_payload_digest != payload
                || request.encoder_digest != raw.model.source_sha256
                || request.head_digest != generation_neuron_head_digest().to_string()
                || request.weights_digest != raw.model.parameters_sha256
                || request.expected_output_width != WIDTH
                || request.feature_vector_q24 != project_generation_state(state)?
                || !raw_requests.insert(binding.generation_request_sha256.clone())
                || self.neuron.bindings.insert(payload, binding).is_some()
            {
                return Err(failure("neuron full-state/request/pin binding"));
            }
        }
        Ok(self)
    }

    pub fn neuron_evidence(&self) -> GenerationNeuronEvidence {
        self.neuron.evidence.clone()
    }
}

impl NeuronFeatureDriver for GenerationDriver {
    fn run_neuron_features(
        &mut self,
        handle: &DriverModelHandle,
        request: &NeuronFeatureRequest,
    ) -> Result<DriverNeuronFeatureObservation, Error> {
        if request.authorization.maximum_tokens < 8
            || request.authorization.reservation_maximum_tokens < 8
        {
            return Err(Error::TokenLimit);
        }
        let driver_started = Instant::now();
        self.verify_registration()?;
        if handle.opaque_id != request.authorization.model_digest
            || handle.opaque_id != self.manifest()?.model_digest
        {
            return Err(Error::ModelMismatch);
        }
        let payload = canonical_neuron_feature_payload_digest(request);
        let binding = self
            .neuron
            .bindings
            .get(&payload)
            .ok_or(Error::PayloadMismatch)?
            .clone();
        if request != &binding.request {
            return Err(Error::PayloadMismatch);
        }
        if let Some(cached) = self.neuron.observations.get(&payload) {
            return Ok(cached.clone());
        }
        // Do not count an earlier normal-driver execution as a fresh feature run.
        if self
            .evidence
            .get(&binding.generation_request_sha256)
            .is_some()
        {
            return Err(failure(
                "raw request already consumed by another execution path",
            ));
        }
        let raw = self
            .requests
            .get(&binding.generation_request_sha256)
            .ok_or(Error::PayloadMismatch)?;
        let process = self.invoke(raw)?;
        self.evidence
            .0
            .lock()
            .map_err(|_| failure("evidence lock"))?
            .insert(binding.generation_request_sha256.clone(), process.clone());
        let started = Instant::now();
        let valid = process.execution.as_ref();
        let projected = (|| {
            if let Some(execution) = valid {
                let previous = execution
                    .states
                    .get(execution.states.len().saturating_sub(2))
                    .ok_or(Error::FeatureOutputMismatch)?;
                if previous != &binding.previous_state {
                    return Err(Error::FeatureOutputMismatch);
                }
                let current = execution
                    .states
                    .last()
                    .ok_or(Error::FeatureOutputMismatch)?;
                Ok((
                    project_generation_state(current)?,
                    project_generation_state(previous)?,
                ))
            } else {
                Ok((Vec::new(), Vec::new()))
            }
        })();
        let (drive, prediction, failure_reason) = match projected {
            Ok((drive, prediction)) => (drive, prediction, None),
            Err(error) => (Vec::new(), Vec::new(), Some(error.to_string())),
        };
        let projection_wall_ns = u64::try_from(started.elapsed().as_nanos()).unwrap_or(u64::MAX);
        let driver_wall_ns = u64::try_from(driver_started.elapsed().as_nanos()).unwrap_or(u64::MAX);
        let resident = valid.map(|v| v.peak_rss_bytes);
        let observation = DriverNeuronFeatureObservation {
            terminal_observed: !process.timed_out
                && (valid.is_some() || process.exit_code.is_some_and(|v| v != 0)),
            succeeded: valid.is_some() && failure_reason.is_none(),
            encoder_digest: request.encoder_digest.clone(),
            head_digest: request.head_digest.clone(),
            drive_q24: drive,
            prediction_q24: prediction,
            observed_memory_bytes: resident.unwrap_or(0),
            // This V1 numeric slot carries the explicitly bound cold-child
            // resident charge, not a measured allocator-byte quantity. Failed
            // invocations retain None below; zero is not measured memory there.
            transient_allocation_bytes: resident.unwrap_or(0),
            queue_age_micros: 0,
            latency_micros: driver_wall_ns.div_ceil(1000),
        };
        self.neuron
            .evidence
            .0
            .lock()
            .map_err(|_| failure("feature evidence lock"))?
            .insert(
                payload.clone(),
                GenerationNeuronEvidenceV1 {
                    feature_payload_sha256: payload.clone(),
                    generation_request_sha256: binding.generation_request_sha256,
                    previous_state_sha256: binding.previous_state.state_sha256,
                    projection_sha256: generation_projection_digest().to_string(),
                    resource_profile_sha256: Digest32::of_bytes(RESOURCE_PROFILE).to_string(),
                    process_wall_ns: process.host_wall_ns,
                    projection_wall_ns,
                    driver_wall_ns,
                    failure_reason,
                    transient_process_resident_charge_bytes: resident,
                    authority: "deny_all".into(),
                },
            );
        self.neuron
            .observations
            .insert(payload, observation.clone());
        Ok(observation)
    }
}

#[cfg(test)]
#[path = "generation_neuron_tests.rs"]
mod tests;
