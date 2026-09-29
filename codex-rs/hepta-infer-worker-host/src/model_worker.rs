//! Experimental synchronous local-driver compatibility layer. It is not a
//! production caller, a verified grant boundary, or proof of physical isolation.
#![forbid(unsafe_code)]

use std::collections::BTreeMap;

#[path = "model_worker_types.rs"]
mod types;
pub use types::DriverModelHandle;
pub use types::DriverRunObservation;
pub use types::Error;
pub use types::ExecutionStatus;
pub use types::InferenceExecutionObservation;
use types::MAX_ACTIVE_REQUESTS;
use types::MAX_MODELS;
pub use types::ModelLoadObservation;
pub use types::ModelManifest;
pub use types::ModelUnloadObservation;
pub use types::ResourceGrant;
pub use types::WorkerRequest;
use types::validate_digest;
use types::validate_grant;
use types::validate_identity;
use types::validate_manifest;
use types::validate_request;

#[path = "model_resources.rs"]
mod resources;
use resources::ResourceLease;
use resources::ResourceManager;
pub use resources::ResourceSnapshot;

#[path = "model_neuron.rs"]
mod neuron;
pub use neuron::DriverNeuronFeatureObservation;
pub use neuron::NeuronFeatureDriver;
pub use neuron::NeuronFeatureExecutionObservation;
pub use neuron::NeuronFeatureRequest;
pub use neuron::canonical_neuron_feature_payload_digest;

#[path = "semantic_worker.rs"]
mod semantic;
pub use semantic::DriverSemanticRetrievalReplyV2;
pub use semantic::SemanticRetrievalCallV2;
pub use semantic::SemanticRetrievalDriver;

/// Experimental driver contract. Implementations must enforce the admitted
/// resident/KV/transient bounds before allocation. Returned measurements alone
/// are not device attestation. Unload borrows a handle so failure cannot erase it.
pub trait ModelDriver {
    fn load(&mut self, manifest: &ModelManifest) -> Result<DriverModelHandle, Error>;
    fn run(
        &mut self,
        handle: &DriverModelHandle,
        request: &WorkerRequest,
    ) -> Result<DriverRunObservation, Error>;
    fn unload(&mut self, handle: &DriverModelHandle) -> Result<(), Error>;
}

#[derive(Debug)]
struct LoadedModel {
    manifest: ModelManifest,
    handle: DriverModelHandle,
    resources: ResourceLease,
    active_requests: usize,
    repair_required: bool,
}

#[derive(Debug)]
pub struct InferenceWorker<D: ModelDriver> {
    worker_id: String,
    generation: u64,
    grant: ResourceGrant,
    driver: D,
    resources: ResourceManager,
    models: BTreeMap<String, LoadedModel>,
    active_requests: BTreeMap<String, String>,
}

impl<D: ModelDriver> InferenceWorker<D> {
    pub fn new(
        now_ms: u64,
        worker_id: String,
        generation: u64,
        grant: ResourceGrant,
        driver: D,
    ) -> Result<Self, Error> {
        validate_identity(&worker_id, "worker")?;
        validate_grant(now_ms, &grant)?;
        if generation == 0 || generation != grant.generation {
            return Err(Error::InvalidGrant);
        }
        let resources = ResourceManager::new(generation, grant.maximum_memory_bytes);
        Ok(Self {
            worker_id,
            generation,
            grant,
            driver,
            resources,
            models: BTreeMap::new(),
            active_requests: BTreeMap::new(),
        })
    }

    pub fn worker_id(&self) -> &str {
        &self.worker_id
    }

    pub fn resource_snapshot(&self) -> Result<ResourceSnapshot, Error> {
        self.resources.snapshot()
    }

    /// A device reset may only remove permission. There is deliberately no
    /// in-place unfence operation or automatic capacity refund.
    pub fn fence_generation(&self) -> Result<(), Error> {
        self.resources.fence()
    }

    pub fn load_model(
        &mut self,
        now_ms: u64,
        manifest: ModelManifest,
    ) -> Result<ModelLoadObservation, Error> {
        self.validate_current_grant(now_ms)?;
        validate_manifest(&manifest)?;
        if self.models.contains_key(&manifest.model_id) {
            return Err(Error::ModelAlreadyLoaded);
        }
        if self.models.len() >= self.grant.maximum_models.min(MAX_MODELS) {
            return Err(Error::ModelCapacity);
        }
        let mut resources = self.resources.reserve(manifest.maximum_resident_bytes)?;
        resources.enter()?;
        // An error with no returned handle is not proof that allocation stopped.
        // The entered guard retains the budget and fences this generation.
        let handle = self.driver.load(&manifest)?;
        let valid = validate_identity(&handle.opaque_id, "model handle").and_then(|()| {
            if handle.observed_memory_bytes > manifest.maximum_resident_bytes {
                Err(Error::ModelCapacity)
            } else {
                Ok(())
            }
        });
        if let Err(error) = valid {
            if self.driver.unload(&handle).is_ok() {
                resources.release_after_terminal()?;
                return Err(error);
            }
            self.models.insert(
                manifest.model_id.clone(),
                LoadedModel {
                    manifest,
                    handle,
                    resources,
                    active_requests: 0,
                    repair_required: true,
                },
            );
            self.resources.fence()?;
            return Err(Error::CleanupRequired);
        }
        let observation = ModelLoadObservation {
            model_id: manifest.model_id.clone(),
            worker_generation: self.generation,
            handle_id: handle.opaque_id.clone(),
            observed_memory_bytes: handle.observed_memory_bytes,
            terminal_observed: true,
        };
        self.models.insert(
            manifest.model_id.clone(),
            LoadedModel {
                manifest,
                handle,
                resources,
                active_requests: 0,
                repair_required: false,
            },
        );
        Ok(observation)
    }

    pub fn run(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: WorkerRequest,
    ) -> Result<InferenceExecutionObservation, Error> {
        self.validate_current_grant(now_ms)?;
        validate_identity(model_id, "model")?;
        validate_request(now_ms, &request)?;
        if self.active_requests.contains_key(&request.request_id)
            || self.active_requests.len()
                >= self.grant.maximum_active_requests.min(MAX_ACTIVE_REQUESTS)
        {
            return Err(Error::RequestCapacity);
        }
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.repair_required {
            return Err(Error::CleanupRequired);
        }
        if request.model_digest != loaded.manifest.model_digest
            || request.reservation_model_digest != loaded.manifest.model_digest
        {
            return Err(Error::ModelMismatch);
        }
        if request.maximum_tokens > loaded.manifest.maximum_tokens
            || request.maximum_tokens > request.reservation_maximum_tokens
        {
            return Err(Error::TokenLimit);
        }
        if request.payload_digest != request.lease_payload_digest {
            return Err(Error::PayloadMismatch);
        }
        if request.cancelled {
            return Ok(InferenceExecutionObservation {
                request_id: request.request_id,
                reservation_id: request.reservation_id,
                worker_generation: self.generation,
                model_digest: request.model_digest,
                payload_digest: request.payload_digest,
                status: ExecutionStatus::Cancelled,
                output_digest: None,
                consumed_tokens: Some(0),
                observed_memory_bytes: loaded.handle.observed_memory_bytes,
                terminal_observed: true,
            });
        }
        let workspace_bytes = request
            .maximum_kv_bytes
            .checked_add(request.maximum_transient_bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        let memory_limit = loaded
            .manifest
            .maximum_resident_bytes
            .checked_add(workspace_bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        let mut workspace = self.resources.reserve(workspace_bytes)?;
        let active_count = loaded
            .active_requests
            .checked_add(1)
            .ok_or(Error::ArithmeticOverflow)?;
        workspace.enter()?;
        loaded.active_requests = active_count;
        self.active_requests
            .insert(request.request_id.clone(), model_id.to_string());
        let observed = self.driver.run(&loaded.handle, &request);
        self.active_requests.remove(&request.request_id);
        loaded.active_requests = loaded
            .active_requests
            .checked_sub(1)
            .ok_or(Error::ResourceAccounting)?;
        let observed = match observed {
            Ok(observed) => observed,
            Err(error) => {
                loaded.repair_required = true;
                return Err(error);
            }
        };
        if observed.terminal_observed {
            workspace.release_after_terminal()?;
        } else {
            loaded.repair_required = true;
            drop(workspace);
        }
        if observed.consumed_tokens.is_some_and(|tokens| {
            tokens > request.maximum_tokens || tokens > request.reservation_maximum_tokens
        }) {
            self.resources.fence()?;
            return Err(Error::TokenLimit);
        }
        if observed.observed_memory_bytes > memory_limit {
            self.resources.fence()?;
            return Err(Error::ModelCapacity);
        }
        let (status, output_digest, terminal_observed) = if !observed.terminal_observed {
            (ExecutionStatus::Indeterminate, None, false)
        } else if observed.succeeded {
            let output = observed
                .output_digest
                .as_ref()
                .ok_or(Error::MissingTerminalOutput)?;
            validate_digest(output, "output")?;
            (ExecutionStatus::Succeeded, observed.output_digest, true)
        } else {
            if let Some(output) = &observed.output_digest {
                validate_digest(output, "output")?;
            }
            (ExecutionStatus::Failed, observed.output_digest, true)
        };
        Ok(InferenceExecutionObservation {
            request_id: request.request_id,
            reservation_id: request.reservation_id,
            worker_generation: self.generation,
            model_digest: request.model_digest,
            payload_digest: request.payload_digest,
            status,
            output_digest,
            consumed_tokens: observed.consumed_tokens,
            observed_memory_bytes: observed.observed_memory_bytes,
            terminal_observed,
        })
    }

    /// Cleanup does not extend a grant or start new inference. It remains legal
    /// after expiry/revocation/fencing, and forgets a handle only after success.
    pub fn unload_model(
        &mut self,
        _now_ms: u64,
        model_id: &str,
    ) -> Result<ModelUnloadObservation, Error> {
        validate_identity(model_id, "model")?;
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.active_requests != 0 {
            return Err(Error::ActiveRequests);
        }
        loaded.repair_required = true;
        if let Err(error) = self.driver.unload(&loaded.handle) {
            self.resources.fence()?;
            return Err(error);
        }
        let loaded = self.models.remove(model_id).ok_or(Error::ModelNotLoaded)?;
        loaded.resources.release_after_terminal()?;
        Ok(ModelUnloadObservation {
            model_id: model_id.to_string(),
            worker_generation: self.generation,
            terminal_observed: true,
        })
    }

    fn validate_current_grant(&self, now_ms: u64) -> Result<(), Error> {
        validate_grant(now_ms, &self.grant)?;
        if self.resources.snapshot()?.fenced {
            return Err(Error::GenerationFenced);
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "model_worker_tests.rs"]
mod tests;
