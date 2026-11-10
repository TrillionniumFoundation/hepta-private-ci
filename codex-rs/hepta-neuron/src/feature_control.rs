//! One bounded FeatureV1 computation on the original durable inference owner.
//! The Cell owner supplies its exact definition, original snapshot and input.
//! This adapter grants no model selection, state commit or publication rights.
//! Unknown dispatches retain their original claim across reopen; readback never
//! admits work or replaces saved costs with recovery-time observations.

use std::sync::Arc;
use std::time::Instant;

use codex_hepta_infer_core::NeuronFeatureObservationV1;
use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::NeuronModelRuntimeTupleV1;
use codex_hepta_infer_core::build_neuron_feature_receipt_v1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::generation::GenerationBindingV1;
use codex_hepta_infer_core::neuron_feature_request_digest_v1;
use codex_hepta_types::Digest32;

use crate::CellDefinitionV1;
use crate::CellInferenceAdmissionV1;
use crate::CellInferenceReadbackPortV1;
use crate::NeuronInferenceControlPort;
use crate::NeuronModelError;
use crate::SparseCheckpoint;
use crate::cell_binding::inference_request_id;
use crate::cell_inference::feature_request;

#[path = "feature_control_codec.rs"]
mod codec;

/// A host-admitted, bounded local worker. It reports actual native measurements
/// and the frozen runtime tuple. Errors mean an unknown execution, not no work.
/// The adapter checks its live clock after durable dispatch and after execution;
/// implementations must bound native work between those checks.
pub trait NeuronFeatureWorkerV1: Send + Sync {
    fn runtime_tuple(&self) -> &NeuronModelRuntimeTupleV1;

    fn execute(
        &self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureObservationV1, NeuronModelError>;
}

/// Exact original Cell input/state binding, derived by the Cell preparation
/// code. Construction validates material; it does not admit or execute work.
#[derive(Clone)]
struct NeuronFeatureControlBindingV1 {
    expected: NeuronFeatureRequestV1,
    runtime: NeuronModelRuntimeTupleV1,
    journal: GenerationBindingV1,
    payload: Vec<u8>,
    not_before_micros: u64,
}

impl NeuronFeatureControlBindingV1 {
    fn from_admission(
        definition: &CellDefinitionV1,
        admission: &CellInferenceAdmissionV1,
        worker_generation: u64,
    ) -> Result<Self, NeuronModelError> {
        let snapshot = &admission.snapshot;
        let r = &definition.runtime;
        let m = &admission.model_request;
        let definition_digest = definition.semantic_digest().map_err(|_| NeuronModelError::Rejected)?;
        if worker_generation == 0 || snapshot.definition_digest != definition_digest
            || snapshot.scope.cell_id != definition.cell_id || snapshot.scope.principal_digest.is_zero()
            || snapshot.source_frontier.is_zero() || snapshot.writer_epoch == 0
            || admission.semantic_request_digest.is_zero() || admission.admitted_at_micros == 0
            || admission.deadline_micros <= admission.admitted_at_micros
            || m.request_id != inference_request_id(&snapshot.scope, &admission.operation_id).map_err(|_| NeuronModelError::Rejected)?
            || m.config_id != r.config_id || m.generation != r.generation || m.model_id != r.model_id
            || m.encoder_digest != r.encoder_digest || m.head_digest != r.head_digest
            || m.weights_digest != r.weights_digest || m.feature_vector_q24.len() != r.input_feature_dimension
            || m.expected_output_width != r.state_width
        {
            return Err(NeuronModelError::Rejected);
        }
        let predecessor_digest = Digest32::of_parts(&[
            b"hepta.neuron.feature-control-predecessor.v1\0",
            snapshot.scope.digest().as_array(),
            snapshot.definition_digest.as_array(),
            snapshot.source_frontier.as_array(),
            &snapshot.writer_epoch.to_le_bytes(),
            &snapshot.revision.to_le_bytes(),
            snapshot.checkpoint.as_ref().map_or(Digest32::ZERO, SparseCheckpoint::digest).as_array(),
        ]);
        let expected = feature_request(m);
        let request_digest = neuron_feature_request_digest_v1(&expected)
            .map_err(|_| NeuronModelError::Rejected)?;
        let payload = codec::payload(
            &expected,
            admission.semantic_request_digest,
            snapshot.scope.digest(),
            predecessor_digest,
            admission.admitted_at_micros,
            admission.deadline_micros,
        )?;
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
            journal: GenerationBindingV1 {
                request_id: expected.request_id.to_string(),
                principal_id: snapshot.scope.principal_digest.to_string(),
                worker_generation,
                manifest_digest: definition_digest.into_array(),
                request_digest: request_digest.into_array(),
                predecessor_digest: predecessor_digest.into_array(),
                payload_digest: Digest32::of_bytes(&payload).into_array(),
                payload_bytes: u32::try_from(payload.len()).map_err(|_| NeuronModelError::Rejected)?,
                result_limit_bytes: codec::MAX_RESULT_BYTES,
                deadline_micros: admission.deadline_micros,
            },
            expected,
            runtime,
            payload,
            not_before_micros: admission.admitted_at_micros,
        })
    }
}

/// Synchronous, bounded native work. The original owner reserves result space
/// before issuing its non-replayable dispatch token and persists terminal bytes
/// before this port exposes them. One unresolved operation blocks fresh work.
pub struct ControlledNeuronFeaturePortV1<W: NeuronFeatureWorkerV1> {
    owner: DurableInferenceControl,
    definition: CellDefinitionV1,
    worker_generation: u64,
    binding: Option<NeuronFeatureControlBindingV1>,
    worker: W,
    clock: Arc<dyn Fn() -> u64 + Send + Sync>,
}

impl<W: NeuronFeatureWorkerV1> ControlledNeuronFeaturePortV1<W> {
    pub fn new(
        owner: DurableInferenceControl,
        definition: CellDefinitionV1,
        worker_generation: u64,
        worker: W,
        clock: Arc<dyn Fn() -> u64 + Send + Sync>,
    ) -> Result<Self, NeuronModelError> {
        let r = &definition.runtime;
        definition.semantic_digest().map_err(|_| NeuronModelError::Rejected)?;
        if worker_generation == 0 || worker.runtime_tuple() != &(NeuronModelRuntimeTupleV1 {
            model_id: r.model_id.clone(), model_manifest_digest: r.model_manifest_digest,
            weights_digest: r.weights_digest, tokenizer_digest: r.tokenizer_digest,
            preprocessor_digest: r.preprocessor_digest, quantization_digest: r.quantization_digest,
            runtime_digest: r.runtime_digest, device_digest: r.device_digest,
        }) {
            return Err(NeuronModelError::Rejected);
        }
        owner.generation_has_unresolved().map_err(codec::control_error)?;
        Ok(Self { owner, definition, worker_generation, binding: None, worker, clock })
    }

    fn bind(&mut self, admission: &CellInferenceAdmissionV1) -> Result<(), NeuronModelError> {
        let binding = NeuronFeatureControlBindingV1::from_admission(&self.definition, admission, self.worker_generation)?;
        self.binding = Some(binding);
        Ok(())
    }

    fn require_request(&self, request: &NeuronFeatureRequestV1) -> Result<&NeuronFeatureControlBindingV1, NeuronModelError> {
        let binding = self.binding.as_ref().ok_or(NeuronModelError::Rejected)?;
        if request != &binding.expected {
            return Err(NeuronModelError::Rejected);
        }
        Ok(binding)
    }

    fn read_original(&self) -> Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        let binding = self.binding.as_ref().ok_or(NeuronModelError::Rejected)?;
        self.owner.generation_record(&binding.journal)
            .map_err(codec::control_error)?
            .and_then(|record| record.result.as_ref())
            .map(|result| codec::decode(&binding.expected, &binding.runtime, &result.bytes))
            .transpose()
    }
}

impl<W: NeuronFeatureWorkerV1> NeuronInferenceControlPort for ControlledNeuronFeaturePortV1<W> {
    fn bind_cell_inference(&mut self, admission: &CellInferenceAdmissionV1) -> Result<(), NeuronModelError> {
        self.bind(admission)
    }

    fn execute_feature(&mut self, request: &NeuronFeatureRequestV1) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        let binding = self.require_request(request)?.clone();
        let started = Instant::now();
        if self.owner.generation_record(&binding.journal).map_err(codec::control_error)?.is_some() {
            return self.read_original()?.ok_or(NeuronModelError::Indeterminate);
        }
        if self.owner.generation_has_unresolved().map_err(codec::control_error)? {
            return Err(NeuronModelError::Indeterminate);
        }
        let admitted = (self.clock)();
        let deadline = binding.journal.deadline_micros;
        if admitted < binding.not_before_micros || admitted >= deadline {
            return Err(NeuronModelError::Rejected);
        }
        let (_, mut token) = self.owner.admit_generation(admitted, binding.journal.clone(), &binding.payload)
            .map_err(codec::control_error)?;
        if token.is_none() {
            return self.read_original()?.ok_or(NeuronModelError::Indeterminate);
        }
        let dispatch = (self.clock)();
        if dispatch < admitted || dispatch >= deadline {
            return Err(NeuronModelError::Indeterminate);
        }
        self.owner.dispatch_generation(dispatch, &mut token).map_err(codec::control_error)?;
        // Dispatch fsync can consume the remaining lease. Recheck at the actual
        // native entry, with no durable write between this check and execution.
        let entered = (self.clock)();
        if entered < dispatch || entered >= deadline {
            return Err(NeuronModelError::Indeterminate);
        }
        let queue = u64::try_from(started.elapsed().as_micros()).map_err(|_| NeuronModelError::Indeterminate)?;
        let mut observation = self.worker.execute(request)?;
        let completed = (self.clock)();
        if completed < entered || observation.status == NeuronFeatureTerminalStatusV1::Indeterminate {
            return Err(NeuronModelError::Indeterminate);
        }
        observation.queue_age_micros = observation.queue_age_micros.checked_add(queue)
            .ok_or(NeuronModelError::Indeterminate)?;
        if completed >= deadline {
            observation.status = NeuronFeatureTerminalStatusV1::Cancelled;
            observation.drive_q24.clear();
            observation.prediction_q24.clear();
        }
        let receipt = build_neuron_feature_receipt_v1(request, binding.runtime, observation)
            .map_err(|_| NeuronModelError::Indeterminate)?;
        let bytes = codec::encode(&receipt)?;
        self.owner.settle_generation(&binding.journal, bytes).map_err(codec::control_error)?;
        Ok(receipt)
    }
}

impl<W: NeuronFeatureWorkerV1> CellInferenceReadbackPortV1 for ControlledNeuronFeaturePortV1<W> {
    fn bind_cell_readback(&mut self, admission: &CellInferenceAdmissionV1) -> Result<(), NeuronModelError> {
        self.bind(admission)
    }

    fn read_feature(&mut self, request: &NeuronFeatureRequestV1) -> Result<Option<NeuronFeatureReceiptV1>, NeuronModelError> {
        self.require_request(request)?;
        self.read_original()
    }
}

#[cfg(test)]
#[path = "feature_control_tests.rs"]
mod tests;
