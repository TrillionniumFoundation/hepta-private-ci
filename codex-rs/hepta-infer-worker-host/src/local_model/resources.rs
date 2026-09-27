#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ModelResourceState {
    Loading,
    Ready,
    Unloading,
    Zombie,
    RepairRequired,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ModelResourceSnapshot {
    pub model_id: String,
    pub memory_bytes: u64,
    pub state: ModelResourceState,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ResourceSnapshot {
    pub generation: u64,
    pub aggregate_memory_bytes: u64,
    pub active_requests: usize,
    pub observed_usage_tokens: u64,
    pub usage_unknown: bool,
    pub fenced: bool,
    pub models: Vec<ModelResourceSnapshot>,
}

#[derive(Clone)]
pub struct ResourceManager {
    inner: Arc<Mutex<ResourceState>>,
}

struct ResourceState {
    generation: u64,
    maximum_memory: u64,
    maximum_models: usize,
    maximum_concurrency: usize,
    maximum_total_usage: u64,
    aggregate_memory: u64,
    active_requests: usize,
    observed_usage: u64,
    usage_unknown: bool,
    fenced: bool,
    models: BTreeMap<String, (u64, ModelResourceState)>,
}

impl ResourceManager {
    pub fn from_grant(grant: &VerifiedResourceGrant) -> Result<Self, LocalModelError> {
        let claims = grant.claims();
        if claims.maximum_aggregate_memory_bytes == 0
            || claims.maximum_models == 0
            || claims.maximum_concurrency == 0
        {
            return Err(LocalModelError::ResourceCapacity);
        }
        Ok(Self {
            inner: Arc::new(Mutex::new(ResourceState {
                generation: claims.worker_generation,
                maximum_memory: claims.maximum_aggregate_memory_bytes,
                maximum_models: claims.maximum_models,
                maximum_concurrency: claims.maximum_concurrency,
                maximum_total_usage: claims.maximum_total_usage_tokens,
                aggregate_memory: 0,
                active_requests: 0,
                observed_usage: 0,
                usage_unknown: false,
                fenced: false,
                models: BTreeMap::new(),
            })),
        })
    }

    fn lock(&self) -> Result<MutexGuard<'_, ResourceState>, LocalModelError> {
        self.inner
            .lock()
            .map_err(|_| LocalModelError::StatePoisoned)
    }

    pub fn reserve_load(
        &self,
        model_id: &str,
        bytes: u64,
    ) -> Result<LoadReservation, LocalModelError> {
        let mut state = self.lock()?;
        if state.fenced
            || bytes == 0
            || state.models.len() >= state.maximum_models
            || state.models.contains_key(model_id)
            || state
                .aggregate_memory
                .checked_add(bytes)
                .is_none_or(|next| next > state.maximum_memory)
        {
            return Err(LocalModelError::ResourceCapacity);
        }
        state.aggregate_memory = state
            .aggregate_memory
            .checked_add(bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        state
            .models
            .insert(model_id.to_string(), (bytes, ModelResourceState::Loading));
        Ok(LoadReservation {
            manager: self.clone(),
            model_id: model_id.to_string(),
            reserved_bytes: bytes,
            finished: false,
        })
    }

    pub fn reserve_run(&self, transient_bytes: u64) -> Result<RunReservation, LocalModelError> {
        let mut state = self.lock()?;
        if state.fenced
            || state.active_requests >= state.maximum_concurrency
            || state
                .aggregate_memory
                .checked_add(transient_bytes)
                .is_none_or(|next| next > state.maximum_memory)
        {
            return Err(LocalModelError::ResourceCapacity);
        }
        state.active_requests = state
            .active_requests
            .checked_add(1)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        state.aggregate_memory = state
            .aggregate_memory
            .checked_add(transient_bytes)
            .ok_or(LocalModelError::ArithmeticOverflow)?;
        Ok(RunReservation {
            manager: self.clone(),
            transient_bytes,
        })
    }

    pub fn begin_unload(&self, model_id: &str) -> Result<UnloadReservation, LocalModelError> {
        let mut state = self.lock()?;
        if state.fenced || state.active_requests != 0 {
            return Err(LocalModelError::ResourceCapacity);
        }
        let (_, model_state) = state
            .models
            .get_mut(model_id)
            .ok_or(LocalModelError::ModelNotLoaded)?;
        if *model_state != ModelResourceState::Ready {
            return Err(LocalModelError::InvalidTransition);
        }
        *model_state = ModelResourceState::Unloading;
        Ok(UnloadReservation {
            manager: self.clone(),
            model_id: model_id.to_string(),
            finished: false,
        })
    }

    pub fn observe_usage(&self, usage: Option<u64>) -> Result<(), LocalModelError> {
        let mut state = self.lock()?;
        match usage {
            Some(tokens) => {
                state.observed_usage = state
                    .observed_usage
                    .checked_add(tokens)
                    .ok_or(LocalModelError::ArithmeticOverflow)?;
                if state.observed_usage > state.maximum_total_usage {
                    state.fenced = true;
                    return Err(LocalModelError::ResourceCapacity);
                }
            }
            None => state.usage_unknown = true,
        }
        Ok(())
    }

    pub fn fence_generation(&self) -> Result<(), LocalModelError> {
        self.lock()?.fenced = true;
        Ok(())
    }

    pub fn snapshot(&self) -> Result<ResourceSnapshot, LocalModelError> {
        let state = self.lock()?;
        Ok(ResourceSnapshot {
            generation: state.generation,
            aggregate_memory_bytes: state.aggregate_memory,
            active_requests: state.active_requests,
            observed_usage_tokens: state.observed_usage,
            usage_unknown: state.usage_unknown,
            fenced: state.fenced,
            models: state
                .models
                .iter()
                .map(|(model_id, (memory_bytes, status))| ModelResourceSnapshot {
                    model_id: model_id.clone(),
                    memory_bytes: *memory_bytes,
                    state: *status,
                })
                .collect(),
        })
    }
}
