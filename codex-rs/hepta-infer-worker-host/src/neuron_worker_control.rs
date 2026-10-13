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
use codex_hepta_infer_core::neuron_feature_request_digest_v1;
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

const COST_DOMAIN: &[u8] = b"hepta.inference.worker.neuron-token-cost.v1\0";

/// Bounded, single-consume diagnostic of one *actually observed* typed Worker
/// execution. This is a self-consistency digest, not an independently
/// authenticated usage meter, production route, or NDU utility claim.
/// This is deliberately separate from the frozen NeuronFeatureReceiptV1.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct WorkerNeuronTokenCostV1 {
    request_id: String,
    reservation_id: String,
    model_id: String,
    worker_id: String,
    worker_generation: u64,
    request_digest: Digest32,
    feature_receipt_digest: Digest32,
    terminal_status: NeuronFeatureTerminalStatusV1,
    consumed_tokens: u32,
    diagnostic_digest: Digest32,
    authority: AuthorityPosture,
}

impl WorkerNeuronTokenCostV1 {
    #[must_use]
    pub const fn consumed_tokens(&self) -> u32 {
        self.consumed_tokens
    }

    #[must_use]
    pub const fn terminal_status(&self) -> NeuronFeatureTerminalStatusV1 {
        self.terminal_status
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.feature_receipt_digest
    }

    /// Recompute from the worker-owned request/reservation and verified typed
    /// response, rather than allowing the caller to submit a usage number.
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = COST_DOMAIN.to_vec();
        for id in [
            &self.request_id,
            &self.reservation_id,
            &self.model_id,
            &self.worker_id,
        ] {
            let value = id.as_bytes();
            bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
            bytes.extend_from_slice(value);
        }
        bytes.extend_from_slice(&self.worker_generation.to_be_bytes());
        bytes.extend_from_slice(self.request_digest.as_array());
        bytes.extend_from_slice(self.feature_receipt_digest.as_array());
        bytes.push(match self.terminal_status {
            NeuronFeatureTerminalStatusV1::Succeeded => 0,
            NeuronFeatureTerminalStatusV1::Failed => 1,
            NeuronFeatureTerminalStatusV1::Cancelled => 2,
            NeuronFeatureTerminalStatusV1::Indeterminate => 3,
        });
        bytes.extend_from_slice(&self.consumed_tokens.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && !self.request_id.is_empty()
            && !self.reservation_id.is_empty()
            && !self.model_id.is_empty()
            && !self.worker_id.is_empty()
            && self.worker_generation > 0
            && !self.request_digest.is_zero()
            && !self.feature_receipt_digest.is_zero()
            && !self.diagnostic_digest.is_zero()
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
    /// One final observable usage receipt for this exact single-use ModelPort.
    /// No receipt survives a repeated/rejected attempt.
    last_cost: Option<WorkerNeuronTokenCostV1>,
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
            last_cost: None,
        }
    }

    /// Read the last terminal usage from THIS port, without inferring model
    /// success or any independent physical/resource attestation.
    #[must_use]
    pub fn cost_diagnostic(&self) -> Option<&WorkerNeuronTokenCostV1> {
        self.last_cost.as_ref()
    }

    /// Single-use extraction for a separately trusted metering/evaluation
    /// owner. A second read cannot create duplicate utility credit.
    pub fn take_cost_diagnostic(&mut self) -> Option<WorkerNeuronTokenCostV1> {
        self.last_cost.take()
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
        self.last_cost = None;
        let authorization = self.reservation.take().ok_or(NeuronModelError::Rejected)?;
        let receipt_reservation_id = authorization.reservation_id.clone();
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
            .run_neuron_features_receipt_with_cost_consumed(
                self.observed_now_ms,
                &self.model_id,
                feature,
                self.neuron_generation,
            )
            .map_err(|_| NeuronModelError::Indeterminate)?;

        verify_neuron_feature_receipt_v1(request, &receipt)
            .map_err(|_| NeuronModelError::Indeterminate)?;

        let mut usage = WorkerNeuronTokenCostV1 {
            request_id: request.request_id.to_string(),
            reservation_id: receipt_reservation_id,
            model_id: self.model_id.clone(),
            worker_id: self.worker.worker_id().to_owned(),
            worker_generation: self.worker.worker_generation(),
            request_digest: neuron_feature_request_digest_v1(request)
                .map_err(|_| NeuronModelError::Indeterminate)?,
            feature_receipt_digest: receipt.receipt_digest,
            terminal_status: receipt.status,
            consumed_tokens,
            diagnostic_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        usage.diagnostic_digest = usage.computed_digest();
        if !usage.validate_integrity() {
            return Err(NeuronModelError::Indeterminate);
        }
        self.last_cost = Some(usage);
        Ok(receipt)
    }
}

#[cfg(test)]
#[path = "neuron_worker_control_tests.rs"]
mod tests;
