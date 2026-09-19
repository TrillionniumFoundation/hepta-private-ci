//! Typed inference.control -> inference.worker production composition seam.
//!
//! Planning remains authority-free. Execution receives an independently
//! operated grant resolver only after the worker has frozen the exact provider,
//! context, quota/resource and physical TurnStart payload. Durable state remains
//! owned by inference.control; verification remains kernel.authority-owned.

#![forbid(unsafe_code)]

use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
use codex_hepta_infer_worker_host::native_app_server::FinalUseGrantResolver;
use codex_hepta_infer_worker_host::native_app_server::NativeAdmission;
use codex_hepta_infer_worker_host::native_app_server::NativeRunOutput;
use codex_hepta_infer_worker_host::native_app_server::NativeWorkerConfig;
use tokio_util::sync::CancellationToken;

pub type WorkerPortResult<T> =
    Result<T, Box<dyn std::error::Error + Send + Sync>>;

/// Source-composed implementation of
/// `ModulePort::inference.control::inference.worker`.
///
/// This type does not issue grants, widen authority, or own inference state.
/// The driver's kernel-owned FinalUseAuthority is established at construction;
/// the external resolver supplies only a signed grant for the exact frozen
/// binding at execution time.
pub struct NativeWorkerPort {
    driver: AppServerModelDriver,
}

impl NativeWorkerPort {
    pub fn new(config: NativeWorkerConfig) -> WorkerPortResult<Self> {
        Ok(Self {
            driver: AppServerModelDriver::new(config)?,
        })
    }

    /// Execute one exact request. Restart recovery never resolves or claims a
    /// second grant and never submits a replacement turn.
    pub async fn execute(
        &self,
        control: &mut DurableInferenceControl,
        admission: NativeAdmission,
        prompt: String,
        cancellation: &CancellationToken,
        grant_resolver: &FinalUseGrantResolver<'_>,
    ) -> WorkerPortResult<NativeRunOutput> {
        self.driver
            .run(
                control,
                admission,
                prompt,
                /*context_query*/ None,
                cancellation,
                grant_resolver,
            )
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn worker_port_surface_is_present() {
        assert!(std::any::type_name::<NativeWorkerPort>().contains("NativeWorkerPort"));
    }
}
