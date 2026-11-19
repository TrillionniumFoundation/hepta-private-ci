//! Original Runtime fixed-helper transport, attached only by the recovered owner.

use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use base64::Engine;
use codex_config::AppToolApproval;
use codex_hepta_contracts::FinalUseAuthority;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::AndroidSetTextV1;
use codex_hepta_memory::OriginalAndroidTextDevice;
use codex_hepta_memory::ProductionAndroidTextTarget;
use codex_mcp::McpBinding;
use codex_mcp::RetainedMcpCalls;
use codex_rmcp_client::RetainedMcpToolSession;
use serde::Serialize;
use tokio::runtime::Handle;
use tokio::runtime::RuntimeFlavor;

use crate::AgentdConfig;
use crate::AgentdError;
use crate::AgentdProductionOperationRuntimeConfig;
use crate::AgentdProductionWriterHost;

#[path = "android_runtime_job.rs"]
mod job;

/// Explicit bootstrap inputs from the existing trusted host. `session` must be
/// its already authenticated, source-qualified Runtime peer for Pocket4; the
/// original helper/APK/signer qualification remains the host's responsibility.
/// This value neither discovers credentials nor creates any device authority.
/// `deadline` is the original local monotonic bound, never a renewed expiry.
pub struct AgentdAndroidRuntimeInputs {
    pub session: AgentdAndroidRuntimeSession,
    pub runtime: Handle,
    pub payload_json: String,
    pub deadline: Instant,
}

/// An original native peer or the named calls retained by the original MCP
/// manager. Managed calls preserve its tool/environment/catalog boundaries.
pub enum AgentdAndroidRuntimeSession {
    Native(RetainedMcpToolSession),
    Managed(RetainedMcpCalls),
}

impl From<RetainedMcpToolSession> for AgentdAndroidRuntimeSession {
    fn from(session: RetainedMcpToolSession) -> Self {
        Self::Native(session)
    }
}

impl AgentdAndroidRuntimeInputs {
    /// Use the manager's existing ready binding without exporting its raw
    /// client, starting another server, or bypassing interactive tool policy.
    /// The original FinalUse owner still separately authorizes the operation.
    pub async fn from_mcp_binding(
        binding: &McpBinding,
        server: &str,
        environment_id: &str,
        runtime: Handle,
        payload_json: String,
        deadline: Instant,
    ) -> Result<Self, AgentdError> {
        let tools = ["process_start", "process_wait", "process_read"];
        let session = tokio::time::timeout_at(
            deadline.into(),
            binding.retain_calls(server, environment_id, &tools),
        )
        .await
        .map_err(|_| AgentdError::Protocol("original Android MCP bootstrap expired".into()))?
        .map_err(|error| AgentdError::Protocol(format!("original Android MCP binding: {error}")))?;
        if tools
            .into_iter()
            .any(|tool| session.tool_approval_mode(tool) != Some(AppToolApproval::Approve))
        {
            return Err(AgentdError::Invalid(
                "original Android Runtime tools require explicit unattended approval in the existing MCP policy".into(),
            ));
        }
        Ok(Self {
            session: AgentdAndroidRuntimeSession::Managed(session),
            runtime,
            payload_json,
            deadline,
        })
    }
}

/// Correlation retained for the original owner, not an effect receipt. An
/// absent job ID after an attempted start is explicitly unresolved. The
/// existing Runtime owns job persistence; this is not another durable ledger.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AndroidRuntimeAttempt {
    pub operation_id: String,
    pub payload_sha256: Sha256Digest,
    pub start_attempted: bool,
    pub job_id: Option<String>,
}

/// A single original operation and immutable payload on a retained Runtime
/// peer. The effect is one-shot even after success; a new authorized operation
/// requires explicit original-owner composition with a fresh native observation.
/// Uncertainty closes this effect lane permanently; read-only reconciliation
/// remains possible on the same peer and original operation.
pub struct AgentdAndroidTextDevice {
    session: AgentdAndroidRuntimeSession,
    runtime: Handle,
    deadline: Instant,
    apply_request: Vec<u8>,
    read_request: Vec<u8>,
    idempotency_key: String,
    effect_available: AtomicBool,
    invalidated: AtomicBool,
    exchange: Mutex<()>,
    attempt: Mutex<AndroidRuntimeAttempt>,
}

/// Prepare the real Android primary target for the same original production
/// writer. Construction performs no helper call, grant request or state write.
/// The trusted launcher must retain its original Runtime manager for the whole
/// Agentd lifetime and attach the existing Device FinalUse owner before use.
pub fn prepare_android_runtime_target(
    inputs: AgentdAndroidRuntimeInputs,
) -> Result<
    (
        Arc<ProductionAndroidTextTarget>,
        Arc<AgentdAndroidTextDevice>,
    ),
    AgentdError,
> {
    let (device, payload) = AgentdAndroidTextDevice::new(inputs).map_err(AgentdError::Invalid)?;
    let device = Arc::new(device);
    let target = ProductionAndroidTextTarget::new(&payload.observation, device.clone())
        .map_err(AgentdError::Invalid)?;
    Ok((Arc::new(target), device))
}

impl AgentdAndroidTextDevice {
    fn new(inputs: AgentdAndroidRuntimeInputs) -> Result<(Self, AndroidSetTextV1), String> {
        let payload = AndroidSetTextV1::from_json(&inputs.payload_json)?;
        let remaining = inputs.deadline.saturating_duration_since(Instant::now());
        let native_budget = Duration::from_millis(
            payload.expires_elapsed_ms - payload.observation.observed_elapsed_ms,
        );
        if remaining.is_zero()
            || remaining > native_budget
            || inputs.runtime.runtime_flavor() != RuntimeFlavor::MultiThread
        {
            return Err(
                "Android bootstrap requires the original deadline and live multithread runtime"
                    .to_string(),
            );
        }
        #[derive(Serialize)]
        struct Helper<'a> {
            op: &'a str,
            payload_base64: String,
            payload_sha256: &'a str,
        }
        let digest = Sha256Digest::for_bytes(inputs.payload_json.as_bytes());
        let request = |op| {
            serde_json::to_vec(&Helper {
                op,
                payload_base64: base64::engine::general_purpose::STANDARD
                    .encode(inputs.payload_json.as_bytes()),
                payload_sha256: digest.as_str(),
            })
            .map_err(|error| error.to_string())
        };
        let apply_request = request("organ-set-text")?;
        let read_request = request("organ-readback")?;
        if apply_request.len() > 24 * 1024 || read_request.len() > 24 * 1024 {
            return Err("Android helper request exceeds its bound".to_string());
        }
        let binding = format!(
            "hepta.android.runtime.v1\0{}\0{}",
            payload.operation_id,
            digest.as_str()
        );
        let idempotency_key = format!(
            "android-{}",
            Sha256Digest::for_bytes(binding.as_bytes()).as_str()
        );
        let attempt = AndroidRuntimeAttempt {
            operation_id: payload.operation_id.clone(),
            payload_sha256: digest,
            start_attempted: false,
            job_id: None,
        };
        Ok((
            Self {
                session: inputs.session,
                runtime: inputs.runtime,
                deadline: inputs.deadline,
                apply_request,
                read_request,
                idempotency_key,
                effect_available: AtomicBool::new(true),
                invalidated: AtomicBool::new(false),
                exchange: Mutex::new(()),
                attempt: Mutex::new(attempt),
            },
            payload,
        ))
    }

    pub fn attempt(&self) -> Result<AndroidRuntimeAttempt, String> {
        self.attempt
            .lock()
            .map(|attempt| attempt.clone())
            .map_err(|_| "Android original job correlation is unavailable".to_string())
    }

    fn exchange(&self, request: &[u8], kind: job::Invocation) -> Result<Vec<u8>, String> {
        let _guard = self
            .exchange
            .try_lock()
            .map_err(|_| "Android original helper exchange is already active".to_string())?;
        let expected = match kind {
            job::Invocation::Effect => &self.apply_request,
            job::Invocation::Readback => &self.read_request,
        };
        if request != expected {
            return Err("Android helper request differs from the original operation".to_string());
        }
        let run = || {
            let deadline = match kind {
                job::Invocation::Effect => self.deadline,
                job::Invocation::Readback if self.invalidated.load(Ordering::Acquire) => {
                    Instant::now() + Duration::from_secs(10)
                }
                job::Invocation::Readback => self.deadline,
            };
            self.runtime
                .block_on(job::invoke(self, request, kind, deadline))
        };
        // Execute inline within the original synchronous FinalUse entry. The
        // future is never detached, queued for later entry, or given a new RT.
        match Handle::try_current().map(|runtime| runtime.runtime_flavor()) {
            Ok(RuntimeFlavor::MultiThread) => tokio::task::block_in_place(run),
            Ok(_) => Err("Android effect cannot enter a current-thread async runtime".to_string()),
            Err(_) => run(),
        }
    }
}

impl OriginalAndroidTextDevice for AgentdAndroidTextDevice {
    fn apply(&self, helper_request: &[u8]) -> Result<Vec<u8>, String> {
        if self.invalidated.load(Ordering::Acquire)
            || self
                .effect_available
                .compare_exchange(true, false, Ordering::AcqRel, Ordering::Acquire)
                .is_err()
        {
            return Err("Android original effect lane is permanently closed".to_string());
        }
        let result = self.exchange(helper_request, job::Invocation::Effect);
        if result.is_err() {
            self.invalidate();
        }
        result
    }

    fn readback(&self, helper_request: &[u8]) -> Result<Vec<u8>, String> {
        self.exchange(helper_request, job::Invocation::Readback)
    }

    fn invalidate(&self) {
        self.invalidated.store(true, Ordering::Release);
        self.effect_available.store(false, Ordering::Release);
    }
}

impl AgentdProductionOperationRuntimeConfig {
    /// Attach a concrete Android target to the same recovered writer, existing
    /// grant provider and destination-specific FinalUse owner. Performs no
    /// native effect or grant request. Default Agentd startup never calls this.
    pub async fn with_android_from_runtime(
        self,
        config: &AgentdConfig,
        recovered_host: &AgentdProductionWriterHost,
        final_use: FinalUseAuthority,
        inputs: AgentdAndroidRuntimeInputs,
    ) -> Result<(Self, Arc<AgentdAndroidTextDevice>), AgentdError> {
        self.validate_for(config)?;
        if recovered_host.destination_count() != 0 {
            return Err(AgentdError::Invalid(
                "Android runtime bootstrap requires the original unregistered recovered writer"
                    .to_string(),
            ));
        }
        tokio::time::timeout_at(
            inputs.deadline.into(),
            self.validate_recovered_host(recovered_host),
        )
        .await
        .map_err(|_| {
            AgentdError::Protocol("Android recovered-owner validation expired".to_string())
        })??;
        let (target, device) = prepare_android_runtime_target(inputs)?;
        Ok((self.with_additional_target(final_use, target)?, device))
    }
}

#[cfg(test)]
#[path = "android_runtime_tests.rs"]
pub(crate) mod tests;
