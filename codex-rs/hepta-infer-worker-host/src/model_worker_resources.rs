//! Preserve the legacy grant domain and read the original Fleet domain explicitly.
use super::Error;
#[cfg(all(target_os = "linux", feature = "agentd-host"))]
use super::MAX_MODELS;
use super::ResourceGrant;

impl<D: super::ModelDriver> super::InferenceWorker<D> {
    pub(crate) fn validate_current_resources(&self, now_ms: u64) -> Result<(), Error> {
        self.grant
            .current_limits(now_ms, &self.worker_id, self.generation)
            .map(|_| ())
    }
}

#[derive(Debug)]
pub(super) enum WorkerResources {
    Legacy(ResourceGrant),
    #[cfg(all(target_os = "linux", feature = "agentd-host"))]
    Fleet(std::sync::Arc<crate::FleetWorkerResourcePortV2>),
}

pub(super) struct WorkerLimits {
    pub(super) maximum_models: usize,
    pub(super) maximum_active_requests: usize,
    pub(super) maximum_memory_bytes: u64,
}
impl WorkerResources {
    pub(super) fn current_limits(
        &self,
        now_ms: u64,
        worker_id: &str,
        worker_generation: u64,
    ) -> Result<WorkerLimits, Error> {
        match self {
            Self::Legacy(grant) => {
                super::validate_grant(now_ms, grant)?;
                if grant.generation != worker_generation || worker_id.is_empty() {
                    return Err(Error::InvalidGrant);
                }
                Ok(WorkerLimits {
                    maximum_models: grant.maximum_models,
                    maximum_active_requests: grant.maximum_active_requests,
                    maximum_memory_bytes: grant.maximum_memory_bytes,
                })
            }
            #[cfg(all(target_os = "linux", feature = "agentd-host"))]
            Self::Fleet(port) => {
                let current = port
                    .observe_current()
                    .map_err(|error| Error::DriverFailure(error.to_string()))?;
                if current.binding().worker_generation.get() != worker_generation
                    || current.binding().context.principal_id != worker_id
                    || now_ms >= current.allocation().expires_at_ms
                {
                    return Err(Error::InvalidGrant);
                }
                Ok(WorkerLimits {
                    // This is the protocol's internal model-table bound. Fleet
                    // does not issue a separate model-count or model-generation grant.
                    maximum_models: MAX_MODELS,
                    maximum_active_requests: usize::try_from(
                        current.allocation().resources.concurrent_turns,
                    )
                    .map_err(|_| Error::InvalidGrant)?,
                    maximum_memory_bytes: current.allocation().resources.memory_bytes,
                })
            }
        }
    }
}
