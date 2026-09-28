use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::AttestedModelHandle;
use super::LocalRuntimeError;
use super::TrustedMemoryObservation;
use super::UnloadObservation;
use super::VerifiedInput;
use super::VerifiedModelManifest;
use super::VerifiedResourceGrant;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceLimits {
    pub maximum_models: usize,
    pub maximum_in_flight: usize,
    pub maximum_aggregate_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceSnapshot {
    pub worker_generation: Generation,
    pub device_id: StableId,
    pub model_count: usize,
    pub in_flight_count: usize,
    pub accounted_memory_bytes: u64,
    pub zombie_count: usize,
    pub fenced_reason: Option<String>,
}

#[derive(Clone, Debug)]
pub struct ResourceManager {
    inner: Arc<Mutex<ResourceState>>,
}

#[derive(Debug)]
struct ResourceState {
    worker_generation: Generation,
    device_id: StableId,
    limits: ResourceLimits,
    models: BTreeMap<String, ModelState>,
    requests: BTreeMap<String, RequestUse>,
    fenced_reason: Option<String>,
}

#[derive(Debug)]
enum ModelState {
    Loading {
        reserved_bytes: u64,
        model_digest: Digest32,
    },
    Loaded {
        accounted_bytes: u64,
        model_digest: Digest32,
        attestation_digest: Digest32,
    },
    Unloading {
        accounted_bytes: u64,
        model_digest: Digest32,
        attestation_digest: Digest32,
    },
    Zombie {
        accounted_bytes: u64,
        model_digest: Digest32,
        reason: String,
    },
}

#[derive(Debug)]
struct RequestUse {
    model_id: String,
    accounted_bytes: u64,
}

impl ResourceManager {
    pub fn new(
        worker_generation: Generation,
        device_id: StableId,
        limits: ResourceLimits,
    ) -> Result<Self, LocalRuntimeError> {
        if worker_generation.get() == 0
            || limits.maximum_models == 0
            || limits.maximum_in_flight == 0
            || limits.maximum_aggregate_memory_bytes == 0
        {
            return Err(LocalRuntimeError::Capacity);
        }
        Ok(Self {
            inner: Arc::new(Mutex::new(ResourceState {
                worker_generation,
                device_id,
                limits,
                models: BTreeMap::new(),
                requests: BTreeMap::new(),
                fenced_reason: None,
            })),
        })
    }

    pub fn reserve_model(
        &self,
        grant: &VerifiedResourceGrant,
        manifest: &VerifiedModelManifest,
    ) -> Result<ModelReservation, LocalRuntimeError> {
        let mut state = self.inner.lock().map_err(|_| LocalRuntimeError::LockPoisoned)?;
        validate_owner(&state, grant)?;
        require_unfenced(&state)?;
        let model_id = manifest.claims().model_id.as_str().to_string();
        if state.models.contains_key(&model_id) {
            return Err(LocalRuntimeError::Conflict);
        }
        if state.models.len() >= state.limits.maximum_models {
            return Err(LocalRuntimeError::Capacity);
        }
        let reserved_bytes = manifest.claims().expected_weight_bytes;
        let maximum = state
            .limits
            .maximum_aggregate_memory_bytes
            .min(grant.claims().maximum_aggregate_memory_bytes);
        let projected = accounted_memory(&state)?
            .checked_add(reserved_bytes)
            .ok_or(LocalRuntimeError::ArithmeticOverflow)?;
        if reserved_bytes == 0 || projected > maximum {
            return Err(LocalRuntimeError::Capacity);
        }
        state.models.insert(
            model_id.clone(),
            ModelState::Loading {
                reserved_bytes,
                model_digest: manifest.claims().model_digest,
            },
        );
        Ok(ModelReservation {
            manager: self.clone(),
            model_id,
            resolved: false,
        })
    }

    pub fn reserve_request(
        &self,
        grant: &VerifiedResourceGrant,
        input: &VerifiedInput,
        model_id: &StableId,
    ) -> Result<RequestReservation, LocalRuntimeError> {
        let mut state = self.inner.lock().map_err(|_| LocalRuntimeError::LockPoisoned)?;
        validate_owner(&state, grant)?;
        require_unfenced(&state)?;
        let operation_id = input.operation_id().as_str().to_string();
        if state.requests.contains_key(&operation_id) {
            return Err(LocalRuntimeError::Conflict);
        }
        let model_key = model_id.as_str();
        if !matches!(state.models.get(model_key), Some(ModelState::Loaded { .. })) {
            return Err(LocalRuntimeError::Conflict);
        }
        let request_limit = state
            .limits
            .maximum_in_flight
            .min(grant.claims().maximum_concurrency);
        if state.requests.len() >= request_limit {
            return Err(LocalRuntimeError::Capacity);
        }
        let request_bytes = input
            .kv_memory_bytes()
            .checked_add(input.transient_memory_bytes())
            .ok_or(LocalRuntimeError::ArithmeticOverflow)?;
        let maximum = state
            .limits
            .maximum_aggregate_memory_bytes
            .min(grant.claims().maximum_aggregate_memory_bytes);
        let projected = accounted_memory(&state)?
            .checked_add(request_bytes)
            .ok_or(LocalRuntimeError::ArithmeticOverflow)?;
        if projected > maximum {
            return Err(LocalRuntimeError::Capacity);
        }
        state.requests.insert(
            operation_id.clone(),
            RequestUse {
                model_id: model_key.to_string(),
                accounted_bytes: request_bytes,
            },
        );
        Ok(RequestReservation {
            manager: self.clone(),
            operation_id,
            released: false,
        })
    }

    pub fn begin_unload(
        &self,
        model_id: &StableId,
    ) -> Result<UnloadPermit, LocalRuntimeError> {
        let mut state = self.inner.lock().map_err(|_| LocalRuntimeError::LockPoisoned)?;
        require_unfenced(&state)?;
        let key = model_id.as_str().to_string();
        if state.requests.values().any(|request| request.model_id == key) {
            return Err(LocalRuntimeError::ActiveRequests);
        }
        let current = state.models.remove(&key).ok_or(LocalRuntimeError::Conflict)?;
        let (accounted_bytes, model_digest, attestation_digest) = match current {
            ModelState::Loaded {
                accounted_bytes,
                model_digest,
                attestation_digest,
            } => (accounted_bytes, model_digest, attestation_digest),
            other => {
                state.models.insert(key, other);
                return Err(LocalRuntimeError::Conflict);
            }
        };
        state.models.insert(
            key.clone(),
            ModelState::Unloading {
                accounted_bytes,
                model_digest,
                attestation_digest,
            },
        );
        Ok(UnloadPermit {
            manager: self.clone(),
            model_id: key,
            accounted_bytes,
            resolved: false,
        })
    }

    pub fn reconcile_observed_memory(
        &self,
        observation: TrustedMemoryObservation,
    ) -> Result<ResourceSnapshot, LocalRuntimeError> {
        let mut state = self.inner.lock().map_err(|_| LocalRuntimeError::LockPoisoned)?;
        if observation.device_id != state.device_id
            || observation.worker_generation != state.worker_generation
            || observation.witness_digest.is_zero()
        {
            return Err(LocalRuntimeError::Device(
                "memory observation identity mismatch".to_string(),
            ));
        }
        if observation.observed_total_bytes > state.limits.maximum_aggregate_memory_bytes {
            state.fenced_reason = Some("trusted device memory limit exceeded".to_string());
            return Err(LocalRuntimeError::Fenced(
                "trusted device memory limit exceeded".to_string(),
            ));
        }
        snapshot(&state)
    }

    pub fn fence_generation(&self, reason: impl Into<String>) -> Result<(), LocalRuntimeError> {
        let reason = reason.into();
        if reason.is_empty() {
            return Err(LocalRuntimeError::Fenced("empty fence reason".to_string()));
        }
        let mut state = self.inner.lock().map_err(|_| LocalRuntimeError::LockPoisoned)?;
        state.fenced_reason = Some(reason);
        Ok(())
    }

    pub fn snapshot(&self) -> Result<ResourceSnapshot, LocalRuntimeError> {
        let state = self.inner.lock().map_err(|_| LocalRuntimeError::LockPoisoned)?;
        snapshot(&state)
    }
}

pub struct ModelReservation {
    manager: ResourceManager,
    model_id: String,
    resolved: bool,
}

impl ModelReservation {
    pub fn commit(
        mut self,
        handle: &AttestedModelHandle,
    ) -> Result<(), LocalRuntimeError> {
        let mut state = self
            .manager
            .inner
            .lock()
            .map_err(|_| LocalRuntimeError::LockPoisoned)?;
        let current = state
            .models
            .remove(&self.model_id)
            .ok_or(LocalRuntimeError::Conflict)?;
        let (reserved_bytes, model_digest) = match current {
            ModelState::Loading {
                reserved_bytes,
                model_digest,
            } => (reserved_bytes, model_digest),
            other => {
                state.models.insert(self.model_id.clone(), other);
                return Err(LocalRuntimeError::Conflict);
            }
        };
        if handle.model_id().as_str() != self.model_id
            || handle.model_digest() != model_digest
            || handle.device_id() != &state.device_id
            || handle.worker_generation() != state.worker_generation
            || handle.observed_memory_bytes() > reserved_bytes
        {
            state.models.insert(
                self.model_id.clone(),
                ModelState::Zombie {
                    accounted_bytes: reserved_bytes,
                    model_digest,
                    reason: "attested handle exceeded or drifted from reservation".to_string(),
                },
            );
            self.resolved = true;
            return Err(LocalRuntimeError::Device(
                "attested handle exceeded or drifted from reservation".to_string(),
            ));
        }
        state.models.insert(
            self.model_id.clone(),
            ModelState::Loaded {
                accounted_bytes: reserved_bytes,
                model_digest,
                attestation_digest: handle.attestation_digest(),
            },
        );
        self.resolved = true;
        Ok(())
    }

    pub fn mark_zombie(
        mut self,
        reason: impl Into<String>,
    ) -> Result<(), LocalRuntimeError> {
        let reason = reason.into();
        let mut state = self
            .manager
            .inner
            .lock()
            .map_err(|_| LocalRuntimeError::LockPoisoned)?;
        let current = state
            .models
            .remove(&self.model_id)
            .ok_or(LocalRuntimeError::Conflict)?;
        let (accounted_bytes, model_digest) = match current {
            ModelState::Loading {
                reserved_bytes,
                model_digest,
            } => (reserved_bytes, model_digest),
            other => {
                state.models.insert(self.model_id.clone(), other);
                return Err(LocalRuntimeError::Conflict);
            }
        };
        state.models.insert(
            self.model_id.clone(),
            ModelState::Zombie {
                accounted_bytes,
                model_digest,
                reason,
            },
        );
        self.resolved = true;
        Ok(())
    }
}

impl Drop for ModelReservation {
    fn drop(&mut self) {
        if self.resolved {
            return;
        }
        if let Ok(mut state) = self.manager.inner.lock() {
            if matches!(state.models.get(&self.model_id), Some(ModelState::Loading { .. })) {
                state.models.remove(&self.model_id);
            }
        }
    }
}

pub struct RequestReservation {
    manager: ResourceManager,
    operation_id: String,
    released: bool,
}

impl RequestReservation {
    pub fn release(mut self) -> Result<(), LocalRuntimeError> {
        let mut state = self
            .manager
            .inner
            .lock()
            .map_err(|_| LocalRuntimeError::LockPoisoned)?;
        state.requests.remove(&self.operation_id);
        self.released = true;
        Ok(())
    }
}

impl Drop for RequestReservation {
    fn drop(&mut self) {
        if self.released {
            return;
        }
        if let Ok(mut state) = self.manager.inner.lock() {
            state.requests.remove(&self.operation_id);
        }
    }
}

pub struct UnloadPermit {
    manager: ResourceManager,
    model_id: String,
    accounted_bytes: u64,
    resolved: bool,
}

impl UnloadPermit {
    pub fn complete(
        mut self,
        observation: &UnloadObservation,
    ) -> Result<(), LocalRuntimeError> {
        let mut state = self
            .manager
            .inner
            .lock()
            .map_err(|_| LocalRuntimeError::LockPoisoned)?;
        if !observation.terminal_observed
            || observation.released_memory_bytes != self.accounted_bytes
            || observation.observation_digest.is_zero()
        {
            mark_unload_zombie(&mut state, &self.model_id, "unload was not exactly observed")?;
            self.resolved = true;
            return Err(LocalRuntimeError::Device(
                "unload was not exactly observed".to_string(),
            ));
        }
        match state.models.remove(&self.model_id) {
            Some(ModelState::Unloading { .. }) => {
                self.resolved = true;
                Ok(())
            }
            Some(other) => {
                state.models.insert(self.model_id.clone(), other);
                Err(LocalRuntimeError::Conflict)
            }
            None => Err(LocalRuntimeError::Conflict),
        }
    }

    pub fn mark_zombie(
        mut self,
        reason: impl Into<String>,
    ) -> Result<(), LocalRuntimeError> {
        let mut state = self
            .manager
            .inner
            .lock()
            .map_err(|_| LocalRuntimeError::LockPoisoned)?;
        mark_unload_zombie(&mut state, &self.model_id, &reason.into())?;
        self.resolved = true;
        Ok(())
    }
}

impl Drop for UnloadPermit {
    fn drop(&mut self) {
        if self.resolved {
            return;
        }
        if let Ok(mut state) = self.manager.inner.lock() {
            let _ = mark_unload_zombie(
                &mut state,
                &self.model_id,
                "unload permit dropped without terminal observation",
            );
        }
    }
}

fn validate_owner(
    state: &ResourceState,
    grant: &VerifiedResourceGrant,
) -> Result<(), LocalRuntimeError> {
    if state.worker_generation != grant.claims().worker_generation
        || state.device_id != grant.claims().device_id
    {
        return Err(LocalRuntimeError::InvalidGrant("resource owner mismatch"));
    }
    Ok(())
}

fn require_unfenced(state: &ResourceState) -> Result<(), LocalRuntimeError> {
    if let Some(reason) = &state.fenced_reason {
        return Err(LocalRuntimeError::Fenced(reason.clone()));
    }
    Ok(())
}

fn accounted_memory(state: &ResourceState) -> Result<u64, LocalRuntimeError> {
    let mut total = 0_u64;
    for model in state.models.values() {
        let bytes = match model {
            ModelState::Loading { reserved_bytes, .. } => *reserved_bytes,
            ModelState::Loaded { accounted_bytes, .. }
            | ModelState::Unloading { accounted_bytes, .. }
            | ModelState::Zombie { accounted_bytes, .. } => *accounted_bytes,
        };
        total = total
            .checked_add(bytes)
            .ok_or(LocalRuntimeError::ArithmeticOverflow)?;
    }
    for request in state.requests.values() {
        total = total
            .checked_add(request.accounted_bytes)
            .ok_or(LocalRuntimeError::ArithmeticOverflow)?;
    }
    Ok(total)
}

fn snapshot(state: &ResourceState) -> Result<ResourceSnapshot, LocalRuntimeError> {
    Ok(ResourceSnapshot {
        worker_generation: state.worker_generation,
        device_id: state.device_id.clone(),
        model_count: state.models.len(),
        in_flight_count: state.requests.len(),
        accounted_memory_bytes: accounted_memory(state)?,
        zombie_count: state
            .models
            .values()
            .filter(|model| matches!(model, ModelState::Zombie { .. }))
            .count(),
        fenced_reason: state.fenced_reason.clone(),
    })
}

fn mark_unload_zombie(
    state: &mut ResourceState,
    model_id: &str,
    reason: &str,
) -> Result<(), LocalRuntimeError> {
    let current = state.models.remove(model_id).ok_or(LocalRuntimeError::Conflict)?;
    match current {
        ModelState::Unloading {
            accounted_bytes,
            model_digest,
            ..
        } => {
            state.models.insert(
                model_id.to_string(),
                ModelState::Zombie {
                    accounted_bytes,
                    model_digest,
                    reason: reason.to_string(),
                },
            );
            Ok(())
        }
        other => {
            state.models.insert(model_id.to_string(), other);
            Err(LocalRuntimeError::Conflict)
        }
    }
}
