//! Native, single-use bridge from a pre-admitted Worker reservation to the
//! inference.control Neuron feature port and the existing Neuron ModelPort.
//!
//! The calling host must obtain and authenticate the WorkerRequest from the
//! actual inference reservation/lease owner. This adapter NEVER fabricates a
//! reservation, grant, selected route, signed final-use token or model load.
//! The worker enforces its loaded manifest, resource grant, lease payload and
//! reservation; the typed receipt is independently checked before release.
//!
//! InferenceWorker's driver remains host-provided; a fixture ModelDriver is not
//! proof that real Laya weights were loaded on a production machine.

use codex_hepta_infer_core::NeuronFeatureReceiptV1;
use codex_hepta_infer_core::NeuronFeatureRequestV1;
use codex_hepta_infer_core::verify_neuron_feature_receipt_v1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_types::Generation;
use std::time::Instant;

use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelDriver;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::WorkerRequest;
use crate::model_worker::canonical_neuron_feature_payload_digest;

/// One immutable, preexisting invocation/reservation against a loaded worker.
/// A rejected preflight still consumes it: resubmission requires new admission.
pub struct WorkerNeuronControlPort<'a, D: ModelDriver + NeuronFeatureDriver> {
    worker: &'a mut InferenceWorker<D>,
    model_id: String,
    /// The Neuron model/Cell generation, independently committed by the
    /// durable inference request. This is NOT the Worker process generation.
    neuron_generation: Generation,
    reservation: Option<WorkerRequest>,
    observed_now_ms: u64,
    /// Monotonic instant from BEFORE the durable owner starts its read/fsync.
    /// Prevents a port retained past its lease deadline from reusing claim time.
    claim_started: Instant,
}

impl<'a, D: ModelDriver + NeuronFeatureDriver> WorkerNeuronControlPort<'a, D> {
    /// Internal handoff after the trusted same-crate inference.control owner
    /// has fsynced a one-time Dispatching claim. Unit tests exercise older
    /// lower-level rejection paths without manufacturing production authority.
    ///
    /// Do NOT expose this constructor outside the crate: a caller-supplied
    /// WorkerRequest is not a substitute for a durable dispatch transition.
    pub(crate) fn from_claimed_worker(
        worker: &'a mut InferenceWorker<D>,
        model_id: String,
        existing_reservation: WorkerRequest,
        neuron_generation: Generation,
        observed_now_ms: u64,
        claim_started: Instant,
    ) -> Self {
        Self {
            worker,
            model_id,
            neuron_generation,
            reservation: Some(existing_reservation),
            observed_now_ms,
            claim_started,
        }
    }

    /// Only module-local fixtures can bypass a durable dispatch claim.
    #[cfg(test)]
    pub(crate) fn from_reserved_worker(
        worker: &'a mut InferenceWorker<D>,
        model_id: String,
        existing_reservation: WorkerRequest,
        neuron_generation: Generation,
        observed_now_ms: u64,
    ) -> Self {
        Self::from_claimed_worker(
            worker,
            model_id,
            existing_reservation,
            neuron_generation,
            observed_now_ms,
            Instant::now(),
        )
    }

    /// True only before the first attempted execution or rejection.
    #[must_use]
    pub fn reservation_unconsumed(&self) -> bool {
        self.reservation.is_some()
    }
}

impl<D: ModelDriver + NeuronFeatureDriver> NeuronInferenceControlPort
    for WorkerNeuronControlPort<'_, D>
{
    fn execute_feature(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureReceiptV1, NeuronModelError> {
        // Take before any check or driver invocation. A stale/invalid request,
        // failed worker or unknown terminal outcome never reuses this identity.
        let authorization = self.reservation.take().ok_or(NeuronModelError::Rejected)?;
        // A fresh port wrapping the same Worker must never replay this request
        // or reservation. Record before ALL preflight checks: rejection,
        // cancellation or indeterminate execution consumes the attempt.
        self.worker
            .consume_neuron_attempt(&authorization)
            .map_err(|_| NeuronModelError::Rejected)?;
        // A Dispatching claim can be fsynced long before a caller actually
        // invokes this port. Reusing the claim-time wall-clock would let an
        // expired request or ResourceGrant execute after its real deadline.
        // Account for elapsed monotonic time including the durable claim;
        // the host remains responsible for authenticating observed_now_ms.
        let elapsed = Instant::now()
            .checked_duration_since(self.claim_started)
            .ok_or(NeuronModelError::Rejected)?;
        let elapsed_ms =
            u64::try_from(elapsed.as_millis()).map_err(|_| NeuronModelError::Rejected)?;
        let execution_now_ms = self
            .observed_now_ms
            .checked_add(elapsed_ms)
            .ok_or(NeuronModelError::Rejected)?;
        if self.model_id != request.model_id.as_str()
            || self.neuron_generation != request.generation
            || authorization.request_id != request.request_id.as_str()
            || authorization.reservation_id.is_empty()
            || authorization.cancelled
            || execution_now_ms >= authorization.deadline_ms
            || authorization.maximum_tokens == 0
            || authorization.maximum_tokens > authorization.reservation_maximum_tokens
            || authorization.reservation_model_digest != authorization.model_digest
            || authorization.lease_payload_digest != authorization.payload_digest
        {
            return Err(NeuronModelError::Rejected);
        }
        let feature = NeuronFeatureRequest {
            authorization,
            encoder_digest: request.encoder_digest.to_string(),
            head_digest: request.head_digest.to_string(),
            weights_digest: request.weights_digest.to_string(),
            input_digest: request.input_digest.to_string(),
            feature_vector_q24: request.feature_vector_q24.clone(),
            expected_output_width: request.expected_output_width,
        };
        let actual_payload = canonical_neuron_feature_payload_digest(&feature);
        if feature.authorization.payload_digest != actual_payload
            || feature.authorization.lease_payload_digest != actual_payload
        {
            return Err(NeuronModelError::Rejected);
        }

        // The adapter has now crossed into the Worker. Once we may have
        // invoked a backend, no error (including invalid output, memory
        // overrun or terminal receipt corruption) proves that no work ran.
        // Preserve unknown outcome instead of authorizing an unsafe retry.
        let receipt = self
            .worker
            .run_neuron_features_receipt_consumed(
                execution_now_ms,
                &self.model_id,
                feature,
                self.neuron_generation,
            )
            .map_err(|_| NeuronModelError::Indeterminate)?;

        verify_neuron_feature_receipt_v1(request, &receipt)
            .map_err(|_| NeuronModelError::Indeterminate)?;
        Ok(receipt)
    }
}

#[cfg(test)]
#[path = "neuron_worker_control_tests.rs"]
mod tests;
