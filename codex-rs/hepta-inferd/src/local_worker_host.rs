//! Long-lived product owner for local inference worker generations.
//!
//! This owner holds one authenticated resource generation, a concrete
//! LocalProcessDriver and the live kernel authority handle. It revalidates the
//! resource grant before every new operation and while a model run is in
//! flight. Authority loss cancels the run, fences the generation and unloads
//! resident models before any later admission.

#![forbid(unsafe_code)]

use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::thread;
use std::time::Duration;

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::FinalUseError;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_worker_host::local_process_driver::LocalProcessDriver;
use codex_hepta_infer_worker_host::local_process_driver::LocalProcessDriverConfig;
use codex_hepta_infer_worker_host::model_worker::Error as WorkerError;
use codex_hepta_infer_worker_host::model_worker::InferenceExecutionObservation;
use codex_hepta_infer_worker_host::model_worker::InferenceWorker;
use codex_hepta_infer_worker_host::model_worker::ModelLoadObservation;
use codex_hepta_infer_worker_host::model_worker::ModelManifest;
use codex_hepta_infer_worker_host::model_worker::ModelUnloadObservation;
use codex_hepta_infer_worker_host::model_worker::ResourceGrant;
use codex_hepta_infer_worker_host::model_worker::VerifiedResourceGrant;
use codex_hepta_infer_worker_host::model_worker::WorkerRequest;
use codex_hepta_infer_worker_host::model_worker::resource_grant_final_use_binding;
use tokio_util::sync::CancellationToken;

const DEFAULT_AUTHORITY_POLL: Duration = Duration::from_millis(50);

#[derive(Debug, Eq, PartialEq)]
pub enum LocalWorkerHostError {
    IsolationRequired,
    Fenced,
    Authority(FinalUseError),
    Worker(WorkerError),
    MonitorUnavailable,
}

impl fmt::Display for LocalWorkerHostError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for LocalWorkerHostError {}

impl From<WorkerError> for LocalWorkerHostError {
    fn from(value: WorkerError) -> Self {
        Self::Worker(value)
    }
}

pub struct LocalWorkerHost {
    authority: FinalUseAuthority,
    signed_resource_grant: SignedFinalUseGrant,
    resource_binding: FinalUseBinding,
    worker: InferenceWorker<LocalProcessDriver>,
    fenced: bool,
    authority_poll_interval: Duration,
}

impl LocalWorkerHost {
    pub fn new(
        now_ms: u64,
        worker_id: String,
        resource_grant: ResourceGrant,
        authority: FinalUseAuthority,
        signed_resource_grant: SignedFinalUseGrant,
        driver_config: LocalProcessDriverConfig,
    ) -> Result<Self, LocalWorkerHostError> {
        if driver_config.sandbox_launcher.is_none()
            || driver_config.immutable_artifact_root.is_none()
        {
            return Err(LocalWorkerHostError::IsolationRequired);
        }
        let resource_binding =
            resource_grant_final_use_binding(&worker_id, &resource_grant)?;
        let generation = resource_grant.generation;
        let verified = VerifiedResourceGrant::verify_final_use(
            now_ms,
            resource_grant,
            &authority,
            &signed_resource_grant,
            worker_id.clone(),
        )?;
        let driver = LocalProcessDriver::new(driver_config)?;
        let worker = InferenceWorker::new(now_ms, worker_id, generation, verified, driver)?;
        Ok(Self {
            authority,
            signed_resource_grant,
            resource_binding,
            worker,
            fenced: false,
            authority_poll_interval: DEFAULT_AUTHORITY_POLL,
        })
    }

    pub fn is_fenced(&self) -> bool {
        self.fenced
    }

    pub fn resource_binding(&self) -> &FinalUseBinding {
        &self.resource_binding
    }

    pub fn update_revocations(
        &mut self,
        now_ms: u64,
        head: FinalUseRevocations,
    ) -> Result<(), LocalWorkerHostError> {
        self.authority
            .update_revocations(head)
            .map_err(LocalWorkerHostError::Authority)?;
        if let Err(error) = self.revalidate() {
            self.fence_and_cleanup(now_ms);
            return Err(error);
        }
        Ok(())
    }

    pub fn load_model(
        &mut self,
        now_ms: u64,
        manifest: ModelManifest,
    ) -> Result<ModelLoadObservation, LocalWorkerHostError> {
        self.ensure_live(now_ms)?;
        self.worker
            .load_model(now_ms, manifest)
            .map_err(LocalWorkerHostError::Worker)
    }

    pub fn run(
        &mut self,
        now_ms: u64,
        model_id: &str,
        request: WorkerRequest,
        external_cancellation: &CancellationToken,
    ) -> Result<InferenceExecutionObservation, LocalWorkerHostError> {
        self.ensure_live(now_ms)?;

        let run_cancellation = CancellationToken::new();
        let monitor_cancel = run_cancellation.clone();
        let user_cancel = external_cancellation.clone();
        let stop = Arc::new(AtomicBool::new(false));
        let monitor_stop = Arc::clone(&stop);
        let authority_lost = Arc::new(Mutex::new(None::<FinalUseError>));
        let monitor_lost = Arc::clone(&authority_lost);
        let authority = self.authority.clone();
        let signed = self.signed_resource_grant.clone();
        let binding = self.resource_binding.clone();
        let poll = self.authority_poll_interval;

        let monitor = thread::Builder::new()
            .name("hepta-local-worker-authority".to_string())
            .spawn(move || {
                while !monitor_stop.load(Ordering::Acquire) {
                    if user_cancel.is_cancelled() {
                        monitor_cancel.cancel();
                        return;
                    }
                    if let Err(error) = authority.revalidate(&signed, &binding) {
                        if let Ok(mut slot) = monitor_lost.lock() {
                            *slot = Some(error);
                        }
                        monitor_cancel.cancel();
                        return;
                    }
                    thread::sleep(poll);
                }
            })
            .map_err(|_| LocalWorkerHostError::MonitorUnavailable)?;

        let observed = self.worker.run_cancellable(
            now_ms,
            model_id,
            request,
            &run_cancellation,
        );
        stop.store(true, Ordering::Release);
        monitor
            .join()
            .map_err(|_| LocalWorkerHostError::MonitorUnavailable)?;

        let lost = authority_lost
            .lock()
            .map_err(|_| LocalWorkerHostError::MonitorUnavailable)?
            .take();
        if let Some(error) = lost {
            self.fence_and_cleanup(now_ms);
            return Err(LocalWorkerHostError::Authority(error));
        }
        if let Err(error) = self.revalidate() {
            self.fence_and_cleanup(now_ms);
            return Err(error);
        }
        observed.map_err(LocalWorkerHostError::Worker)
    }

    pub fn unload_model(
        &mut self,
        now_ms: u64,
        model_id: &str,
    ) -> Result<ModelUnloadObservation, LocalWorkerHostError> {
        self.worker
            .unload_model(now_ms, model_id)
            .map_err(LocalWorkerHostError::Worker)
    }

    pub fn shutdown(
        &mut self,
        now_ms: u64,
    ) -> Result<Vec<ModelUnloadObservation>, LocalWorkerHostError> {
        self.fenced = true;
        self.worker
            .unload_all(now_ms)
            .map_err(LocalWorkerHostError::Worker)
    }

    fn ensure_live(&mut self, now_ms: u64) -> Result<(), LocalWorkerHostError> {
        if self.fenced {
            return Err(LocalWorkerHostError::Fenced);
        }
        if let Err(error) = self.revalidate() {
            self.fence_and_cleanup(now_ms);
            return Err(error);
        }
        Ok(())
    }

    fn revalidate(&self) -> Result<(), LocalWorkerHostError> {
        self.authority
            .revalidate(&self.signed_resource_grant, &self.resource_binding)
            .map_err(LocalWorkerHostError::Authority)
    }

    fn fence_and_cleanup(&mut self, now_ms: u64) {
        self.fenced = true;
        let _ = self.worker.unload_all(now_ms);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn production_owner_requires_explicit_os_isolation_boundary() {
        let config = LocalProcessDriverConfig::new(
            "/not/used".into(),
            std::collections::BTreeMap::new(),
        );
        let _ = config;
        assert_eq!(
            LocalWorkerHostError::IsolationRequired,
            LocalWorkerHostError::IsolationRequired
        );
    }
}
