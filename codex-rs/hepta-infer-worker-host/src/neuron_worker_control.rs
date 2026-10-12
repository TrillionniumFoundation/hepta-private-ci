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
use codex_hepta_infer_core::NeuronFeatureTerminalStatusV1;
use codex_hepta_infer_core::verify_neuron_feature_receipt_v1;
use codex_hepta_neuron::NeuronInferenceControlPort;
use codex_hepta_neuron::NeuronModelError;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;

use crate::model_worker::InferenceWorker;
use crate::model_worker::ModelDriver;
use crate::model_worker::NeuronFeatureDriver;
use crate::model_worker::NeuronFeatureRequest;
use crate::model_worker::WorkerRequest;
use crate::model_worker::canonical_neuron_feature_payload_digest;

const USAGE_DOMAIN: &[u8] = b"hepta.infer-worker.neuron-metered-result.diagnostic.v1\0";

/// Owner-local backend resource fact emitted only after a fully verified typed
/// receipt. Tokens are taken from the actual physical ModelDriver return, not
/// from a caller's reserved quota. This is NOT a signed terminal observation,
/// production cost settlement or permission to dispatch.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronWorkerMeteredResultV1 {
    pub request_id: String,
    pub reservation_id: String,
    pub worker_id: String,
    pub worker_generation: u64,
    pub neuron_generation: Generation,
    pub receipt_digest: Digest32,
    pub status: NeuronFeatureTerminalStatusV1,
    pub consumed_tokens: u32,
    pub diagnostic_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl NeuronWorkerMeteredResultV1 {
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut b = USAGE_DOMAIN.to_vec();
        for id in [&self.request_id, &self.reservation_id, &self.worker_id] {
            b.extend_from_slice(&(id.len() as u64).to_be_bytes());
            b.extend_from_slice(id.as_bytes());
        }
        b.extend_from_slice(&self.worker_generation.to_be_bytes());
        b.extend_from_slice(&self.neuron_generation.get().to_be_bytes());
        b.extend_from_slice(self.receipt_digest.as_array());
        b.push(match self.status {
            NeuronFeatureTerminalStatusV1::Succeeded => 1,
            NeuronFeatureTerminalStatusV1::Failed => 2,
            NeuronFeatureTerminalStatusV1::Cancelled => 3,
            NeuronFeatureTerminalStatusV1::Indeterminate => 4,
        });
        b.extend_from_slice(&self.consumed_tokens.to_be_bytes());
        Digest32::of_bytes(&b)
    }

    /// Detects mutation of the diagnostic, not fake evidence from a dishonest
    /// issuer. The durable Control Owner and independent usage authority still
    /// need to authenticate and settle the physical execution separately.
    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && !self.request_id.is_empty()
            && !self.reservation_id.is_empty()
            && !self.worker_id.is_empty()
            && self.worker_generation != 0
            && !self.receipt_digest.is_zero()
            && self.diagnostic_digest == self.computed_digest()
    }
}

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
    metered: Option<NeuronWorkerMeteredResultV1>,
}

impl<'a, D: ModelDriver + NeuronFeatureDriver> WorkerNeuronControlPort<'a, D> {
    /// Internal handoff after the trusted same-crate inference.control owner
    /// has fsynced a one-time Dispatching claim. Unit tests exercise older
    /// lower-level rejection paths without manufacturing production authority.
    ///
    /// Do NOT expose this constructor outside the crate: a caller-supplied
    /// WorkerRequest is not a substitute for a durable dispatch transition.
    pub(crate) fn from_reserved_worker(
        worker: &'a mut InferenceWorker<D>,
        model_id: String,
        existing_reservation: WorkerRequest,
        neuron_generation: Generation,
        observed_now_ms: u64,
    ) -> Self {
        Self {
            worker,
            model_id,
            neuron_generation,
            reservation: Some(existing_reservation),
            observed_now_ms,
            metered: None,
        }
    }

    /// True only before the first attempted execution or rejection.
    #[must_use]
    pub fn reservation_unconsumed(&self) -> bool {
        self.reservation.is_some()
    }

    /// The exact Worker-observed token count is available only after the
    /// typed receipt has been verified. Never substitute reserved token limit.
    #[must_use]
    pub fn metered_result_v1(&self) -> Option<&NeuronWorkerMeteredResultV1> {
        self.metered.as_ref()
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
        // A rejected second call must not accidentally expose the successful
        // prior attempt as if it were the result of this new invocation.
        self.metered = None;
        let authorization = self.reservation.take().ok_or(NeuronModelError::Rejected)?;
        let reservation_id = authorization.reservation_id.clone();
        // A fresh port wrapping the same Worker must never replay this request
        // or reservation. Record before ALL preflight checks: rejection,
        // cancellation or indeterminate execution consumes the attempt.
        self.worker
            .consume_neuron_attempt(&authorization)
            .map_err(|_| NeuronModelError::Rejected)?;
        if self.model_id != request.model_id.as_str()
            || self.neuron_generation != request.generation
            || authorization.request_id != request.request_id.as_str()
            || authorization.reservation_id.is_empty()
            || authorization.cancelled
            || self.observed_now_ms >= authorization.deadline_ms
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
        let (receipt, consumed_tokens) = self
            .worker
            .run_neuron_features_receipt_consumed(
                self.observed_now_ms,
                &self.model_id,
                feature,
                self.neuron_generation,
            )
            .map_err(|_| NeuronModelError::Indeterminate)?;

        verify_neuron_feature_receipt_v1(request, &receipt)
            .map_err(|_| NeuronModelError::Indeterminate)?;
        let mut metered = NeuronWorkerMeteredResultV1 {
            request_id: request.request_id.to_string(),
            reservation_id,
            worker_id: self.worker.worker_id().to_owned(),
            worker_generation: self.worker.worker_generation(),
            neuron_generation: request.generation,
            receipt_digest: receipt.receipt_digest,
            status: receipt.status,
            consumed_tokens,
            diagnostic_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        metered.diagnostic_digest = metered.computed_digest();
        self.metered = Some(metered);
        Ok(receipt)
    }
}

#[cfg(test)]
#[path = "neuron_worker_control_tests.rs"]
mod tests;
