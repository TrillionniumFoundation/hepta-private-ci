pub struct LoadReservation {
    manager: ResourceManager,
    model_id: String,
    reserved_bytes: u64,
    dispatched: bool,
    finished: bool,
}

impl LoadReservation {
    fn mark_dispatched(&mut self) {
        self.dispatched = true;
    }

    fn release_rejected(mut self) {
        // The trusted driver reported the existing terminal rejection contract.
        self.dispatched = false;
    }

    pub fn commit(mut self, observed_bytes: u64) -> Result<(), LocalModelError> {
        let mut state = self.manager.lock()?;
        if observed_bytes == 0 || observed_bytes > self.reserved_bytes {
            if let Some((_, status)) = state.models.get_mut(&self.model_id) {
                *status = ModelResourceState::RepairRequired;
            }
            state.fenced = true;
            self.finished = true;
            return Err(LocalModelError::DriverAttestation);
        }
        let release = self
            .reserved_bytes
            .checked_sub(observed_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        state.aggregate_memory = state
            .aggregate_memory
            .checked_sub(release)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        let (retained_bytes, status) = state
            .models
            .get_mut(&self.model_id)
            .ok_or(LocalModelError::ModelNotLoaded)?;
        *retained_bytes = observed_bytes;
        *status = ModelResourceState::Ready;
        self.finished = true;
        Ok(())
    }

    pub fn quarantine(mut self) -> Result<(), LocalModelError> {
        let mut state = self.manager.lock()?;
        let (_, status) = state
            .models
            .get_mut(&self.model_id)
            .ok_or(LocalModelError::ModelNotLoaded)?;
        *status = ModelResourceState::Zombie;
        state.fenced = true;
        self.finished = true;
        Ok(())
    }
}

impl Drop for LoadReservation {
    fn drop(&mut self) {
        if self.finished {
            return;
        }
        if let Ok(mut state) = self.manager.inner.lock() {
            if self.dispatched {
                if let Some((_, status)) = state.models.get_mut(&self.model_id) {
                    *status = ModelResourceState::RepairRequired;
                }
                state.fenced = true;
                return;
            }
            state.models.remove(&self.model_id);
            match state.aggregate_memory.checked_sub(self.reserved_bytes) {
                Some(next) => state.aggregate_memory = next,
                None => state.fenced = true,
            }
        }
    }
}

pub struct RunReservation {
    manager: ResourceManager,
    transient_bytes: u64,
    dispatched: bool,
    finished: bool,
}

impl RunReservation {
    fn mark_dispatched(&mut self) {
        self.dispatched = true;
    }

    fn complete(mut self) -> Result<(), LocalModelError> {
        let mut state = self.manager.lock()?;
        let active = state
            .active_requests
            .checked_sub(1)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        let memory = state
            .aggregate_memory
            .checked_sub(self.transient_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        state.active_requests = active;
        state.aggregate_memory = memory;
        self.finished = true;
        Ok(())
    }
}

impl Drop for RunReservation {
    fn drop(&mut self) {
        if self.finished {
            return;
        }
        if let Ok(mut state) = self.manager.inner.lock() {
            if self.dispatched {
                state.fenced = true;
                state.usage_unknown = true;
                return;
            }
            match (
                state.active_requests.checked_sub(1),
                state.aggregate_memory.checked_sub(self.transient_bytes),
            ) {
                (Some(active), Some(memory)) => {
                    state.active_requests = active;
                    state.aggregate_memory = memory;
                }
                _ => state.fenced = true,
            }
        }
    }
}

pub struct UnloadReservation {
    manager: ResourceManager,
    model_id: String,
    finished: bool,
}

impl UnloadReservation {
    fn abort_before_dispatch(mut self) -> Result<(), LocalModelError> {
        let mut state = self.manager.lock()?;
        let (_, status) = state
            .models
            .get_mut(&self.model_id)
            .ok_or(LocalModelError::ModelNotLoaded)?;
        if *status != ModelResourceState::Unloading {
            return Err(LocalModelError::InvalidTransition);
        }
        *status = ModelResourceState::Ready;
        self.finished = true;
        Ok(())
    }

    pub fn complete(mut self, released_bytes: u64) -> Result<(), LocalModelError> {
        let mut state = self.manager.lock()?;
        let (retained_bytes, status) = state
            .models
            .get(&self.model_id)
            .copied()
            .ok_or(LocalModelError::ModelNotLoaded)?;
        if status != ModelResourceState::Unloading || released_bytes != retained_bytes {
            state.fenced = true;
            self.finished = true;
            return Err(LocalModelError::DriverAttestation);
        }
        state.models.remove(&self.model_id);
        state.aggregate_memory = state
            .aggregate_memory
            .checked_sub(released_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        self.finished = true;
        Ok(())
    }

    pub fn quarantine(mut self) -> Result<(), LocalModelError> {
        let mut state = self.manager.lock()?;
        let (_, status) = state
            .models
            .get_mut(&self.model_id)
            .ok_or(LocalModelError::ModelNotLoaded)?;
        *status = ModelResourceState::Zombie;
        state.fenced = true;
        self.finished = true;
        Ok(())
    }
}

impl Drop for UnloadReservation {
    fn drop(&mut self) {
        if self.finished {
            return;
        }
        if let Ok(mut state) = self.manager.inner.lock() {
            if let Some((_, status)) = state.models.get_mut(&self.model_id) {
                *status = ModelResourceState::RepairRequired;
            }
            state.fenced = true;
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum LocalExecutionStatus {
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalExecutionObservation {
    pub operation_id: String,
    pub status: LocalExecutionStatus,
    pub output_digest: Option<String>,
    pub observed_usage_tokens: Option<u64>,
    pub terminal_observed: bool,
}

struct LoadedModel {
    handle: AttestedModelHandle,
}
