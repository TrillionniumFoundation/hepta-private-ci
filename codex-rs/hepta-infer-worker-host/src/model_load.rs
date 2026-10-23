//! One bounded resource owner per original physical load attempt.

use super::*;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverLoadAttempt {
    pub worker_id: String,
    pub worker_generation: u64,
    pub sequence: u64,
    pub grant: ResourceGrant,
    pub manifest: ModelManifest,
    pub reserved_memory_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum DriverLoadState {
    /// The original attempt acquired no resources; invalid after Owned.
    NoEffect,
    Unknown,
    /// The original load completed and still owns this resource.
    Owned(DriverModelHandle),
    /// All resources acquired by the original attempt are confirmed released.
    Released,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DriverLoadObservation {
    pub attempt: DriverLoadAttempt,
    pub state: DriverLoadState,
}

impl<D: ModelDriver> InferenceWorker<D> {
    /// Observe only the original unresolved load. This never dispatches a load
    /// or reconciles an execution/unload whose terminality is still unknown.
    pub fn reconcile_load(&mut self, model_id: &str) -> Result<DriverLoadState, Error> {
        validate_identity(model_id, "model")?;
        let loaded = self.models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.lifecycle != ModelLifecycle::LoadUnresolved {
            return Err(Error::ActiveRequests);
        }
        let observed = self.driver.reconcile_load(&loaded.attempt)?;
        self.apply_load(model_id, observed)
    }

    pub(super) fn refuse_unresolved_load(&self) -> Result<(), Error> {
        if self.models.values().any(|model| {
            matches!(
                model.lifecycle,
                ModelLifecycle::LoadUnresolved | ModelLifecycle::LoadRejected
            )
        }) {
            return Err(Error::ActiveRequests);
        }
        Ok(())
    }

    pub(super) fn apply_load(
        &mut self,
        model_id: &str,
        observed: DriverLoadObservation,
    ) -> Result<DriverLoadState, Error> {
        let loaded = self.models.get(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.lifecycle != ModelLifecycle::LoadUnresolved || loaded.handle.is_some() {
            return Err(Error::ActiveRequests);
        }
        if observed.attempt != loaded.attempt {
            return self.reject_load(
                model_id,
                Error::DriverFailure("load binding mismatch".to_string()),
            );
        }
        match observed.state {
            DriverLoadState::Owned(handle) => {
                let duplicate = self.models.iter().any(|(id, model)| {
                    id != model_id
                        && model
                            .handle
                            .as_ref()
                            .is_some_and(|other| other.opaque_id == handle.opaque_id)
                });
                let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
                loaded.handle = Some(handle.clone());
                let validation = validate_identity(&handle.opaque_id, "model handle").and({
                    if duplicate
                        || handle.observed_memory_bytes > loaded.attempt.reserved_memory_bytes
                    {
                        Err(Error::ModelCapacity)
                    } else {
                        Ok(())
                    }
                });
                if let Err(error) = validation {
                    return self.reject_load(model_id, error);
                }
                loaded.lifecycle = ModelLifecycle::Ready;
                Ok(DriverLoadState::Owned(handle))
            }
            state @ (DriverLoadState::NoEffect | DriverLoadState::Released) => {
                self.models.remove(model_id);
                Ok(state)
            }
            DriverLoadState::Unknown => Ok(DriverLoadState::Unknown),
        }
    }

    fn reject_load(&mut self, model_id: &str, error: Error) -> Result<DriverLoadState, Error> {
        self.models
            .get_mut(model_id)
            .ok_or(Error::ModelNotLoaded)?
            .lifecycle = ModelLifecycle::LoadRejected;
        self.release_model(model_id)?;
        Err(error)
    }

    pub(super) fn release_model(&mut self, model_id: &str) -> Result<(), Error> {
        let loaded = self.models.get_mut(model_id).ok_or(Error::ModelNotLoaded)?;
        if loaded.active_requests != 0 || loaded.lifecycle == ModelLifecycle::ExecutionUnresolved {
            return Err(Error::ActiveRequests);
        }
        loaded.lifecycle = match loaded.lifecycle {
            ModelLifecycle::LoadUnresolved | ModelLifecycle::LoadRejected => {
                ModelLifecycle::LoadRejected
            }
            ModelLifecycle::Ready | ModelLifecycle::UnloadUnresolved => {
                ModelLifecycle::UnloadUnresolved
            }
            ModelLifecycle::ExecutionUnresolved => return Err(Error::ActiveRequests),
        };
        let observed = self.driver.unload(&loaded.attempt)?;
        if observed.attempt != loaded.attempt {
            return Err(Error::DriverFailure("release binding mismatch".to_string()));
        }
        match observed.state {
            DriverLoadState::Released => {}
            DriverLoadState::NoEffect if loaded.handle.is_none() => {}
            DriverLoadState::Owned(handle) => {
                loaded.handle.get_or_insert(handle);
                return Err(Error::DriverFailure("release unresolved".to_string()));
            }
            DriverLoadState::NoEffect | DriverLoadState::Unknown => {
                return Err(Error::DriverFailure("release unresolved".to_string()));
            }
        }
        self.models.remove(model_id);
        Ok(())
    }
}
