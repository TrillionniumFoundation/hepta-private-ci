//! Resource-accounted semantic prediction under the existing inference owner.
//! This experimental port is not an independently verified authority boundary.

use codex_hepta_infer_core::SemanticRetrievalRequestV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::semantic::SemanticAdmissionV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticCompletionV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticPhaseV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticRecordV1;
use codex_hepta_infer_core::durable_control::semantic::SemanticResourceLimitsV2;
use codex_hepta_types::Digest32;

use super::DriverModelHandle;
use super::Error;
use super::InferenceWorker;
use super::MAX_ACTIVE_REQUESTS;
use super::ModelDriver;
use super::WorkerRequest;
use super::validate_identity;
use super::validate_request;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SemanticRetrievalCallV2 {
    pub authorization: WorkerRequest,
    pub input: SemanticRetrievalRequestV1,
    /// Bound even for historical lookup when no model is resident.
    pub maximum_resident_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverSemanticRetrievalReplyV2 {
    pub reply_wire: Vec<u8>,
    /// Returning bytes does not establish that a process/model has stopped.
    pub terminal_observed: bool,
    /// None is an unknown measurement, not a zero-cost execution.
    pub observed_memory_bytes: Option<u64>,
}

/// A selected model leaf under the existing worker's lifecycle and resources.
/// Implementations enforce the supplied bounds before allocation, conserve the
/// request's absolute deadline, and return full binary data, never executable
/// code. They must not auto-retry, pick another model, or invent terminal/resource
/// observations. The existing host owns current source/artifact/authority checks.
/// An error after the durable fence remains unknown until trusted reconciliation.
pub trait SemanticRetrievalDriver: ModelDriver {
    fn run_semantic_retrieval(
        &mut self,
        handle: &DriverModelHandle,
        request_wire: &[u8],
        limits: &SemanticResourceLimitsV2,
    ) -> Result<DriverSemanticRetrievalReplyV2, Error>;
}

impl<D: SemanticRetrievalDriver> InferenceWorker<D> {
    /// Execute once behind the existing owner's durable fence and full-result
    /// journal. The result is an observation, never permission for downstream
    /// consumption. Historical results may be read after expiry without a model;
    /// current authority and source revocations must still be checked at use.
    pub fn run_semantic_retrieval_durable(
        &mut self,
        control: &mut DurableInferenceControl,
        now_ms: u64,
        principal_id: &str,
        model_id: &str,
        call: SemanticRetrievalCallV2,
    ) -> Result<SemanticRecordV1, Error> {
        validate_identity(principal_id, "principal")?;
        validate_identity(model_id, "model")?;
        // Structural validation only: history is not a new time-bound use.
        validate_request(0, &call.authorization)?;
        let wire = call.input.encode().map_err(|_| Error::FeatureContract)?;
        let payload = Digest32::of_bytes(&wire).to_string();
        if call.authorization.request_id != call.input.operation_id
            || call.authorization.payload_digest != payload
            || call.authorization.lease_payload_digest != payload
            || call.authorization.model_digest != call.input.bundle_digest
            || call.authorization.reservation_model_digest != call.input.bundle_digest
            || call.authorization.maximum_tokens > call.authorization.reservation_maximum_tokens
            || call.authorization.deadline_ms != call.input.deadline_ms
        {
            return Err(Error::PayloadMismatch);
        }
        let limits = SemanticResourceLimitsV2 {
            model_id: model_id.to_string(),
            resident_bytes: call.maximum_resident_bytes,
            kv_bytes: call.authorization.maximum_kv_bytes,
            transient_bytes: call.authorization.maximum_transient_bytes,
        };
        let memory_limit = limits.total_bytes().map_err(owner_error)?;
        let id = call.authorization.request_id.clone();
        if let Some(previous) = control.semantic_record(&id).map_err(owner_error)? {
            if previous.admission.request_wire != wire
                || previous.admission.principal_id != principal_id
                || previous.admission.reservation_id != call.authorization.reservation_id
                || previous.admission.maximum_tokens != call.authorization.maximum_tokens
                || previous.resource_limits.as_ref() != Some(&limits)
            {
                return Err(Error::PayloadMismatch);
            }
            if previous.phase != SemanticPhaseV1::Reserved {
                return if call.authorization.cancelled {
                    control.cancel_semantic(&id).map_err(owner_error)
                } else {
                    Ok(previous.clone())
                };
            }
            // A Reserved predecessor is not a transferable dispatch lease.
            if previous.admission.worker_id != self.worker_id
                || previous.admission.worker_generation != self.generation
                || previous.admission.authority_binding_digest != self.grant.semantic_digest
            {
                return Err(Error::PayloadMismatch);
            }
            if call.authorization.cancelled {
                return control.cancel_semantic(&id).map_err(owner_error);
            }
        }
        self.validate_current_grant(now_ms)?;
        validate_request(now_ms, &call.authorization)?;
        call.input
            .validate_at(now_ms)
            .map_err(|_| Error::FeatureContract)?;
        if call.input.generation != self.generation {
            return Err(Error::PayloadMismatch);
        }
        if self.active_requests.contains_key(&id)
            || self.active_requests.len()
                >= self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS)
        {
            return Err(Error::RequestCapacity);
        }
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.repair_required {
            return Err(Error::CleanupRequired);
        }
        if loaded.manifest.model_digest != call.input.bundle_digest
            || loaded.manifest.maximum_resident_bytes != limits.resident_bytes
        {
            return Err(Error::ModelMismatch);
        }
        if call.authorization.maximum_tokens > loaded.manifest.maximum_tokens {
            return Err(Error::TokenLimit);
        }
        if memory_limit > self.grant.maximum_memory_bytes {
            return Err(Error::ModelCapacity);
        }
        let workspace_bytes = limits
            .kv_bytes
            .checked_add(limits.transient_bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        // Resident memory was reserved at model load. Reserve the additional
        // workspace before durable admission or physical execution.
        let mut workspace = self.resources.reserve(workspace_bytes)?;
        let active_count = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        let record = control
            .reserve_semantic_with_resources(
                now_ms,
                SemanticAdmissionV1 {
                    request_wire: wire.clone(),
                    principal_id: principal_id.to_string(),
                    reservation_id: call.authorization.reservation_id.clone(),
                    worker_id: self.worker_id.clone(),
                    worker_generation: self.generation,
                    maximum_tokens: call.authorization.maximum_tokens,
                    maximum_memory_bytes: memory_limit,
                    authority_binding_digest: self.grant.semantic_digest.clone(),
                },
                self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS),
                limits.clone(),
            )
            .map_err(owner_error)?;
        if call.authorization.cancelled {
            return control.cancel_semantic(&id).map_err(owner_error);
        }
        control
            .fence_semantic_dispatch(&id, record.revision, now_ms)
            .map_err(owner_error)?;
        workspace.enter()?;
        loaded.active_requests = active_count;
        self.active_requests
            .insert(id.clone(), model_id.to_string());
        let observed = self
            .driver
            .run_semantic_retrieval(&loaded.handle, &wire, &limits);
        self.active_requests.remove(&id);
        loaded.active_requests = loaded
            .active_requests
            .checked_sub(1)
            .ok_or(Error::ResourceAccounting)?;
        let observed = match observed {
            Ok(observed) if observed.terminal_observed => observed,
            Ok(_) => {
                loaded.repair_required = true;
                return Err(Error::MissingTerminalOutput);
            }
            Err(error) => {
                loaded.repair_required = true;
                return Err(error);
            }
        };
        // Complete does binding/shape/resource validation and fsync. A failure
        // leaves the durable fence and quarantines the entered workspace guard.
        let completed = match control.complete_semantic(
            &id,
            SemanticCompletionV1 {
                reply_wire: observed.reply_wire,
                observed_memory_bytes: observed.observed_memory_bytes,
            },
        ) {
            Ok(completed) => completed,
            Err(error) => {
                loaded.repair_required = true;
                return Err(owner_error(error));
            }
        };
        workspace.release_after_terminal()?;
        if !completed.within_resource_budget {
            self.resources.fence()?;
        }
        Ok(completed)
    }
}

fn owner_error(error: codex_hepta_infer_core::durable_control::Error) -> Error {
    Error::DriverFailure(format!("durable semantic owner: {error}"))
}

#[cfg(test)]
#[path = "semantic_worker_tests.rs"]
mod tests;
