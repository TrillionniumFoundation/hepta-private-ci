//! Semantic retrieval uses the existing worker, model catalog and active slots.
//! Durable calls use the existing inference owner; no separate result store.

use codex_hepta_infer_core::SemanticRetrievalReplyV1;
use codex_hepta_infer_core::SemanticRetrievalRequestV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::semantic::SemanticAdmissionV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticCompletionV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticPhaseV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticRecordV1;
use codex_hepta_types::Digest32;

use super::DriverModelHandle;
use super::Error;
use super::InferenceWorker;
use super::MAX_ACTIVE_REQUESTS;
use super::ModelDriver;
use super::ModelLifecycle;
use super::WorkerRequest;
use super::validate_identity;
use super::validate_request;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticRetrievalCallV1 {
    pub authorization: WorkerRequest,
    pub input: SemanticRetrievalRequestV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverSemanticRetrievalReplyV1 {
    /// A complete HPTARS V1 reply, not an acknowledgement or partial stdout.
    pub reply_wire: Vec<u8>,
    pub observed_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticRetrievalExecutionV1 {
    pub request_id: String,
    pub reservation_id: String,
    pub worker_generation: u64,
    pub reply: SemanticRetrievalReplyV1,
    pub observed_memory_bytes: u64,
}

/// A host-selected model leaf under the existing worker lifecycle. Implementors
/// must bound transport reads, close stdin, enforce the request deadline and
/// return only after observing child/model completion. Errors do not prove a
/// non-execution; no alternate backend or automatic retry is allowed. A driver
/// must measure resources rather than treating a missing measurement as zero.
/// The host, not this trait or the Python leaf, owns source-currentness checks.
pub trait SemanticRetrievalDriver: ModelDriver {
    fn run_semantic_retrieval(
        &mut self,
        handle: &DriverModelHandle,
        request_wire: &[u8],
    ) -> Result<DriverSemanticRetrievalReplyV1, Error>;
}

impl<D: SemanticRetrievalDriver> InferenceWorker<D> {
    fn validate_semantic_entry(
        &self,
        now_ms: u64,
        model_id: &str,
        call: &SemanticRetrievalCallV1,
    ) -> Result<Vec<u8>, Error> {
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        validate_request(now_ms, &call.authorization)?;
        call.input
            .validate_at(now_ms)
            .map_err(|_| Error::FeatureContract)?;
        if call.input.operation_id != call.authorization.request_id
            || call.input.generation != self.generation
            || call.input.deadline_ms != call.authorization.deadline_ms
        {
            return Err(Error::PayloadMismatch);
        }
        if self
            .active_requests
            .contains_key(&call.authorization.request_id)
            || self.active_requests.len()
                >= self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS)
        {
            return Err(Error::RequestCapacity);
        }
        let wire = call.input.encode().map_err(|_| Error::FeatureContract)?;
        let payload = Digest32::of_bytes(&wire).to_string();
        if payload != call.authorization.payload_digest
            || payload != call.authorization.lease_payload_digest
        {
            return Err(Error::PayloadMismatch);
        }
        let loaded = self.models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.lifecycle != ModelLifecycle::Ready {
            return Err(Error::ModelQuarantined);
        }
        if call.input.bundle_digest != loaded.manifest.model_digest
            || call.authorization.model_digest != loaded.manifest.model_digest
            || call.authorization.reservation_model_digest != loaded.manifest.model_digest
        {
            return Err(Error::ModelMismatch);
        }
        if call.authorization.maximum_tokens > loaded.manifest.maximum_tokens
            || call.authorization.maximum_tokens > call.authorization.reservation_maximum_tokens
        {
            return Err(Error::TokenLimit);
        }
        if call.authorization.cancelled {
            return Err(Error::RequestCancelled);
        }
        Ok(wire)
    }

    /// Low-level compatibility seam: this call does not supply durable replay.
    /// Product composition should use run_semantic_retrieval_durable and still
    /// revalidate source/artifact/authority currentness at actual consumption.
    pub fn run_semantic_retrieval(
        &mut self,
        now_ms: u64,
        model_id: &str,
        call: SemanticRetrievalCallV1,
    ) -> Result<SemanticRetrievalExecutionV1, Error> {
        let wire = self.validate_semantic_entry(now_ms, model_id, &call)?;
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        loaded.active_requests = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        self.active_requests
            .insert(call.authorization.request_id.clone(), model_id.to_string());
        let observed = self.driver.run_semantic_retrieval(&loaded.handle, &wire)?;
        let reply = call
            .input
            .decode_reply(&observed.reply_wire)
            .map_err(|_| Error::FeatureContract)?;
        let consumed = reply
            .input_tokens
            .checked_add(reply.output_tokens)
            .ok_or(Error::ArithmeticOverflow)?;
        if consumed > u64::from(call.authorization.maximum_tokens) {
            return Err(Error::TokenLimit);
        }
        if observed.observed_memory_bytes == 0
            || observed.observed_memory_bytes > self.grant.maximum_memory_bytes
        {
            return Err(Error::ModelCapacity);
        }
        self.active_requests.remove(&call.authorization.request_id);
        loaded.active_requests = loaded.active_requests.saturating_sub(1);
        Ok(SemanticRetrievalExecutionV1 {
            request_id: call.authorization.request_id,
            reservation_id: call.authorization.reservation_id,
            worker_generation: self.generation,
            reply,
            observed_memory_bytes: observed.observed_memory_bytes,
        })
    }

    /// Dispatch under a durable write-ahead fence in the existing control
    /// owner. A recovered unknown record returns reconcile-only without even
    /// loading/requiring a model. A completed record returns its original bytes.
    /// Neither is permission to consume an expired/revoked source or artifact.
    ///
    /// This is a trusted composition port, not an authority issuer. The host
    /// supplies the verified principal and rechecks currentness at final use.
    /// It must not infer external-task success from a completed prediction.
    pub fn run_semantic_retrieval_durable(
        &mut self,
        control: &mut DurableInferenceControl,
        now_ms: u64,
        principal_id: &str,
        model_id: &str,
        call: SemanticRetrievalCallV1,
    ) -> Result<SemanticRecordV1, Error> {
        validate_identity(principal_id, "principal")?;
        let wire = call.input.encode().map_err(|_| Error::FeatureContract)?;
        let digest = Digest32::of_bytes(&wire).to_string();
        if call.authorization.request_id != call.input.operation_id
            || call.authorization.payload_digest != digest
            || call.authorization.lease_payload_digest != digest
            || call.authorization.model_digest != call.input.bundle_digest
            || call.authorization.reservation_model_digest != call.input.bundle_digest
            || call.authorization.maximum_tokens > call.authorization.reservation_maximum_tokens
            || call.authorization.deadline_ms != call.input.deadline_ms
        {
            return Err(Error::PayloadMismatch);
        }
        let id = call.authorization.request_id.clone();
        let admission = SemanticAdmissionV1 {
            request_wire: wire.clone(),
            principal_id: principal_id.to_string(),
            reservation_id: call.authorization.reservation_id.clone(),
            worker_id: self.worker_id.clone(),
            worker_generation: self.generation,
            maximum_tokens: call.authorization.maximum_tokens,
            maximum_memory_bytes: self.grant.maximum_memory_bytes,
            authority_binding_digest: self.grant.semantic_digest.clone(),
        };
        let exists = control.semantic_record(&id).map_err(owner_error)?.is_some();
        if !exists {
            // A new cancellation still records a deterministic pre-dispatch
            // negative, but cannot bypass the normal profile/grant checks.
            let mut preflight = call.clone();
            preflight.authorization.cancelled = false;
            self.validate_semantic_entry(now_ms, model_id, &preflight)?;
        }
        let record = control
            .reserve_semantic(
                now_ms,
                admission,
                self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS),
            )
            .map_err(owner_error)?;
        if call.authorization.cancelled {
            return control.cancel_semantic(&id).map_err(owner_error);
        }
        if record.phase != SemanticPhaseV1::Reserved {
            return Ok(record);
        }
        self.validate_semantic_entry(now_ms, model_id, &call)?;
        control
            .fence_semantic_dispatch(&id, record.revision, now_ms)
            .map_err(owner_error)?;
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        loaded.active_requests = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        self.active_requests
            .insert(id.clone(), model_id.to_string());
        let observed = self.driver.run_semantic_retrieval(&loaded.handle, &wire)?;
        let completion = SemanticCompletionV1 {
            reply_wire: observed.reply_wire,
            observed_memory_bytes: (observed.observed_memory_bytes > 0)
                .then_some(observed.observed_memory_bytes),
        };
        // Persistence and binding checks happen before releasing the live slot
        // or publishing output. A write failure leaves both owners unknown.
        let completed = control
            .complete_semantic(&id, completion)
            .map_err(owner_error)?;
        self.active_requests.remove(&id);
        loaded.active_requests = loaded.active_requests.saturating_sub(1);
        Ok(completed)
    }
}

fn owner_error(error: codex_hepta_infer_core::durable_control::Error) -> Error {
    // The journal record, not this transport error, determines execution state.
    Error::DriverFailure(format!("durable semantic owner: {error}"))
}
