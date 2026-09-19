//! Product composition of authenticated local-model execution with neuron.runtime.
//!
//! The intelligence facade supplies one already-authorized worker request and
//! consumes only the resulting advisory neuron receipt. It cannot mint the
//! worker lease, install a model, select a candidate artifact or execute effects.

use std::str::FromStr;

use codex_hepta_infer_worker_host::model_worker::Error as WorkerError;
use codex_hepta_infer_worker_host::model_worker::ExecutionStatus;
use codex_hepta_infer_worker_host::model_worker::InferenceWorker;
use codex_hepta_infer_worker_host::model_worker::ModelDriver;
use codex_hepta_infer_worker_host::model_worker::NeuronFeatureDriver;
use codex_hepta_infer_worker_host::model_worker::NeuronFeatureRequest;
use codex_hepta_infer_worker_host::model_worker::WorkerRequest;
use codex_hepta_infer_worker_host::model_worker::canonical_neuron_feature_payload_digest;
use codex_hepta_neuron::AnchorWitnessStore;
use codex_hepta_neuron::LocalModelRuntimeReceiptV1;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_neuron::NeuronModelOutputV1;
use codex_hepta_neuron::NeuronModelPort;
use codex_hepta_neuron::NeuronModelRequestV1;
use codex_hepta_neuron::NeuronRuntime;
use codex_hepta_neuron::NeuronRuntimeError;
use codex_hepta_neuron::NeuronRuntimeOutputV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::canonical_model_output_digest_v1;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorizedNeuronTickV1 {
    pub now_ms: u64,
    pub authorization: WorkerRequest,
    pub tick: NeuronTickInputV1,
}

struct WorkerNeuronModelPort<'a, D: ModelDriver + NeuronFeatureDriver> {
    worker: &'a mut InferenceWorker<D>,
    now_ms: u64,
    authorization: Option<WorkerRequest>,
}

impl<D: ModelDriver + NeuronFeatureDriver> NeuronModelPort for WorkerNeuronModelPort<'_, D> {
    fn execute(
        &mut self,
        request: &NeuronModelRequestV1,
    ) -> Result<NeuronModelOutputV1, NeuronModelError> {
        let authorization = self
            .authorization
            .take()
            .ok_or(NeuronModelError::Rejected)?;
        let feature_request = feature_request(request, authorization);
        let observed = self
            .worker
            .run_neuron_features(self.now_ms, request.model_id.as_str(), feature_request)
            .map_err(map_worker_error)?;
        match observed.status {
            ExecutionStatus::Succeeded if observed.terminal_observed => {}
            ExecutionStatus::Indeterminate => return Err(NeuronModelError::Indeterminate),
            ExecutionStatus::Failed | ExecutionStatus::Cancelled => {
                return Err(NeuronModelError::Rejected);
            }
            ExecutionStatus::Succeeded => return Err(NeuronModelError::Indeterminate),
        }

        let model_id =
            StableId::new(observed.manifest.model_id).map_err(|_| NeuronModelError::Rejected)?;
        let weights_digest = parse_digest(&observed.manifest.weights_digest)?;
        if model_id != request.model_id || weights_digest != request.weights_digest {
            return Err(NeuronModelError::Rejected);
        }
        let runtime_receipt = LocalModelRuntimeReceiptV1 {
            model_id,
            weights_digest,
            tokenizer_digest: parse_digest(&observed.manifest.tokenizer_digest)?,
            preprocessor_digest: parse_digest(&observed.manifest.preprocessor_digest)?,
            quantization_id: digest_id("quantization", &observed.manifest.quantization_digest)?,
            backend_id: digest_id("runtime", &observed.manifest.runtime_digest)?,
            device_identity_digest: parse_digest(&observed.manifest.device_digest)?,
            latency_micros: observed.latency_micros,
            resident_bytes: observed.observed_memory_bytes,
        };
        let encoder_digest = parse_digest(&observed.encoder_digest)?;
        let head_digest = parse_digest(&observed.head_digest)?;
        let output_digest = canonical_model_output_digest_v1(
            &observed.drive_q24,
            &observed.prediction_q24,
            &runtime_receipt,
        )
        .map_err(|_| NeuronModelError::Rejected)?;
        Ok(NeuronModelOutputV1 {
            encoder_digest,
            head_digest,
            output_digest,
            drive_q24: observed.drive_q24,
            prediction_q24: observed.prediction_q24,
            queue_age_micros: observed.queue_age_micros,
            transient_allocation_bytes: observed.transient_allocation_bytes,
            runtime_receipt,
        })
    }
}

pub fn expected_neuron_worker_payload_digest_v1<W: AnchorWitnessStore>(
    runtime: &NeuronRuntime<W>,
    tick: &NeuronTickInputV1,
    authorization: &WorkerRequest,
) -> Result<String, NeuronRuntimeError> {
    let model_request = runtime.model_request(tick)?;
    let feature_request = feature_request(&model_request, authorization.clone());
    Ok(canonical_neuron_feature_payload_digest(&feature_request))
}

pub fn run_neuron_tick_v1<W, D>(
    runtime: &mut NeuronRuntime<W>,
    worker: &mut InferenceWorker<D>,
    request: AuthorizedNeuronTickV1,
) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError>
where
    W: AnchorWitnessStore,
    D: ModelDriver + NeuronFeatureDriver,
{
    let mut port = WorkerNeuronModelPort {
        worker,
        now_ms: request.now_ms,
        authorization: Some(request.authorization),
    };
    runtime.tick(&mut port, request.tick)
}

fn feature_request(
    request: &NeuronModelRequestV1,
    authorization: WorkerRequest,
) -> NeuronFeatureRequest {
    NeuronFeatureRequest {
        authorization,
        encoder_digest: request.encoder_digest.to_string(),
        head_digest: request.head_digest.to_string(),
        input_digest: request.input_digest.to_string(),
        feature_vector_q24: request.feature_vector_q24.clone(),
        expected_output_width: request.expected_output_width,
    }
}

fn parse_digest(value: &str) -> Result<Digest32, NeuronModelError> {
    Digest32::from_str(value).map_err(|_| NeuronModelError::Rejected)
}

fn digest_id(prefix: &str, value: &str) -> Result<StableId, NeuronModelError> {
    parse_digest(value)?;
    StableId::new(format!("{prefix}:{value}")).map_err(|_| NeuronModelError::Rejected)
}

fn map_worker_error(error: WorkerError) -> NeuronModelError {
    match error {
        WorkerError::DriverFailure(_)
        | WorkerError::ModelNotLoaded
        | WorkerError::ModelCapacity
        | WorkerError::RequestCapacity => NeuronModelError::Unavailable,
        _ => NeuronModelError::Rejected,
    }
}

#[cfg(test)]
#[path = "neuron_runtime_tests.rs"]
mod tests;
