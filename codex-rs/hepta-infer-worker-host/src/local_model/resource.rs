use std::collections::BTreeMap;
use std::sync::{Arc, Mutex};

use super::{validate_identity, Error, OperationId};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModelResourceState {
    Ready,
    Unloading,
    RepairRequired,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RequestResourceState {
    Reserved,
    Dispatched,
    Quarantined,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceSnapshot {
    pub generation: u64,
    pub fenced: bool,
    pub reserved_model_bytes: u64,
    pub committed_model_bytes: u64,
    pub request_memory_bytes: u64,
    pub loaded_models: usize,
    pub active_requests: usize,
    pub quarantined_requests: usize,
    pub repair_required_models: usize,
}

#[derive(Clone)]
pub struct ResourceManager {
    inner: Arc<Mutex<ResourceState>>,
}

#[derive(Debug)]
struct ResourceState {
    generation: u64,
    fenced: bool,
    maximum_aggregate_memory_bytes: u64,
    maximum_concurrent_requests: usize,
    reserved_model_bytes: u64,
    committed_model_bytes: u64,
    request_memory_bytes: u64,
    pending_models: BTreeMap<String, u64>,
    models: BTreeMap<String, ModelAllocation>,
    requests: BTreeMap<String, RequestAllocation>,
}

#[derive(Clone, Debug)]
struct ModelAllocation {
    handle_id: String,
    bytes: u64,
    state: ModelResourceState,
}

#[derive(Clone, Debug)]
struct RequestAllocation {
    bytes: u64,
    state: RequestResourceState,
}

impl ResourceManager {
    pub fn new(
        generation: u64,
        maximum_aggregate_memory_bytes: u64,
        maximum_concurrent_requests: usize,
    ) -> Result<Self, Error> {
        if generation == 0
            || maximum_aggregate_memory_bytes == 0
            || maximum_concurrent_requests == 0
        {
            return Err(Error::ResourceCapacity);
        }
        Ok(Self {
            inner: Arc::new(Mutex::new(ResourceState {
                generation,
                fenced: false,
                maximum_aggregate_memory_bytes,
                maximum_concurrent_requests,
                reserved_model_bytes: 0,
                committed_model_bytes: 0,
                request_memory_bytes: 0,
                pending_models: BTreeMap::new(),
                models: BTreeMap::new(),
                requests: BTreeMap::new(),
            })),
        })
    }

    pub fn reserve_model(
        &self,
        model_id: &str,
        requested_bytes: u64,
        grant_limit: u64,
    ) -> Result<ModelReservation, Error> {
        validate_identity(model_id, "model")?;
        if requested_bytes == 0 {
            return Err(Error::ResourceCapacity);
        }
        let mut state = self.lock()?;
        require_unfenced(&state)?;
        if state.pending_models.contains_key(model_id)
            || state.models.contains_key(model_id)
        {
            return Err(Error::ModelAlreadyLoaded);
        }
        let ceiling = state.maximum_aggregate_memory_bytes.min(grant_limit);
        let projected = aggregate_memory(&state)?
            .checked_add(requested_bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        if projected > ceiling {
            return Err(Error::ResourceCapacity);
        }
        state.reserved_model_bytes = state
            .reserved_model_bytes
            .checked_add(requested_bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        state
            .pending_models
            .insert(model_id.to_string(), requested_bytes);
        Ok(ModelReservation {
            manager: self.clone(),
            model_id: model_id.to_string(),
            reserved_bytes: requested_bytes,
            committed: false,
        })
    }

    pub fn reserve_request(
        &self,
        operation_id: &OperationId,
        requested_bytes: u64,
        grant_memory_limit: u64,
        grant_concurrency_limit: usize,
    ) -> Result<RequestReservation, Error> {
        if requested_bytes == 0 {
            return Err(Error::ResourceCapacity);
        }
        let mut state = self.lock()?;
        require_unfenced(&state)?;
        if state.requests.contains_key(operation_id.as_str()) {
            return Err(Error::ModelBusy);
        }
        let concurrency = state
            .maximum_concurrent_requests
            .min(grant_concurrency_limit);
        if state.requests.len() >= concurrency {
            return Err(Error::ResourceCapacity);
        }
        let ceiling = state
            .maximum_aggregate_memory_bytes
            .min(grant_memory_limit);
        let projected = aggregate_memory(&state)?
            .checked_add(requested_bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        if projected > ceiling {
            return Err(Error::ResourceCapacity);
        }
        state.request_memory_bytes = state
            .request_memory_bytes
            .checked_add(requested_bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        state.requests.insert(
            operation_id.as_str().to_string(),
            RequestAllocation {
                bytes: requested_bytes,
                state: RequestResourceState::Reserved,
            },
        );
        Ok(RequestReservation {
            manager: self.clone(),
            operation_id: operation_id.as_str().to_string(),
            detached: false,
        })
    }

    pub fn ensure_quarantined(
        &self,
        operation_id: &OperationId,
        requested_bytes: u64,
        grant_memory_limit: u64,
        grant_concurrency_limit: usize,
    ) -> Result<(), Error> {
        {
            let state = self.lock()?;
            if let Some(existing) = state.requests.get(operation_id.as_str()) {
                return if existing.state == RequestResourceState::Quarantined
                    && existing.bytes == requested_bytes
                {
                    Ok(())
                } else {
                    Err(Error::ModelBusy)
                };
            }
        }
        let mut reservation = self.reserve_request(
            operation_id,
            requested_bytes,
            grant_memory_limit,
            grant_concurrency_limit,
        )?;
        reservation.mark_dispatched()?;
        reservation.quarantine()?;
        Ok(())
    }

    pub fn begin_unload(&self, model_id: &str) -> Result<(), Error> {
        let mut state = self.lock()?;
        let model = state
            .models
            .get_mut(model_id)
            .ok_or(Error::ModelNotLoaded)?;
        match model.state {
            ModelResourceState::Ready => {
                model.state = ModelResourceState::Unloading;
            }
            ModelResourceState::RepairRequired => {
                return Err(Error::RepairRequired);
            }
            ModelResourceState::Unloading => {
                return Err(Error::ModelBusy);
            }
        }
        Ok(())
    }

    pub fn complete_unload(
        &self,
        model_id: &str,
        handle_id: &str,
    ) -> Result<(), Error> {
        let mut state = self.lock()?;
        let model = state
            .models
            .get(model_id)
            .ok_or(Error::ModelNotLoaded)?;
        if model.handle_id != handle_id
            || model.state != ModelResourceState::Unloading
        {
            return Err(Error::RepairRequired);
        }
        let bytes = model.bytes;
        state.models.remove(model_id);
        state.committed_model_bytes = state
            .committed_model_bytes
            .checked_sub(bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        Ok(())
    }

    pub fn mark_repair_required(&self, model_id: &str) -> Result<(), Error> {
        let mut state = self.lock()?;
        let model = state
            .models
            .get_mut(model_id)
            .ok_or(Error::ModelNotLoaded)?;
        model.state = ModelResourceState::RepairRequired;
        Ok(())
    }

    pub fn fence_generation(&self) -> Result<(), Error> {
        let mut state = self.lock()?;
        state.fenced = true;
        for model in state.models.values_mut() {
            model.state = ModelResourceState::RepairRequired;
        }
        for request in state.requests.values_mut() {
            request.state = RequestResourceState::Quarantined;
        }
        Ok(())
    }

    pub fn snapshot(&self) -> Result<ResourceSnapshot, Error> {
        let state = self.lock()?;
        Ok(ResourceSnapshot {
            generation: state.generation,
            fenced: state.fenced,
            reserved_model_bytes: state.reserved_model_bytes,
            committed_model_bytes: state.committed_model_bytes,
            request_memory_bytes: state.request_memory_bytes,
            loaded_models: state.models.len(),
            active_requests: state.requests.len(),
            quarantined_requests: state
                .requests
                .values()
                .filter(|request| {
                    request.state == RequestResourceState::Quarantined
                })
                .count(),
            repair_required_models: state
                .models
                .values()
                .filter(|model| {
                    model.state == ModelResourceState::RepairRequired
                })
                .count(),
        })
    }

    fn lock(&self) -> Result<std::sync::MutexGuard<'_, ResourceState>, Error> {
        self.inner.lock().map_err(|_| Error::LockPoisoned)
    }
}

pub struct ModelReservation {
    manager: ResourceManager,
    model_id: String,
    reserved_bytes: u64,
    committed: bool,
}

impl ModelReservation {
    pub(crate) fn commit(
        mut self,
        handle_id: String,
        observed_bytes: u64,
    ) -> Result<(), Error> {
        validate_identity(&handle_id, "model handle")?;
        if observed_bytes == 0 || observed_bytes > self.reserved_bytes {
            return Err(Error::ResourceCapacity);
        }
        {
            let mut state = self.manager.lock()?;
            let reserved = state
                .pending_models
                .get(&self.model_id)
                .copied()
                .ok_or(Error::ResourceCapacity)?;
            if reserved != self.reserved_bytes {
                return Err(Error::ResourceCapacity);
            }
            state.pending_models.remove(&self.model_id);
            state.reserved_model_bytes = state
                .reserved_model_bytes
                .checked_sub(self.reserved_bytes)
                .ok_or(Error::ArithmeticOverflow)?;
            state.committed_model_bytes = state
                .committed_model_bytes
                .checked_add(observed_bytes)
                .ok_or(Error::ArithmeticOverflow)?;
            state.models.insert(
                self.model_id.clone(),
                ModelAllocation {
                    handle_id,
                    bytes: observed_bytes,
                    state: ModelResourceState::Ready,
                },
            );
        }
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
            if state.pending_models.remove(&self.model_id).is_some() {
                if let Some(next) =
                    state.reserved_model_bytes.checked_sub(self.reserved_bytes)
                {
                    state.reserved_model_bytes = next;
                } else {
                    state.fenced = true;
                }
            }
        }
    }
}

pub struct RequestReservation {
    manager: ResourceManager,
    operation_id: String,
    detached: bool,
}

impl RequestReservation {
    pub fn mark_dispatched(&mut self) -> Result<(), Error> {
        let mut state = self.manager.lock()?;
        let request = state
            .requests
            .get_mut(&self.operation_id)
            .ok_or(Error::ResourceCapacity)?;
        if request.state != RequestResourceState::Reserved {
            return Err(Error::RepairRequired);
        }
        request.state = RequestResourceState::Dispatched;
        Ok(())
    }

    pub fn quarantine(&mut self) -> Result<(), Error> {
        let mut state = self.manager.lock()?;
        let request = state
            .requests
            .get_mut(&self.operation_id)
            .ok_or(Error::ResourceCapacity)?;
        request.state = RequestResourceState::Quarantined;
        self.detached = true;
        Ok(())
    }

    pub fn finish(mut self) -> Result<(), Error> {
        let mut state = self.manager.lock()?;
        let request = state
            .requests
            .remove(&self.operation_id)
            .ok_or(Error::ResourceCapacity)?;
        state.request_memory_bytes = state
            .request_memory_bytes
            .checked_sub(request.bytes)
            .ok_or(Error::ArithmeticOverflow)?;
        self.detached = true;
        Ok(())
    }

    pub(crate) fn from_quarantine(
        manager: ResourceManager,
        operation_id: &OperationId,
    ) -> Self {
        Self {
            manager,
            operation_id: operation_id.as_str().to_string(),
            detached: false,
        }
    }
}

impl Drop for RequestReservation {
    fn drop(&mut self) {
        if self.detached {
            return;
        }
        if let Ok(mut state) = self.manager.inner.lock() {
            let releasable = state
                .requests
                .get(&self.operation_id)
                .is_some_and(|request| {
                    request.state == RequestResourceState::Reserved
                });
            if releasable {
                if let Some(request) = state.requests.remove(&self.operation_id)
                {
                    if let Some(next) =
                        state.request_memory_bytes.checked_sub(request.bytes)
                    {
                        state.request_memory_bytes = next;
                    } else {
                        state.fenced = true;
                    }
                }
            }
        }
    }
}

fn require_unfenced(state: &ResourceState) -> Result<(), Error> {
    if state.fenced {
        return Err(Error::GenerationFenced);
    }
    Ok(())
}

fn aggregate_memory(state: &ResourceState) -> Result<u64, Error> {
    state
        .reserved_model_bytes
        .checked_add(state.committed_model_bytes)
        .and_then(|value| value.checked_add(state.request_memory_bytes))
        .ok_or(Error::ArithmeticOverflow)
}
