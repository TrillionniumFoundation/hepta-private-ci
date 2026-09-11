use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_automation::AutomationTask;
use codex_hepta_automation::AutomationTaskDraft;
use codex_hepta_automation::AutomationTaskId;
use codex_hepta_contracts::AgentId;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::timeout;

use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::EventBatch;
use crate::HealthSnapshot;
use crate::LifecycleSnapshot;
use crate::MAX_CONTROL_FRAME_BYTES;
use crate::MemoryFederationCapabilityId;
use crate::MemoryFederationCapabilitySnapshot;
use crate::MemoryFederationScopeKind;
use crate::SessionIngress;

pub struct AgentdClient {
    socket_path: PathBuf,
    expected_agent_id: AgentId,
    spawn_generation: u64,
    next_request_id: AtomicU64,
    timeout: Duration,
}

impl AgentdClient {
    pub fn new(
        socket_path: PathBuf,
        expected_agent_id: AgentId,
        spawn_generation: u64,
    ) -> Result<Self, AgentdError> {
        if !socket_path.is_absolute() || spawn_generation == 0 {
            return Err(AgentdError::Invalid(
                "agentd client requires an absolute socket and non-zero spawn generation"
                    .to_string(),
            ));
        }
        Ok(Self {
            socket_path,
            expected_agent_id,
            spawn_generation,
            next_request_id: AtomicU64::new(1),
            timeout: Duration::from_secs(2),
        })
    }

    pub async fn health(&self) -> Result<HealthSnapshot, AgentdError> {
        match self
            .send(AgentdRequest::health(
                self.request_id(),
                self.spawn_generation,
            ))
            .await?
            .payload
        {
            AgentdPayload::Health(snapshot) => Ok(snapshot),
            payload => unexpected(payload),
        }
    }

    pub async fn lifecycle(&self) -> Result<LifecycleSnapshot, AgentdError> {
        match self
            .send(AgentdRequest::lifecycle(
                self.request_id(),
                self.spawn_generation,
            ))
            .await?
            .payload
        {
            AgentdPayload::Lifecycle(snapshot) => Ok(snapshot),
            payload => unexpected(payload),
        }
    }

    pub async fn session_ingress(&self) -> Result<SessionIngress, AgentdError> {
        match self
            .send(AgentdRequest::session_ingress(
                self.request_id(),
                self.spawn_generation,
            ))
            .await?
            .payload
        {
            AgentdPayload::SessionIngress(ingress) => Ok(ingress),
            payload => unexpected(payload),
        }
    }

    /// Read verified context through this exact generation's canonical owner.
    pub async fn cognitive_context(
        &self,
        query: String,
        limit: u16,
    ) -> Result<crate::CognitiveContextSnapshot, AgentdError> {
        match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::CognitiveContext { query, limit },
            })
            .await?
            .payload
        {
            AgentdPayload::CognitiveContext(snapshot) => Ok(snapshot),
            payload => unexpected(payload),
        }
    }

    /// Submit text signed by a separately trusted owner-configured issuer.
    pub async fn submit_authbus_text(
        &self,
        request: crate::AuthBusTextIngress,
    ) -> Result<crate::AuthBusTextStatus, AgentdError> {
        match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::AuthBusText { request },
            })
            .await?
            .payload
        {
            AgentdPayload::AuthBusTextStatus(status) => Ok(status),
            payload => unexpected(payload),
        }
    }

    /// Observe queue-admission state; this never reports model/effect completion.
    pub async fn authbus_text_status(
        &self,
        delivery_id: String,
    ) -> Result<crate::AuthBusTextStatus, AgentdError> {
        match self
            .send(AgentdRequest {
                schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                request_id: self.request_id(),
                spawn_generation: self.spawn_generation,
                method: crate::AgentdMethod::AuthBusTextStatus { delivery_id },
            })
            .await?
            .payload
        {
            AgentdPayload::AuthBusTextStatus(status) => Ok(status),
            payload => unexpected(payload),
        }
    }

    pub async fn events(&self, after_cursor: u64, limit: u16) -> Result<EventBatch, AgentdError> {
        match self
            .send(AgentdRequest::events(
                self.request_id(),
                self.spawn_generation,
                after_cursor,
                limit,
            ))
            .await?
            .payload
        {
            AgentdPayload::Events(events) => Ok(events),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_create(
        &self,
        draft: AutomationTaskDraft,
    ) -> Result<AutomationTask, AgentdError> {
        match self
            .send(AgentdRequest::automation_create(
                self.request_id(),
                self.spawn_generation,
                draft,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationTask(task) => Ok(task),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_list(&self, limit: u16) -> Result<Vec<AutomationTask>, AgentdError> {
        match self
            .send(AgentdRequest::automation_list(
                self.request_id(),
                self.spawn_generation,
                limit,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationTasks { tasks } => Ok(tasks),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_cancel(
        &self,
        task_id: AutomationTaskId,
    ) -> Result<AutomationTask, AgentdError> {
        match self
            .send(AgentdRequest::automation_cancel(
                self.request_id(),
                self.spawn_generation,
                task_id,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationTask(task) => Ok(task),
            payload => unexpected(payload),
        }
    }

    pub async fn automation_set_enabled(
        &self,
        task_id: AutomationTaskId,
        enabled: bool,
        resume_at_ms: Option<u64>,
    ) -> Result<AutomationTask, AgentdError> {
        match self
            .send(AgentdRequest::automation_set_enabled(
                self.request_id(),
                self.spawn_generation,
                task_id,
                enabled,
                resume_at_ms,
            ))
            .await?
            .payload
        {
            AgentdPayload::AutomationTask(task) => Ok(task),
            payload => unexpected(payload),
        }
    }

    pub async fn memory_federation_grant(
        &self,
        consumer_agent_id: AgentId,
        owner_scope: MemoryFederationScopeKind,
        lifetime_seconds: u32,
    ) -> Result<MemoryFederationCapabilitySnapshot, AgentdError> {
        match self
            .send(AgentdRequest::memory_federation_grant(
                self.request_id(),
                self.spawn_generation,
                consumer_agent_id,
                owner_scope,
                lifetime_seconds,
            ))
            .await?
            .payload
        {
            AgentdPayload::MemoryFederationCapability(capability) => Ok(capability),
            payload => unexpected(payload),
        }
    }

    pub async fn memory_federation_revoke(
        &self,
        capability_id: MemoryFederationCapabilityId,
    ) -> Result<MemoryFederationCapabilitySnapshot, AgentdError> {
        match self
            .send(AgentdRequest::memory_federation_revoke(
                self.request_id(),
                self.spawn_generation,
                capability_id,
            ))
            .await?
            .payload
        {
            AgentdPayload::MemoryFederationCapability(capability) => Ok(capability),
            payload => unexpected(payload),
        }
    }

    pub async fn memory_federation_list(
        &self,
        limit: u16,
    ) -> Result<Vec<MemoryFederationCapabilitySnapshot>, AgentdError> {
        match self
            .send(AgentdRequest::memory_federation_list(
                self.request_id(),
                self.spawn_generation,
                limit,
            ))
            .await?
            .payload
        {
            AgentdPayload::MemoryFederationCapabilities { capabilities } => Ok(capabilities),
            payload => unexpected(payload),
        }
    }

    pub async fn memory_federation_status(
        &self,
        capability_id: MemoryFederationCapabilityId,
    ) -> Result<Option<MemoryFederationCapabilitySnapshot>, AgentdError> {
        match self
            .send(AgentdRequest::memory_federation_status(
                self.request_id(),
                self.spawn_generation,
                capability_id,
            ))
            .await?
            .payload
        {
            AgentdPayload::MemoryFederationStatus { capability } => Ok(capability),
            payload => unexpected(payload),
        }
    }

    async fn send(&self, request: AgentdRequest) -> Result<AgentdResponse, AgentdError> {
        let expected_request_id = request.request_id;
        let stream = timeout(self.timeout, UnixStream::connect(&self.socket_path))
            .await
            .map_err(|_| AgentdError::Protocol("agentd control connect timed out".to_string()))??;
        let (reader, mut writer) = tokio::io::split(stream);
        let mut bytes = serde_json::to_vec(&request)?;
        bytes.push(b'\n');
        if bytes.len() as u64 > MAX_CONTROL_FRAME_BYTES {
            return Err(AgentdError::Protocol(
                "agentd request exceeded frame bound".to_string(),
            ));
        }
        timeout(self.timeout, writer.write_all(&bytes))
            .await
            .map_err(|_| AgentdError::Protocol("agentd control write timed out".to_string()))??;
        let mut reader = BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1);
        let mut response_bytes = Vec::new();
        let count = timeout(self.timeout, reader.read_until(b'\n', &mut response_bytes))
            .await
            .map_err(|_| AgentdError::Protocol("agentd control read timed out".to_string()))??;
        if count == 0 || count as u64 > MAX_CONTROL_FRAME_BYTES || !response_bytes.ends_with(b"\n")
        {
            return Err(AgentdError::Protocol(
                "agentd returned an invalid bounded response frame".to_string(),
            ));
        }
        let response: AgentdResponse = serde_json::from_slice(&response_bytes)?;
        if response.schema_version != AGENTD_CONTROL_SCHEMA_VERSION
            || response.request_id != expected_request_id
            || response.agent_id != self.expected_agent_id
            || response.spawn_generation != self.spawn_generation
        {
            return Err(AgentdError::Protocol(
                "agentd response identity does not match request".to_string(),
            ));
        }
        Ok(response)
    }

    fn request_id(&self) -> u64 {
        self.next_request_id.fetch_add(1, Ordering::Relaxed)
    }
}

fn unexpected<T>(payload: AgentdPayload) -> Result<T, AgentdError> {
    match payload {
        AgentdPayload::Error { code, message } => Err(AgentdError::Protocol(format!(
            "agentd rejected request ({code}): {message}"
        ))),
        other => Err(AgentdError::Protocol(format!(
            "agentd returned unexpected payload {other:?}"
        ))),
    }
}
