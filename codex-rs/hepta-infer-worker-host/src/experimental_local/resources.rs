use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;

use super::AttestedModelHandle;
use super::LocalWorkerError;
use super::VerifiedResourceGrant;
use super::validate_identity;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModelLifecycle {
    Loading,
    Ready,
    Draining,
    Unloading,
    Zombie,
    RepairRequired,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RequestLifecycle {
    Prepared,
    Running,
    Quarantined,
}

#[derive(Clone, Debug)]
struct ModelRecord {
    bytes: u64,
    active_requests: u32,
    lifecycle: ModelLifecycle,
}

#[derive(Clone, Debug)]
struct RequestRecord {
    handle_id: String,
    bytes: u64,
    lifecycle: RequestLifecycle,
}

#[derive(Debug)]
struct ResourceState {
    generation: u64,
    device_epoch: u64,
    maximum_bytes: u64,
    maximum_concurrency: u32,
    pending_model_bytes: u64,
    committed_model_bytes: u64,
    request_bytes: u64,
    models: BTreeMap<String, ModelRecord>,
    requests: BTreeMap<String, RequestRecord>,
    fenced_reason: Option<String>,
}

impl ResourceState {
    fn total_bytes(&self) -> Result<u64, LocalWorkerError> {
        self.pending_model_bytes
            .checked_add(self.committed_model_bytes)
            .and_then(|value| value.checked_add(self.request_bytes))
            .ok_or(LocalWorkerError::ArithmeticOverflow)
    }

    fn ensure_available(&self, additional: u64) -> Result<(), LocalWorkerError> {
        if let Some(reason) = &self.fenced_reason {
            return Err(LocalWorkerError::GenerationFenced(reason.clone()));
        }
        let next = self
            .total_bytes()?
            .checked_add(additional)
            .ok_or(LocalWorkerError::ArithmeticOverflow)?;
        if next > self.maximum_bytes {
            return Err(LocalWorkerError::CapacityExceeded);
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct ResourceManager {
    inner: Arc<Mutex<ResourceState>>,
}

impl ResourceManager {
    pub fn new(grant: &VerifiedResourceGrant) -> Self {
        Self {
            inner: Arc::new(Mutex::new(ResourceState {
                generation: grant.worker_generation(),
                device_epoch: grant.device_epoch(),
                maximum_bytes: grant.maximum_aggregate_memory_bytes(),
                maximum_concurrency: grant.maximum_concurrency(),
                pending_model_bytes: 0,
                committed_model_bytes: 0,
                request_bytes: 0,
                models: BTreeMap::new(),
                requests: BTreeMap::new(),
                fenced_reason: None,
            })),
        }
    }

    pub fn snapshot(&self) -> Result<ResourceSnapshot, LocalWorkerError> {
        let state = self.lock()?;
        Ok(ResourceSnapshot {
            generation: state.generation,
            device_epoch: state.device_epoch,
            maximum_bytes: state.maximum_bytes,
            pending_model_bytes: state.pending_model_bytes,
            committed_model_bytes: state.committed_model_bytes,
            request_bytes: state.request_bytes,
            loaded_models: state.models.len(),
            active_or_quarantined_requests: state.requests.len(),
            fenced_reason: state.fenced_reason.clone(),
        })
    }

    pub fn fence_generation(&self, reason: impl Into<String>) -> Result<(), LocalWorkerError> {
        let reason = reason.into();
        if reason.is_empty() || reason.len() > 4096 {
            return Err(LocalWorkerError::InvalidIdentity("generation fence reason"));
        }
        let mut state = self.lock()?;
        state.fenced_reason = Some(reason);
        for model in state.models.values_mut() {
            if model.lifecycle != ModelLifecycle::Zombie {
                model.lifecycle = ModelLifecycle::RepairRequired;
            }
        }
        for request in state.requests.values_mut() {
            request.lifecycle = RequestLifecycle::Quarantined;
        }
        Ok(())
    }

    pub fn resolve_quarantine(&self, operation_id: &str) -> Result<(), LocalWorkerError> {
        if self.resolve_quarantine_if_present(operation_id)? {
            Ok(())
        } else {
            Err(LocalWorkerError::InvalidTransition(
                "quarantined request not found",
            ))
        }
    }

    /// Release a same-process quarantined request after exact terminal
    /// reconciliation. A restarted process may have no in-memory request entry;
    /// that case is a no-op because no local bytes or concurrency are retained.
    pub(super) fn resolve_quarantine_if_present(
        &self,
        operation_id: &str,
    ) -> Result<bool, LocalWorkerError> {
        validate_identity(operation_id, "local operation")?;
        let mut state = self.lock()?;
        match state
            .requests
            .get(operation_id)
            .map(|request| request.lifecycle)
        {
            None => Ok(false),
            Some(RequestLifecycle::Quarantined) => {
                release_request_locked(&mut state, operation_id)?;
                Ok(true)
            }
            Some(_) => Err(LocalWorkerError::InvalidTransition(
                "request is not quarantined",
            )),
        }
    }

    pub fn model_lifecycle(
        &self,
        handle_id: &str,
    ) -> Result<Option<ModelLifecycle>, LocalWorkerError> {
        let state = self.lock()?;
        Ok(state.models.get(handle_id).map(|record| record.lifecycle))
    }

    pub(super) fn ensure_current(
        &self,
        generation: u64,
        device_epoch: u64,
    ) -> Result<(), LocalWorkerError> {
        let state = self.lock()?;
        if state.generation != generation || state.device_epoch != device_epoch {
            return Err(LocalWorkerError::GenerationFenced(
                "worker or device generation changed".to_string(),
            ));
        }
        // Fencing blocks new admission in `ensure_available`, but exact
        // recovery and physical cleanup must remain possible for the same
        // generation and device epoch.
        Ok(())
    }

    pub(super) fn reserve_model(
        &self,
        expected_bytes: u64,
    ) -> Result<ModelReservation, LocalWorkerError> {
        if expected_bytes == 0 {
            return Err(LocalWorkerError::CapacityExceeded);
        }
        let mut state = self.lock()?;
        state.ensure_available(expected_bytes)?;
        state.pending_model_bytes = state
            .pending_model_bytes
            .checked_add(expected_bytes)
            .ok_or(LocalWorkerError::ArithmeticOverflow)?;
        Ok(ModelReservation {
            manager: self.clone(),
            expected_bytes,
            committed: false,
        })
    }

    pub(super) fn reserve_request(
        &self,
        operation_id: &str,
        handle: &AttestedModelHandle,
        expected_transient_bytes: u64,
    ) -> Result<RequestReservation, LocalWorkerError> {
        validate_identity(operation_id, "local operation")?;
        let mut state = self.lock()?;
        state.ensure_available(expected_transient_bytes)?;
        if state.requests.contains_key(operation_id)
            || state.requests.len()
                >= usize::try_from(state.maximum_concurrency)
                    .map_err(|_| LocalWorkerError::ArithmeticOverflow)?
        {
            return Err(LocalWorkerError::CapacityExceeded);
        }
        let model =
            state
                .models
                .get_mut(handle.handle_id())
                .ok_or(LocalWorkerError::InvalidTransition(
                    "model is not registered",
                ))?;
        if model.lifecycle != ModelLifecycle::Ready {
            return Err(LocalWorkerError::InvalidTransition("model is not ready"));
        }
        model.active_requests = model
            .active_requests
            .checked_add(1)
            .ok_or(LocalWorkerError::ArithmeticOverflow)?;
        state.request_bytes = state
            .request_bytes
            .checked_add(expected_transient_bytes)
            .ok_or(LocalWorkerError::ArithmeticOverflow)?;
        state.requests.insert(
            operation_id.to_string(),
            RequestRecord {
                handle_id: handle.handle_id().to_string(),
                bytes: expected_transient_bytes,
                lifecycle: RequestLifecycle::Prepared,
            },
        );
        Ok(RequestReservation {
            manager: self.clone(),
            operation_id: operation_id.to_string(),
            retained: false,
        })
    }

    pub(super) fn begin_unload(
        &self,
        handle: &AttestedModelHandle,
    ) -> Result<(), LocalWorkerError> {
        let mut state = self.lock()?;
        let model =
            state
                .models
                .get_mut(handle.handle_id())
                .ok_or(LocalWorkerError::InvalidTransition(
                    "model is not registered",
                ))?;
        if !matches!(
            model.lifecycle,
            ModelLifecycle::Ready | ModelLifecycle::RepairRequired | ModelLifecycle::Zombie
        ) || model.active_requests != 0
        {
            return Err(LocalWorkerError::InvalidTransition(
                "model cannot enter unload",
            ));
        }
        model.lifecycle = ModelLifecycle::Draining;
        model.lifecycle = ModelLifecycle::Unloading;
        Ok(())
    }

    pub(super) fn complete_unload(
        &self,
        handle: &AttestedModelHandle,
    ) -> Result<(), LocalWorkerError> {
        let mut state = self.lock()?;
        let record =
            state
                .models
                .get(handle.handle_id())
                .ok_or(LocalWorkerError::InvalidTransition(
                    "model is not registered",
                ))?;
        if record.lifecycle != ModelLifecycle::Unloading || record.active_requests != 0 {
            return Err(LocalWorkerError::InvalidTransition(
                "model unload is not terminal",
            ));
        }
        let bytes = record.bytes;
        state.models.remove(handle.handle_id());
        state.committed_model_bytes = state
            .committed_model_bytes
            .checked_sub(bytes)
            .ok_or(LocalWorkerError::ArithmeticOverflow)?;
        Ok(())
    }

    pub(super) fn fail_unload(&self, handle: &AttestedModelHandle) -> Result<(), LocalWorkerError> {
        let mut state = self.lock()?;
        let record =
            state
                .models
                .get_mut(handle.handle_id())
                .ok_or(LocalWorkerError::InvalidTransition(
                    "model is not registered",
                ))?;
        record.lifecycle = ModelLifecycle::Zombie;
        Ok(())
    }

    fn lock(&self) -> Result<std::sync::MutexGuard<'_, ResourceState>, LocalWorkerError> {
        self.inner
            .lock()
            .map_err(|_| LocalWorkerError::ResourceStatePoisoned)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceSnapshot {
    pub generation: u64,
    pub device_epoch: u64,
    pub maximum_bytes: u64,
    pub pending_model_bytes: u64,
    pub committed_model_bytes: u64,
    pub request_bytes: u64,
    pub loaded_models: usize,
    pub active_or_quarantined_requests: usize,
    pub fenced_reason: Option<String>,
}

pub(super) struct ModelReservation {
    manager: ResourceManager,
    expected_bytes: u64,
    committed: bool,
}

impl ModelReservation {
    pub(super) fn commit(mut self, handle: &AttestedModelHandle) -> Result<(), LocalWorkerError> {
        let mut state = self.manager.lock()?;
        if state.models.contains_key(handle.handle_id()) {
            return Err(LocalWorkerError::InvalidTransition(
                "model handle already registered",
            ));
        }
        let without_reservation = state
            .total_bytes()?
            .checked_sub(self.expected_bytes)
            .ok_or(LocalWorkerError::ArithmeticOverflow)?;
        let next = without_reservation
            .checked_add(handle.resident_memory_bytes())
            .ok_or(LocalWorkerError::ArithmeticOverflow)?;
        if next > state.maximum_bytes {
            return Err(LocalWorkerError::CapacityExceeded);
        }
        state.pending_model_bytes = state
            .pending_model_bytes
            .checked_sub(self.expected_bytes)
            .ok_or(LocalWorkerError::ArithmeticOverflow)?;
        state.committed_model_bytes = state
            .committed_model_bytes
            .checked_add(handle.resident_memory_bytes())
            .ok_or(LocalWorkerError::ArithmeticOverflow)?;
        state.models.insert(
            handle.handle_id().to_string(),
            ModelRecord {
                bytes: handle.resident_memory_bytes(),
                active_requests: 0,
                lifecycle: ModelLifecycle::Ready,
            },
        );
        self.committed = true;
        Ok(())
    }
}

impl Drop for ModelReservation {
    fn drop(&mut self) {
        if self.committed {
            return;
        }
        if let Ok(mut state) = self.manager.inner.lock() {
            match state.pending_model_bytes.checked_sub(self.expected_bytes) {
                Some(value) => state.pending_model_bytes = value,
                None => {
                    state.fenced_reason =
                        Some("model reservation accounting underflow; repair required".to_string());
                }
            }
        }
    }
}

pub(super) struct RequestReservation {
    manager: ResourceManager,
    operation_id: String,
    retained: bool,
}

impl RequestReservation {
    pub(super) fn mark_running(&self) -> Result<(), LocalWorkerError> {
        let mut state = self.manager.lock()?;
        let request = state
            .requests
            .get_mut(&self.operation_id)
            .ok_or(LocalWorkerError::InvalidTransition("request disappeared"))?;
        if request.lifecycle != RequestLifecycle::Prepared {
            return Err(LocalWorkerError::InvalidTransition(
                "request cannot enter running",
            ));
        }
        request.lifecycle = RequestLifecycle::Running;
        Ok(())
    }

    pub(super) fn complete(mut self) -> Result<(), LocalWorkerError> {
        let mut state = self.manager.lock()?;
        release_request_locked(&mut state, &self.operation_id)?;
        self.retained = true;
        Ok(())
    }

    pub(super) fn quarantine(mut self) -> Result<(), LocalWorkerError> {
        let mut state = self.manager.lock()?;
        let request = state
            .requests
            .get_mut(&self.operation_id)
            .ok_or(LocalWorkerError::InvalidTransition("request disappeared"))?;
        request.lifecycle = RequestLifecycle::Quarantined;
        self.retained = true;
        Ok(())
    }
}

impl Drop for RequestReservation {
    fn drop(&mut self) {
        if self.retained {
            return;
        }
        if let Ok(mut state) = self.manager.inner.lock()
            && release_request_locked(&mut state, &self.operation_id).is_err()
        {
            state.fenced_reason =
                Some("request reservation accounting failure; repair required".to_string());
        }
    }
}

fn release_request_locked(
    state: &mut ResourceState,
    operation_id: &str,
) -> Result<(), LocalWorkerError> {
    let request = state
        .requests
        .remove(operation_id)
        .ok_or(LocalWorkerError::InvalidTransition("request not found"))?;
    state.request_bytes = state
        .request_bytes
        .checked_sub(request.bytes)
        .ok_or(LocalWorkerError::ArithmeticOverflow)?;
    let model =
        state
            .models
            .get_mut(&request.handle_id)
            .ok_or(LocalWorkerError::InvalidTransition(
                "request model disappeared",
            ))?;
    model.active_requests = model
        .active_requests
        .checked_sub(1)
        .ok_or(LocalWorkerError::ArithmeticOverflow)?;
    Ok(())
}
