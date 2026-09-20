use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ReleaseId;
use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::timeout;

use crate::SupervisorError;
use crate::daemon_protocol::MAX_SUPERVISORD_CONTROL_FRAME_BYTES;
use crate::daemon_protocol::SUPERVISORD_CONTROL_SCHEMA_VERSION;
use crate::daemon_protocol::SupervisordAgentStatus;
use crate::daemon_protocol::SupervisordControlFence;
use crate::daemon_protocol::SupervisordHealth;
use crate::daemon_protocol::SupervisordMethod;
use crate::daemon_protocol::SupervisordMutationAccepted;
use crate::daemon_protocol::SupervisordPayload;
use crate::daemon_protocol::SupervisordRequest;
use crate::daemon_protocol::SupervisordResponse;

pub struct SupervisordClient {
    socket_path: PathBuf,
    next_request_id: AtomicU64,
    timeout: Duration,
}

impl SupervisordClient {
    pub fn new(socket_path: PathBuf) -> Result<Self, SupervisorError> {
        if !socket_path.is_absolute() {
            return Err(SupervisorError::Invalid(
                "supervisord client requires an absolute socket path".to_string(),
            ));
        }
        Ok(Self {
            socket_path,
            next_request_id: AtomicU64::new(1),
            timeout: Duration::from_secs(2),
        })
    }

    pub async fn health(&self) -> Result<SupervisordHealth, SupervisorError> {
        match self.send(SupervisordMethod::Health).await? {
            SupervisordPayload::Health(health) => Ok(health),
            payload => unexpected(payload),
        }
    }

    pub async fn roster(&self, limit: u16) -> Result<Vec<SupervisordAgentStatus>, SupervisorError> {
        match self.send(SupervisordMethod::Roster { limit }).await? {
            SupervisordPayload::Roster { agents } => Ok(agents),
            payload => unexpected(payload),
        }
    }

    pub async fn snapshot(
        &self,
        agent_id: AgentId,
    ) -> Result<SupervisordAgentStatus, SupervisorError> {
        self.agent(SupervisordMethod::Snapshot { agent_id }).await
    }

    pub async fn start(
        &self,
        fence: SupervisordControlFence,
        release_id: ReleaseId,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Start { fence, release_id })
            .await
    }

    pub async fn drain(
        &self,
        fence: SupervisordControlFence,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Drain { fence }).await
    }

    pub async fn stop(
        &self,
        fence: SupervisordControlFence,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Stop { fence }).await
    }

    pub async fn kill(
        &self,
        fence: SupervisordControlFence,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Kill { fence }).await
    }

    pub async fn restart(
        &self,
        fence: SupervisordControlFence,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Restart { fence }).await
    }

    pub async fn upgrade(
        &self,
        fence: SupervisordControlFence,
        release_id: ReleaseId,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Upgrade { fence, release_id })
            .await
    }

    pub async fn rollback(
        &self,
        fence: SupervisordControlFence,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        self.mutation(SupervisordMethod::Rollback { fence }).await
    }

    async fn agent(
        &self,
        method: SupervisordMethod,
    ) -> Result<SupervisordAgentStatus, SupervisorError> {
        match self.send(method).await? {
            SupervisordPayload::Agent(status) => Ok(status),
            payload => unexpected(payload),
        }
    }

    async fn mutation(
        &self,
        method: SupervisordMethod,
    ) -> Result<SupervisordMutationAccepted, SupervisorError> {
        match self.send(method).await? {
            SupervisordPayload::MutationAccepted {
                operation,
                accepted_state_digest,
                agent,
                production_receipt,
            } => Ok(SupervisordMutationAccepted {
                operation,
                accepted_state_digest,
                agent,
                production_receipt,
            }),
            payload => unexpected(payload),
        }
    }

    async fn send(&self, method: SupervisordMethod) -> Result<SupervisordPayload, SupervisorError> {
        let request_id = self.next_request_id.fetch_add(1, Ordering::Relaxed);
        let request = SupervisordRequest::new(request_id, method);
        request
            .validate()
            .map_err(|_| SupervisorError::Invalid("invalid supervisord request".to_string()))?;
        let stream = timeout(self.timeout, UnixStream::connect(&self.socket_path))
            .await
            .map_err(|_| SupervisorError::Invalid("supervisord connect timed out".to_string()))??;
        let (reader, mut writer) = tokio::io::split(stream);
        let mut bytes = serde_json::to_vec(&request)
            .map_err(|error| SupervisorError::Invalid(format!("encode request: {error}")))?;
        bytes.push(b'\n');
        if bytes.len() as u64 > MAX_SUPERVISORD_CONTROL_FRAME_BYTES {
            return Err(SupervisorError::Invalid(
                "supervisord request exceeded frame bound".to_string(),
            ));
        }
        timeout(self.timeout, writer.write_all(&bytes))
            .await
            .map_err(|_| SupervisorError::Invalid("supervisord write timed out".to_string()))??;
        writer.shutdown().await?;
        let mut reader = BufReader::new(reader).take(MAX_SUPERVISORD_CONTROL_FRAME_BYTES + 1);
        let mut response_bytes = Vec::new();
        let count = timeout(self.timeout, reader.read_until(b'\n', &mut response_bytes))
            .await
            .map_err(|_| SupervisorError::Invalid("supervisord read timed out".to_string()))??;
        if count == 0
            || count as u64 > MAX_SUPERVISORD_CONTROL_FRAME_BYTES
            || !response_bytes.ends_with(b"\n")
        {
            return Err(SupervisorError::Invalid(
                "supervisord returned an invalid bounded response".to_string(),
            ));
        }
        let response: SupervisordResponse = serde_json::from_slice(&response_bytes)
            .map_err(|error| SupervisorError::Invalid(format!("decode response: {error}")))?;
        if response.schema_version != SUPERVISORD_CONTROL_SCHEMA_VERSION
            || response.request_id != request_id
        {
            return Err(SupervisorError::Invalid(
                "supervisord response identity does not match request".to_string(),
            ));
        }
        match response.payload {
            SupervisordPayload::Error {
                code,
                message,
                actual: _,
            } => Err(SupervisorError::Invalid(format!(
                "supervisord rejected request ({code}): {message}"
            ))),
            payload => Ok(payload),
        }
    }
}

fn unexpected<T>(payload: SupervisordPayload) -> Result<T, SupervisorError> {
    Err(SupervisorError::Invalid(format!(
        "supervisord returned unexpected payload {payload:?}"
    )))
}
