//! Semantic retrieval uses the existing worker, model catalog and active slots.
//! It does not create a second inference owner or persist its own outcomes.

use codex_hepta_infer_core::SemanticRetrievalReplyV1;
use codex_hepta_infer_core::SemanticRetrievalRequestV1;
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
    /// Invoke a typed read-only retrieval through this worker's existing model
    /// handle and shared capacity. For this profile maximum_tokens bounds total
    /// observed input plus output tokens. A reply is an observation, not final
    /// source authorization, an adopted artifact, a selected action or success
    /// of the external task. The caller revalidates currentness at consumption.
    pub fn run_semantic_retrieval(
        &mut self,
        now_ms: u64,
        model_id: &str,
        call: SemanticRetrievalCallV1,
    ) -> Result<SemanticRetrievalExecutionV1, Error> {
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
        if self.active_requests.contains_key(&call.authorization.request_id)
            || self.active_requests.len() >= self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS)
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
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
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
            // Check existing active identity first: cancellation cannot turn
            // an already unknown dispatch into a new pre-entry rejection.
            return Err(Error::RequestCancelled);
        }
        loaded.active_requests = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        self.active_requests.insert(
            call.authorization.request_id.clone(),
            model_id.to_string(),
        );
        // Every fallible action after insertion retains the slot unless a
        // complete, bound and well-formed terminal observation is obtained.
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
}
