//! Typed inference.control -> inference.worker production composition seam.
//!
//! Planning remains authority-free. This port accepts a kernel-owned
//! FinalUseAuthority and independently signed grant at execution time, then
//! delegates the exact fresh request to the worker's final-use-gated path.

#![forbid(unsafe_code)]

use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::FinalUseBinding;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_worker_host::native_app_server::AppServerModelDriver;
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
/// Durable reservation/dispatch/settlement remains in DurableInferenceControl;
/// final-use verification remains in kernel.authority; execution remains in
/// inference.worker.
pub struct NativeWorkerPort {
    driver: AppServerModelDriver,
}

impl NativeWorkerPort {
    pub fn new(config: NativeWorkerConfig) -> WorkerPortResult<Self> {
        Ok(Self {
            driver: AppServerModelDriver::new(config)?,
        })
    }

    /// Return the exact binding an external authority owner must sign for a
    /// fresh provider dispatch through this port.
    pub fn final_use_binding(
        &self,
        request_id: &str,
        prompt: &str,
    ) -> WorkerPortResult<FinalUseBinding> {
        self.driver.provider_final_use_binding(request_id, prompt)
    }

    /// Consume already-established authority and execute one exact request.
    ///
    /// The worker claims the signed final-use grant only for a fresh Reserved
    /// request immediately before durable dispatch intent. Restart recovery
    /// never claims a second grant and never submits a replacement turn.
    pub async fn execute(
        &self,
        control: &mut DurableInferenceControl,
        authority: &FinalUseAuthority,
        signed: &SignedFinalUseGrant,
        admission: NativeAdmission,
        prompt: String,
        cancellation: &CancellationToken,
    ) -> WorkerPortResult<NativeRunOutput> {
        self.driver
            .run_authorized(
                control,
                authority,
                signed,
                admission,
                prompt,
                cancellation,
            )
            .await
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_contracts::AgentId;
    use std::path::PathBuf;
    use std::time::Duration;

    fn port() -> NativeWorkerPort {
        NativeWorkerPort::new(NativeWorkerConfig {
            agentd_socket: PathBuf::from("/tmp/hepta-agentd-test.sock"),
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
                .expect("fixed agent id"),
            generation: 7,
            model: "model.exact".to_string(),
            timeout: Duration::from_secs(30),
        })
        .expect("port")
    }

    #[test]
    fn final_use_binding_is_exact_stable_and_payload_sensitive() {
        let port = port();
        let first = port
            .final_use_binding("request.1", "hello")
            .expect("first binding");
        let same = port
            .final_use_binding("request.1", "hello")
            .expect("same binding");
        let changed = port
            .final_use_binding("request.1", "hello!")
            .expect("changed binding");

        assert_eq!(first, same);
        assert_eq!(
            first.subject_id,
            "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12"
        );
        assert_eq!(first.destination_id, "provider:codex-app-server");
        assert_ne!(first.request_sha256, [0; 32]);
        assert_ne!(first.scope_sha256, [0; 32]);
        assert_ne!(first.payload_sha256, [0; 32]);
        assert_ne!(first.payload_sha256, changed.payload_sha256);
        assert_ne!(first.request_sha256, changed.request_sha256);
        assert_eq!(first.scope_sha256, changed.scope_sha256);
    }
}
