//! Bounded local control protocol shared by one Hepta agent daemon and its supervisor.

#![forbid(unsafe_code)]

mod authbus;
mod capabilities;
pub use authbus::AuthBusTextBody;
pub use authbus::AuthBusTextIngress;
pub use authbus::AuthBusTextState;
pub use authbus::AuthBusTextStatus;
pub use capabilities::AGENTD_CAPABILITY_SCHEMA_VERSION;
pub use capabilities::AgentdCapability;
pub use capabilities::AgentdCapabilitySet;
pub use capabilities::NegotiatedAgentdCapabilities;
pub use capabilities::negotiate_capabilities;

use std::path::PathBuf;

use codex_hepta_automation::AutomationTask;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTaskId;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use serde::Deserialize;
use serde::Serialize;

pub const AGENTD_CONTROL_SCHEMA_VERSION: u32 = 2;
/// Version for the transport-only host turn authority witness.  This type is
/// deliberately not an authority grant and is not consumed by the Agentd
/// runtime yet; it gives a future host/supervisor seam one strict wire shape.
pub const HOST_TURN_AUTHORITY_BINDING_SCHEMA_VERSION: u32 = 1;
pub const MAX_CONTROL_FRAME_BYTES: u64 = 65_536;
pub const MAX_EVENT_BATCH: u16 = 256;
pub const MAX_FEDERATION_CONTROL_LIST: u16 = 128;
const FEDERATION_CAPABILITY_ID_PREFIX: &str = "federation:v1:";

#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct MemoryFederationCapabilityId(String);

impl MemoryFederationCapabilityId {
    pub fn parse(value: impl Into<String>) -> Result<Self, String> {
        let value = value.into();
        let digest = value
            .strip_prefix(FEDERATION_CAPABILITY_ID_PREFIX)
            .ok_or_else(|| "invalid memory federation capability id".to_string())?;
        Sha256Digest::parse(digest.to_string())?;
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for MemoryFederationCapabilityId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::parse(value).map_err(serde::de::Error::custom)
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryFederationScopeKind {
    AgentPrivate,
    WorkspacePrivate,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MemoryFederationCapabilityState {
    Granted,
    Revoked,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct MemoryFederationCapabilitySnapshot {
    pub capability_id: MemoryFederationCapabilityId,
    pub owner_agent_id: AgentId,
    pub consumer_agent_id: AgentId,
    pub owner_scope: MemoryFederationScopeKind,
    pub generation: u64,
    pub revision: u64,
    pub effective_at_unix_seconds: i64,
    pub expires_at_unix_seconds: i64,
    pub state: MemoryFederationCapabilityState,
}

pub const MAX_RUN_CANCEL_REASON_BYTES: usize = 512;
pub const MAX_RUN_EXECUTION_ID_BYTES: usize = 256;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RunPhase {
    Admitted,
    ContextAttached,
    Dispatched,
    Cancelling,
    Cancelled,
    Succeeded,
    Failed,
    Indeterminate,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunSnapshot {
    pub run_id: String,
    pub request_digest: String,
    pub objective_digest: String,
    pub body_digest: String,
    pub artifact_set_digest: String,
    pub authority_epoch: u64,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ContextAttachment {
    pub run_id: String,
    pub request_digest: String,
    pub objective_digest: String,
    pub body_digest: String,
    pub artifact_set_digest: String,
    pub authority_epoch: u64,
    pub deadline_ms: u64,
    pub context_digest: String,
    pub compilation_receipt_digest: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunDispatchBinding {
    pub run_id: String,
    pub context_digest: String,
    pub thread_id: String,
    pub provider_request_digest: String,
    pub binding_digest: String,
}

impl RunDispatchBinding {
    pub fn new(
        run_id: impl Into<String>,
        context_digest: impl Into<String>,
        thread_id: impl Into<String>,
        provider_request_digest: impl Into<String>,
    ) -> Result<Self, String> {
        let mut value = Self {
            run_id: run_id.into(),
            context_digest: context_digest.into(),
            thread_id: thread_id.into(),
            provider_request_digest: provider_request_digest.into(),
            binding_digest: String::new(),
        };
        value.binding_digest = value.compute_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), String> {
        validate_run_protocol_id(&self.run_id, "run id", 128)?;
        validate_run_protocol_id(&self.thread_id, "Codex thread id", MAX_RUN_EXECUTION_ID_BYTES)?;
        validate_run_protocol_digest(&self.context_digest, "context digest")?;
        validate_run_protocol_digest(&self.provider_request_digest, "provider request digest")?;
        validate_run_protocol_digest(&self.binding_digest, "dispatch binding digest")?;
        if self.binding_digest != self.compute_digest() {
            return Err("dispatch binding digest mismatch".to_string());
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> String {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.agentd.run-dispatch-binding.v1");
        push_run_protocol_text(&mut bytes, &self.run_id);
        push_run_protocol_text(&mut bytes, &self.context_digest);
        push_run_protocol_text(&mut bytes, &self.thread_id);
        push_run_protocol_text(&mut bytes, &self.provider_request_digest);
        Sha256Digest::for_bytes(&bytes).as_str().to_string()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunExecutionBinding {
    pub run_id: String,
    pub dispatch_binding_digest: String,
    pub thread_id: String,
    pub turn_id: String,
    pub binding_digest: String,
}

impl RunExecutionBinding {
    pub fn new(
        run_id: impl Into<String>,
        dispatch_binding_digest: impl Into<String>,
        thread_id: impl Into<String>,
        turn_id: impl Into<String>,
    ) -> Result<Self, String> {
        let mut value = Self {
            run_id: run_id.into(),
            dispatch_binding_digest: dispatch_binding_digest.into(),
            thread_id: thread_id.into(),
            turn_id: turn_id.into(),
            binding_digest: String::new(),
        };
        value.binding_digest = value.compute_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), String> {
        validate_run_protocol_id(&self.run_id, "run id", 128)?;
        validate_run_protocol_id(&self.thread_id, "Codex thread id", MAX_RUN_EXECUTION_ID_BYTES)?;
        validate_run_protocol_id(&self.turn_id, "Codex turn id", MAX_RUN_EXECUTION_ID_BYTES)?;
        validate_run_protocol_digest(&self.dispatch_binding_digest, "dispatch binding digest")?;
        validate_run_protocol_digest(&self.binding_digest, "execution binding digest")?;
        if self.binding_digest != self.compute_digest() {
            return Err("execution binding digest mismatch".to_string());
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> String {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.agentd.run-execution-binding.v1");
        push_run_protocol_text(&mut bytes, &self.run_id);
        push_run_protocol_text(&mut bytes, &self.dispatch_binding_digest);
        push_run_protocol_text(&mut bytes, &self.thread_id);
        push_run_protocol_text(&mut bytes, &self.turn_id);
        Sha256Digest::for_bytes(&bytes).as_str().to_string()
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunTerminalObservation {
    pub run_id: String,
    pub dispatch_binding_digest: String,
    pub execution_binding_digest: String,
    pub thread_id: String,
    pub turn_id: String,
    pub phase: RunPhase,
    pub observation_digest: String,
}

impl RunTerminalObservation {
    pub fn new(
        run_id: impl Into<String>,
        dispatch_binding_digest: impl Into<String>,
        execution_binding_digest: impl Into<String>,
        thread_id: impl Into<String>,
        turn_id: impl Into<String>,
        phase: RunPhase,
    ) -> Result<Self, String> {
        let mut value = Self {
            run_id: run_id.into(),
            dispatch_binding_digest: dispatch_binding_digest.into(),
            execution_binding_digest: execution_binding_digest.into(),
            thread_id: thread_id.into(),
            turn_id: turn_id.into(),
            phase,
            observation_digest: String::new(),
        };
        value.observation_digest = value.compute_digest();
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), String> {
        validate_run_protocol_id(&self.run_id, "run id", 128)?;
        validate_run_protocol_id(&self.thread_id, "Codex thread id", MAX_RUN_EXECUTION_ID_BYTES)?;
        validate_run_protocol_id(&self.turn_id, "Codex turn id", MAX_RUN_EXECUTION_ID_BYTES)?;
        validate_run_protocol_digest(&self.dispatch_binding_digest, "dispatch binding digest")?;
        validate_run_protocol_digest(&self.execution_binding_digest, "execution binding digest")?;
        validate_run_protocol_digest(&self.observation_digest, "terminal observation digest")?;
        if !matches!(self.phase, RunPhase::Cancelled | RunPhase::Succeeded | RunPhase::Failed) {
            return Err("terminal observation must carry a terminal run phase".to_string());
        }
        if self.observation_digest != self.compute_digest() {
            return Err("terminal observation digest mismatch".to_string());
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_digest(&self) -> String {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.agentd.run-terminal-observation.v1");
        push_run_protocol_text(&mut bytes, &self.run_id);
        push_run_protocol_text(&mut bytes, &self.dispatch_binding_digest);
        push_run_protocol_text(&mut bytes, &self.execution_binding_digest);
        push_run_protocol_text(&mut bytes, &self.thread_id);
        push_run_protocol_text(&mut bytes, &self.turn_id);
        bytes.push(match self.phase {
            RunPhase::Cancelled => 0,
            RunPhase::Succeeded => 1,
            RunPhase::Failed => 2,
            RunPhase::Admitted
            | RunPhase::ContextAttached
            | RunPhase::Dispatched
            | RunPhase::Cancelling
            | RunPhase::Indeterminate => u8::MAX,
        });
        Sha256Digest::for_bytes(&bytes).as_str().to_string()
    }
}

fn validate_run_protocol_id(value: &str, label: &str, maximum: usize) -> Result<(), String> {
    if value.is_empty()
        || value.len() > maximum
        || !value.bytes().all(|byte| byte.is_ascii_alphanumeric() || b"._:-".contains(&byte))
    {
        return Err(format!("{label} is invalid"));
    }
    Ok(())
}

fn validate_run_protocol_digest(value: &str, label: &str) -> Result<(), String> {
    Sha256Digest::parse(value.to_string()).map_err(|_| format!("{label} is invalid"))?;
    if value.bytes().all(|byte| byte == b'0') {
        return Err(format!("{label} must not be the zero digest"));
    }
    Ok(())
}

fn push_run_protocol_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RunReceipt {
    pub run_id: String,
    pub revision: u64,
    pub phase: RunPhase,
    pub context_digest: Option<String>,
    pub terminal_observed: bool,
    pub idempotent: bool,
    pub cancel_reason: Option<String>,
    pub cancellation_ack_deadline_ms: Option<u64>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CancellationDisposition {
    CancelledBeforeDispatch,
    CancellingAfterDispatch,
    AlreadyTerminal,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdRequest {
    pub schema_version: u32,
    pub request_id: u64,
    pub spawn_generation: u64,
    pub method: AgentdMethod,
}

impl AgentdRequest {
    pub fn capabilities(request_id: u64, spawn_generation: u64) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::Capabilities,
        }
    }

    pub fn health(request_id: u64, spawn_generation: u64) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::Health,
        }
    }

    pub fn lifecycle(request_id: u64, spawn_generation: u64) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::Lifecycle,
        }
    }

    pub fn session_ingress(request_id: u64, spawn_generation: u64) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::SessionIngress,
        }
    }

    pub fn run_start(request_id: u64, spawn_generation: u64, snapshot: RunSnapshot) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunStart { snapshot },
        }
    }

    pub fn run_attach_context(
        request_id: u64,
        spawn_generation: u64,
        expected_revision: u64,
        attachment: ContextAttachment,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunAttachContext {
                expected_revision,
                attachment,
            },
        }
    }

    pub fn run_mark_dispatched(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        binding: RunDispatchBinding,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunMarkDispatched {
                run_id,
                expected_revision,
                binding,
            },
        }
    }

    pub fn run_bind_execution(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        binding: RunExecutionBinding,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunBindExecution {
                run_id,
                expected_revision,
                binding,
            },
        }
    }

    pub fn run_cancel(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        reason: String,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunCancel {
                run_id,
                expected_revision,
                reason,
            },
        }
    }

    pub fn run_observe_terminal(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
        phase: RunPhase,
        observation: Option<RunTerminalObservation>,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunObserveTerminal {
                run_id,
                expected_revision,
                phase,
                observation,
            },
        }
    }

    pub fn run_status(request_id: u64, spawn_generation: u64, run_id: String) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunStatus { run_id },
        }
    }

    pub fn run_remove_closed(
        request_id: u64,
        spawn_generation: u64,
        run_id: String,
        expected_revision: u64,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::RunRemoveClosed {
                run_id,
                expected_revision,
            },
        }
    }

    pub fn events(request_id: u64, spawn_generation: u64, after_cursor: u64, limit: u16) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::Events {
                after_cursor,
                limit,
            },
        }
    }

    pub fn automation_create(
        request_id: u64,
        spawn_generation: u64,
        draft: AutomationTaskDraft,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::AutomationCreate { draft },
        }
    }

    pub fn automation_list(request_id: u64, spawn_generation: u64, limit: u16) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::AutomationList { limit },
        }
    }

    pub fn automation_cancel(
        request_id: u64,
        spawn_generation: u64,
        task_id: AutomationTaskId,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::AutomationCancel { task_id },
        }
    }

    pub fn automation_set_enabled(
        request_id: u64,
        spawn_generation: u64,
        task_id: AutomationTaskId,
        enabled: bool,
        resume_at_ms: Option<u64>,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::AutomationSetEnabled {
                task_id,
                enabled,
                resume_at_ms,
            },
        }
    }

    pub fn memory_federation_grant(
        request_id: u64,
        spawn_generation: u64,
        consumer_agent_id: AgentId,
        owner_scope: MemoryFederationScopeKind,
        lifetime_seconds: u32,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::MemoryFederationGrant {
                consumer_agent_id,
                owner_scope,
                lifetime_seconds,
            },
        }
    }

    pub fn memory_federation_revoke(
        request_id: u64,
        spawn_generation: u64,
        capability_id: MemoryFederationCapabilityId,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::MemoryFederationRevoke { capability_id },
        }
    }

    pub fn memory_federation_list(request_id: u64, spawn_generation: u64, limit: u16) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::MemoryFederationList { limit },
        }
    }

    pub fn memory_federation_status(
        request_id: u64,
        spawn_generation: u64,
        capability_id: MemoryFederationCapabilityId,
    ) -> Self {
        Self {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id,
            spawn_generation,
            method: AgentdMethod::MemoryFederationStatus { capability_id },
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum AgentdMethod {
    Capabilities,
    Health,
    Lifecycle,
    SessionIngress,
    RunStart {
        snapshot: RunSnapshot,
    },
    RunAttachContext {
        expected_revision: u64,
        attachment: ContextAttachment,
    },
    RunMarkDispatched {
        run_id: String,
        expected_revision: u64,
        binding: RunDispatchBinding,
    },
    RunBindExecution {
        run_id: String,
        expected_revision: u64,
        binding: RunExecutionBinding,
    },
    RunCancel {
        run_id: String,
        expected_revision: u64,
        reason: String,
    },
    RunObserveTerminal {
        run_id: String,
        expected_revision: u64,
        phase: RunPhase,
        observation: Option<RunTerminalObservation>,
    },
    RunStatus {
        run_id: String,
    },
    RunRemoveClosed {
        run_id: String,
        expected_revision: u64,
    },
    AuthBusText {
        request: AuthBusTextIngress,
    },
    AuthBusTextStatus {
        delivery_id: String,
    },
    CognitiveContext {
        query: String,
        limit: u16,
    },
    Events {
        after_cursor: u64,
        limit: u16,
    },
    AutomationCreate {
        draft: AutomationTaskDraft,
    },
    AutomationList {
        limit: u16,
    },
    AutomationCancel {
        task_id: AutomationTaskId,
    },
    AutomationSetEnabled {
        task_id: AutomationTaskId,
        enabled: bool,
        resume_at_ms: Option<u64>,
    },
    MemoryFederationGrant {
        consumer_agent_id: AgentId,
        owner_scope: MemoryFederationScopeKind,
        lifetime_seconds: u32,
    },
    MemoryFederationRevoke {
        capability_id: MemoryFederationCapabilityId,
    },
    MemoryFederationList {
        limit: u16,
    },
    MemoryFederationStatus {
        capability_id: MemoryFederationCapabilityId,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdResponse {
    pub schema_version: u32,
    pub request_id: u64,
    pub agent_id: AgentId,
    pub spawn_generation: u64,
    pub current_generation: u64,
    pub payload: AgentdPayload,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum AgentdPayload {
    Capabilities(AgentdCapabilitySet),
    Health(HealthSnapshot),
    Lifecycle(LifecycleSnapshot),
    SessionIngress(SessionIngress),
    RunReceipt(RunReceipt),
    RunCancellation {
        disposition: CancellationDisposition,
        receipt: RunReceipt,
    },
    RunStatus {
        receipt: Option<RunReceipt>,
    },
    CognitiveContext(CognitiveContextSnapshot),
    AuthBusTextStatus(AuthBusTextStatus),
    Events(EventBatch),
    AutomationTask(AutomationTask),
    AutomationTasks {
        tasks: Vec<AutomationTask>,
    },
    MemoryFederationCapability(MemoryFederationCapabilitySnapshot),
    MemoryFederationCapabilities {
        capabilities: Vec<MemoryFederationCapabilitySnapshot>,
    },
    MemoryFederationStatus {
        capability: Option<MemoryFederationCapabilitySnapshot>,
    },
    Error {
        code: String,
        message: String,
    },
}

/// A bounded read from the owning Agent's canonical SQLite store. The digest
/// identifies an observed cut; it is not a grant or a promise of future freshness.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveContextSnapshot {
    pub snapshot_digest: String,
    pub read_digest: String,
    pub omitted_records: u64,
    pub items: Vec<CognitiveContextItem>,
    pub plan: Option<CognitiveContextPlan>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveContextPlan {
    /// Binds the evaluated context with `plan: null`, before any abstention.
    pub evaluated_context_digest: String,
    pub plan_receipt_digest: String,
    pub read_allowed: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveContextItem {
    pub memory_id: String,
    pub revision: u64,
    pub content: String,
    pub content_sha256: String,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HealthSnapshot {
    /// True once the App Server initialized while this exact spawn still owns Starting.
    pub promotion_ready: bool,
    /// True only after the supervisor promoted this spawn to Running.
    pub ready: bool,
    pub fenced: bool,
    pub lifecycle: AgentLifecycle,
    pub process_id: u32,
    pub workspace: PathBuf,
    pub home_root: PathBuf,
    pub run_root: PathBuf,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LifecycleSnapshot {
    pub lifecycle: AgentLifecycle,
    pub app_server_ready: bool,
    pub fenced: bool,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SessionIngress {
    pub socket_path: PathBuf,
    pub transport: SessionTransport,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SessionTransport {
    CodexAppServerWebsocketOverUds,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdEvent {
    pub cursor: u64,
    pub kind: AgentdEventKind,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum AgentdEventKind {
    Bootstrapped,
    Lifecycle {
        lifecycle: AgentLifecycle,
        generation: u64,
    },
    AppServerReady,
    Draining,
    GenerationFenced,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EventBatch {
    pub events: Vec<AgentdEvent>,
    pub gap: bool,
    pub next_cursor: u64,
    pub latest_cursor: u64,
}

/// Exact host-bound turn/lease identity transported across the Agentd
/// boundary.
///
/// This is a qualification contract only.  It carries the witness that a
/// supervisor can later bind to an Agent-local append-only lease CAS, but the
/// current protocol has no method that grants authority from this value.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct HostTurnAuthorityBinding {
    pub schema_version: u32,
    pub owner_agent_id: AgentId,
    pub lease_id: String,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: String,
    pub lease_expires_at_unix_seconds: u64,
    pub lease_head_sha256: Sha256Digest,
}

impl HostTurnAuthorityBinding {
    #[expect(
        clippy::too_many_arguments,
        reason = "authority binding constructor keeps all signed identity fields explicit"
    )]
    pub fn new(
        owner_agent_id: AgentId,
        lease_id: impl Into<String>,
        authority_epoch: u64,
        owner_epoch: u64,
        generation: u64,
        fencing_token: impl Into<String>,
        lease_expires_at_unix_seconds: u64,
        lease_head_sha256: Sha256Digest,
    ) -> Result<Self, String> {
        let binding = Self {
            schema_version: HOST_TURN_AUTHORITY_BINDING_SCHEMA_VERSION,
            owner_agent_id,
            lease_id: lease_id.into(),
            authority_epoch,
            owner_epoch,
            generation,
            fencing_token: fencing_token.into(),
            lease_expires_at_unix_seconds,
            lease_head_sha256,
        };
        binding.validate()?;
        Ok(binding)
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema_version != HOST_TURN_AUTHORITY_BINDING_SCHEMA_VERSION {
            return Err("unsupported host turn authority binding schema".to_string());
        }
        validate_protocol_text(&self.lease_id, "lease id", /*max_bytes*/ 512)?;
        validate_protocol_text(&self.fencing_token, "fencing token", /*max_bytes*/ 256)?;
        if self.authority_epoch == 0 {
            return Err("authority epoch must be non-zero".to_string());
        }
        if self.owner_epoch == 0 {
            return Err("owner epoch must be non-zero".to_string());
        }
        if self.generation == 0 {
            return Err("lease generation must be non-zero".to_string());
        }
        if self.lease_expires_at_unix_seconds == 0 {
            return Err("lease expiry must be non-zero".to_string());
        }
        Ok(())
    }
}

impl<'de> Deserialize<'de> for HostTurnAuthorityBinding {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: serde::Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            schema_version: u32,
            owner_agent_id: AgentId,
            lease_id: String,
            authority_epoch: u64,
            owner_epoch: u64,
            generation: u64,
            fencing_token: String,
            lease_expires_at_unix_seconds: u64,
            lease_head_sha256: Sha256Digest,
        }

        let wire = Wire::deserialize(deserializer)?;
        let binding = Self {
            schema_version: wire.schema_version,
            owner_agent_id: wire.owner_agent_id,
            lease_id: wire.lease_id,
            authority_epoch: wire.authority_epoch,
            owner_epoch: wire.owner_epoch,
            generation: wire.generation,
            fencing_token: wire.fencing_token,
            lease_expires_at_unix_seconds: wire.lease_expires_at_unix_seconds,
            lease_head_sha256: wire.lease_head_sha256,
        };
        binding.validate().map_err(serde::de::Error::custom)?;
        Ok(binding)
    }
}

fn validate_protocol_text(value: &str, label: &str, max_bytes: usize) -> Result<(), String> {
    if value.trim().is_empty() || value.len() > max_bytes || value.as_bytes().contains(&0) {
        return Err(format!(
            "{label} must contain 1..={max_bytes} non-NUL bytes"
        ));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn capabilities_endpoint_is_additive_and_bounded() {
        let request = AgentdRequest::capabilities(1, 1);
        let bytes = serde_json::to_vec(&request).expect("serialize capabilities request");
        assert!(bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&bytes).unwrap(),
            request
        );
        let payload = AgentdPayload::Capabilities(AgentdCapabilitySet::empty());
        let payload_bytes = serde_json::to_vec(&payload).expect("serialize capabilities payload");
        assert_eq!(
            serde_json::from_slice::<AgentdPayload>(&payload_bytes).unwrap(),
            payload
        );
    }

    #[test]
    fn health_wire_round_trip_is_strict_and_bounded() {
        let request = AgentdRequest::health(7, 11);
        let request_bytes = serde_json::to_vec(&request).expect("serialize request");
        assert!(request_bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&request_bytes).expect("parse request"),
            request
        );

        let response = AgentdResponse {
            schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
            request_id: 7,
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent id"),
            spawn_generation: 11,
            current_generation: 11,
            payload: AgentdPayload::Health(HealthSnapshot {
                promotion_ready: true,
                ready: true,
                fenced: false,
                lifecycle: AgentLifecycle::Running,
                process_id: 17,
                workspace: PathBuf::from("/tmp/workspace"),
                home_root: PathBuf::from("/tmp/home"),
                run_root: PathBuf::from("/tmp/run"),
            }),
        };
        let response_bytes = serde_json::to_vec(&response).expect("serialize response");
        assert!(response_bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdResponse>(&response_bytes).expect("parse response"),
            response
        );
    }

    #[test]
    fn automation_wire_round_trip_is_strict_and_bounded() {
        let mut draft = AutomationTaskDraft::new(
            "019153a4-3088-7e03-a56a-9b1964f75ddd",
            "x".repeat(32 * 1024),
            codex_hepta_automation::AutomationSchedule::Once,
            123,
            100,
        );
        draft.task_id =
            AutomationTaskId::parse("019153a4-3088-7000-a56a-9b1964f75001").expect("task id");
        let request = AgentdRequest::automation_create(9, 3, draft);
        let bytes = serde_json::to_vec(&request).expect("serialize request");
        assert!(bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&bytes).expect("parse request"),
            request
        );
    }

    #[test]
    fn memory_federation_control_is_typed_strict_and_bounded() {
        let consumer = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dd3").expect("consumer id");
        let grant = AgentdRequest::memory_federation_grant(
            10,
            3,
            consumer,
            MemoryFederationScopeKind::WorkspacePrivate,
            3_600,
        );
        let grant_bytes = serde_json::to_vec(&grant).expect("serialize grant");
        assert!(grant_bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&grant_bytes).expect("parse grant"),
            grant
        );

        let capability_id =
            MemoryFederationCapabilityId::parse(format!("federation:v1:{}", "a".repeat(64)))
                .expect("capability id");
        let revoke = AgentdRequest::memory_federation_revoke(11, 3, capability_id);
        let revoke_bytes = serde_json::to_vec(&revoke).expect("serialize revoke");
        assert!(revoke_bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&revoke_bytes).expect("parse revoke"),
            revoke
        );

        let malformed = String::from_utf8(revoke_bytes)
            .expect("utf8")
            .replace(&"a".repeat(64), "not-a-digest");
        assert!(serde_json::from_str::<AgentdRequest>(&malformed).is_err());
    }

    #[test]
    fn run_lifecycle_wire_binds_complete_snapshot_and_cancel_reason() {
        let snapshot = RunSnapshot {
            run_id: "run.1".to_string(),
            request_digest: "1".repeat(64),
            objective_digest: "2".repeat(64),
            body_digest: "3".repeat(64),
            artifact_set_digest: "4".repeat(64),
            authority_epoch: 9,
            deadline_ms: 12_345,
        };
        let start = AgentdRequest::run_start(21, 3, snapshot.clone());
        let bytes = serde_json::to_vec(&start).expect("serialize run start");
        assert!(bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&bytes).expect("parse run start"),
            start
        );

        let attachment = ContextAttachment {
            run_id: snapshot.run_id.clone(),
            request_digest: snapshot.request_digest.clone(),
            objective_digest: snapshot.objective_digest.clone(),
            body_digest: snapshot.body_digest.clone(),
            artifact_set_digest: snapshot.artifact_set_digest.clone(),
            authority_epoch: snapshot.authority_epoch,
            deadline_ms: snapshot.deadline_ms,
            context_digest: "5".repeat(64),
            compilation_receipt_digest: "6".repeat(64),
        };
        let attach = AgentdRequest::run_attach_context(22, 3, 1, attachment);
        let attach_bytes = serde_json::to_vec(&attach).expect("serialize attach");
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&attach_bytes).expect("parse attach"),
            attach
        );

        let dispatch_binding = RunDispatchBinding::new(
            snapshot.run_id.clone(),
            "5".repeat(64),
            "thread.1",
            "7".repeat(64),
        )
        .expect("dispatch binding");
        let dispatch = AgentdRequest::run_mark_dispatched(
            23,
            3,
            snapshot.run_id.clone(),
            2,
            dispatch_binding.clone(),
        );
        let dispatch_bytes = serde_json::to_vec(&dispatch).expect("serialize dispatch");
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&dispatch_bytes).expect("parse dispatch"),
            dispatch
        );

        let execution_binding = RunExecutionBinding::new(
            snapshot.run_id.clone(),
            dispatch_binding.binding_digest.clone(),
            dispatch_binding.thread_id.clone(),
            "turn.1",
        )
        .expect("execution binding");
        let bind = AgentdRequest::run_bind_execution(
            24,
            3,
            snapshot.run_id.clone(),
            3,
            execution_binding.clone(),
        );
        let bind_bytes = serde_json::to_vec(&bind).expect("serialize execution binding");
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&bind_bytes).expect("parse execution binding"),
            bind
        );

        let terminal = RunTerminalObservation::new(
            snapshot.run_id.clone(),
            dispatch_binding.binding_digest,
            execution_binding.binding_digest,
            execution_binding.thread_id,
            execution_binding.turn_id,
            RunPhase::Succeeded,
        )
        .expect("terminal observation");
        let observe = AgentdRequest::run_observe_terminal(
            25,
            3,
            snapshot.run_id.clone(),
            4,
            RunPhase::Succeeded,
            Some(terminal),
        );
        let observe_bytes = serde_json::to_vec(&observe).expect("serialize terminal observation");
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&observe_bytes)
                .expect("parse terminal observation"),
            observe
        );

        let cancel =
            AgentdRequest::run_cancel(26, 3, snapshot.run_id, 4, "operator_requested".to_string());
        let cancel_bytes = serde_json::to_vec(&cancel).expect("serialize cancel");
        assert_eq!(
            serde_json::from_slice::<AgentdRequest>(&cancel_bytes).expect("parse cancel"),
            cancel
        );

        let payload = AgentdPayload::RunCancellation {
            disposition: CancellationDisposition::CancellingAfterDispatch,
            receipt: RunReceipt {
                run_id: "run.1".to_string(),
                revision: 3,
                phase: RunPhase::Cancelling,
                context_digest: Some("5".repeat(64)),
                terminal_observed: false,
                idempotent: false,
                cancel_reason: Some("operator_requested".to_string()),
                cancellation_ack_deadline_ms: Some(13_000),
            },
        };
        let payload_bytes = serde_json::to_vec(&payload).expect("serialize run payload");
        assert_eq!(
            serde_json::from_slice::<AgentdPayload>(&payload_bytes).expect("parse run payload"),
            payload
        );
    }

    #[test]
    fn host_turn_authority_binding_is_strict_and_fail_closed() {
        let owner = AgentId::parse("019153a4-3088-7e03-a56a-9b1964f75dde").expect("owner id");
        let binding = HostTurnAuthorityBinding::new(
            owner,
            "lease:transport-witness",
            7,
            11,
            3,
            "fence:transport-witness",
            1_900_000_000,
            Sha256Digest::for_bytes(b"transport-head"),
        )
        .expect("valid host authority binding");
        let bytes = serde_json::to_vec(&binding).expect("serialize host binding");
        assert!(bytes.len() as u64 <= MAX_CONTROL_FRAME_BYTES);
        assert_eq!(
            serde_json::from_slice::<HostTurnAuthorityBinding>(&bytes).expect("parse host binding"),
            binding
        );

        let mut zero_epoch = serde_json::to_string(&binding).expect("json");
        zero_epoch = zero_epoch.replace("\"authority_epoch\":7", "\"authority_epoch\":0");
        assert!(serde_json::from_str::<HostTurnAuthorityBinding>(&zero_epoch).is_err());

        let unknown = serde_json::to_string(&binding)
            .expect("json")
            .replace('}', ",\"unexpected\":true}");
        assert!(serde_json::from_str::<HostTurnAuthorityBinding>(&unknown).is_err());

        assert!(
            HostTurnAuthorityBinding::new(
                binding.owner_agent_id,
                binding.lease_id.clone(),
                binding.authority_epoch,
                binding.owner_epoch,
                binding.generation,
                "\0",
                binding.lease_expires_at_unix_seconds,
                binding.lease_head_sha256,
            )
            .is_err()
        );
    }
}
