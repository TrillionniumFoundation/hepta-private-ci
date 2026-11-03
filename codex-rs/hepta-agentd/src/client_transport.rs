use std::time::Duration;

use codex_uds::UnixStream;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::time::timeout;

use super::AgentdClient;
use crate::AGENTD_CONTROL_OVERLOAD_FRAME;
use crate::AGENTD_CONTROL_SCHEMA_VERSION;
use crate::AGENTD_OVERLOAD_RETRY_AFTER_MS;
use crate::AgentdError;
use crate::AgentdRequest;
use crate::AgentdResponse;
use crate::MAX_CONTROL_FRAME_BYTES;

pub(super) enum ResponseObservation {
    Standard,
    Objective(Duration),
}

impl ResponseObservation {
    fn failure(&self, error: AgentdError) -> AgentdError {
        match self {
            Self::Standard => error,
            Self::Objective(_) => AgentdError::Protocol(format!(
                "Objective outcome is unknown; reconcile the original identity: {error}"
            )),
        }
    }
}

impl AgentdClient {
    pub(super) async fn send(&self, request: AgentdRequest) -> Result<AgentdResponse, AgentdError> {
        self.send_observing(request, ResponseObservation::Standard)
            .await
    }

    pub(super) async fn send_observing(
        &self,
        request: AgentdRequest,
        observation: ResponseObservation,
    ) -> Result<AgentdResponse, AgentdError> {
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
            .map_err(|_| {
                observation.failure(AgentdError::Protocol(
                    "agentd control write timed out".to_string(),
                ))
            })?
            .map_err(|error| observation.failure(error.into()))?;
        let mut reader = BufReader::new(reader).take(MAX_CONTROL_FRAME_BYTES + 1);
        let mut response_bytes = Vec::new();
        let response_timeout = match &observation {
            ResponseObservation::Standard => self.timeout,
            ResponseObservation::Objective(timeout) => *timeout,
        };
        let count = timeout(
            response_timeout,
            reader.read_until(b'\n', &mut response_bytes),
        )
        .await
        .map_err(|_| {
            observation.failure(AgentdError::Protocol(
                "agentd control read timed out".to_string(),
            ))
        })?
        .map_err(|error| observation.failure(error.into()))?;
        if count == 0 || count as u64 > MAX_CONTROL_FRAME_BYTES || !response_bytes.ends_with(b"\n")
        {
            return Err(observation.failure(AgentdError::Protocol(
                "agentd returned an invalid bounded response frame".to_string(),
            )));
        }
        if response_bytes.as_slice() == AGENTD_CONTROL_OVERLOAD_FRAME {
            return Err(AgentdError::Overloaded {
                retry_after_ms: AGENTD_OVERLOAD_RETRY_AFTER_MS,
            });
        }
        let response: AgentdResponse = serde_json::from_slice(&response_bytes)
            .map_err(|error| observation.failure(error.into()))?;
        if response.schema_version != AGENTD_CONTROL_SCHEMA_VERSION
            || response.request_id != expected_request_id
            || response.agent_id != self.expected_agent_id
            || response.spawn_generation != self.spawn_generation
        {
            return Err(observation.failure(AgentdError::Protocol(
                "agentd response identity does not match request".to_string(),
            )));
        }
        Ok(response)
    }
}
